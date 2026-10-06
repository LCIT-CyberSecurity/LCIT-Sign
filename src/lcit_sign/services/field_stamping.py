"""Elements placed on a document (signature, date, text, logo) and how they
end up on the signed PDF.

An operator prepares a draft version by placing elements on its pages (the
editor stores them as fractions of the page, origin top-left). At signing time
each element is resolved to its final value — automatic ones from the signer's
authenticated identity and the time of signing, free text from what the signer
typed — and stamped onto a copy of the original. The original file is never
touched, and the resolved list is stored with the signature and covered by its
evidence hash, so it can be re-verified later whatever happens to the editor.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from typing import Any
from zoneinfo import ZoneInfo

from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

from lcit_sign.models.document import AUTOMATIC_KINDS, INPUT_KINDS, FieldKind
from lcit_sign.services.signature_pdf import _SIGNATURE_FONT_NAME, _ensure_font_registered

MAX_TEXT_LENGTH = 500
_INK = HexColor("#101828")
_SIGNATURE_INK = HexColor("#1f2a5c")


class FieldError(ValueError):
    """The prepared elements or the values supplied for them are not usable."""


@dataclass(frozen=True)
class PreparedField:
    id: str
    page: int
    x: float
    y: float
    width: float
    height: float
    kind: FieldKind
    label: str = ""
    required: bool = True
    role: int = 1
    group_key: str | None = None


@dataclass(frozen=True)
class PageSize:
    width: float
    height: float


def _visual_box(page: Any) -> tuple[float, float, float, float]:
    """(left, bottom, width, height) of the page as a viewer shows it."""
    box = page.cropbox
    left, bottom = float(box.left), float(box.bottom)
    width, height = float(box.width), float(box.height)
    if int(page.get("/Rotate", 0) or 0) % 180 == 90:
        width, height = height, width
    return left, bottom, width, height


def page_sizes(pdf: bytes) -> list[PageSize]:
    """Visual size of every page, in PDF points (what the editor needs to
    draw pages in the right proportions)."""
    sizes = []
    for page in PdfReader(BytesIO(pdf)).pages:
        _, _, width, height = _visual_box(page)
        sizes.append(PageSize(width, height))
    return sizes


def validate_layout(fields: list[PreparedField], page_count: int) -> None:
    if len(fields) > 200:
        raise FieldError("Too many elements on one document (200 at most)")
    for field in fields:
        where = f"element « {field.label or field.kind.value} »"
        if not 1 <= field.page <= page_count:
            raise FieldError(f"{where}: page {field.page} does not exist")
        if not (0 <= field.x <= 1 and 0 <= field.y <= 1):
            raise FieldError(f"{where}: position outside the page")
        if not (0.005 <= field.width <= 1 and 0.005 <= field.height <= 1):
            raise FieldError(f"{where}: invalid size")
        if field.x + field.width > 1.0001 or field.y + field.height > 1.0001:
            raise FieldError(f"{where}: runs past the edge of the page")
        if not 1 <= field.role <= 10:
            raise FieldError(f"{where}: role must be between 1 and 10")
        if len(field.label) > 120:
            raise FieldError(f"{where}: label too long")


def resolve(
    fields: list[PreparedField],
    *,
    role: int = 1,
    signer_name: str,
    signer_email: str,
    signed_at: datetime,
    inputs: dict[str, str],
    logo_sha256: str | None,
    signer_first_name: str = "",
    signer_last_name: str = "",
    tz: str = "Europe/Paris",
    preview: bool = False,
) -> list[dict[str, Any]]:
    """Final value of each of this signer's elements, as stored with the
    signature. Raises FieldError for a missing required input, an unknown
    input id, or a logo that was never configured.

    With `preview` it is what the signer is shown BEFORE signing: nothing is refused (an
    answer not typed yet shows its label in brackets, a missing logo is left out), and each
    element is flagged so that it is drawn as "not signed yet". It is never stored."""
    mine = [f for f in fields if f.role == role]
    typed = {f.id for f in mine if f.kind in INPUT_KINDS}
    # "Today" and "now" are the signer's, not UTC's: just after midnight in Paris
    # it is already tomorrow's date.
    local = signed_at.astimezone(ZoneInfo(tz))
    first = signer_first_name or signer_name.partition(" ")[0]
    last = signer_last_name or signer_name.partition(" ")[2]
    unknown = set(inputs) - {f.id for f in fields}
    if unknown:
        raise FieldError("Values were supplied for elements that do not exist")
    stray = set(inputs) - typed
    if stray:
        raise FieldError("Values were supplied for elements that are filled automatically")

    # Elements sharing a group key are filled once and apply to all of them.
    shared: dict[str, str] = {}
    for f in mine:
        if f.kind in INPUT_KINDS and f.group_key and inputs.get(f.id, "").strip():
            shared.setdefault(f.group_key, inputs[f.id].strip())

    resolved: list[dict[str, Any]] = []
    missing: list[str] = []
    for f in mine:
        if f.kind in INPUT_KINDS:
            value = inputs.get(f.id, "").strip() or (shared.get(f.group_key or "", ""))
            default_label = "Lieu" if f.kind == FieldKind.PLACE else "Texte"
            if len(value) > MAX_TEXT_LENGTH:
                label = f.label or default_label
                raise FieldError(f"« {label} » is too long ({MAX_TEXT_LENGTH} max)")
            if not value and preview:
                value = f"[{f.label or default_label}]"
            elif not value and f.required:
                missing.append(f.label or default_label)
                continue
            elif not value:
                continue
        elif f.kind == FieldKind.DATE:
            value = local.strftime("%d/%m/%Y")
        elif f.kind == FieldKind.TIME:
            value = local.strftime("%H:%M")
        elif f.kind in (FieldKind.SIGNATURE, FieldKind.FULL_NAME):
            value = signer_name
        elif f.kind == FieldKind.FIRST_NAME:
            value = first
        elif f.kind == FieldKind.LAST_NAME:
            value = last
        elif f.kind == FieldKind.EMAIL:
            value = signer_email
        elif f.kind == FieldKind.LOGO:
            if not logo_sha256 and preview:
                continue
            if not logo_sha256:
                raise FieldError("Aucun logo d'entreprise n'est configuré (Administration)")
            value = f"logo:{logo_sha256}"
        else:  # pragma: no cover - the enum is closed
            raise FieldError(f"unsupported element kind {f.kind}")
        resolved.append(
            {
                "field_id": f.id,
                "role": f.role,
                "kind": f.kind.value,
                "label": f.label,
                "page": f.page,
                "x": round(f.x, 6),
                "y": round(f.y, 6),
                "width": round(f.width, 6),
                "height": round(f.height, 6),
                "value": value,
                **({"preview": True} if preview else {}),
            }
        )
    if missing:
        raise FieldError("À renseigner : " + ", ".join(sorted(set(missing))))
    return resolved


def fields_digest(resolved: list[dict[str, Any]]) -> str:
    """Digest covered by the evidence hash: what was stamped, and where."""
    canonical = json.dumps(
        sorted(resolved, key=lambda r: r["field_id"]), sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _fit_single_line(text: str, font: str, box_width: float, box_height: float) -> float:
    size = max(min(box_height * 0.72, 14.0), 6.0)
    while size > 5 and pdfmetrics.stringWidth(text, font, size) > box_width:
        size -= 0.5
    return size


def _draw_field(
    c: canvas.Canvas, item: dict[str, Any], left: float, bottom: float, width: float, height: float,
    logo: bytes | None,
) -> None:
    x = left + item["x"] * width
    box_w = item["width"] * width
    box_h = item["height"] * height
    y = bottom + (1 - item["y"] - item["height"]) * height  # PDF origin is bottom-left
    kind = FieldKind(item["kind"])
    value = str(item["value"])

    if item.get("preview"):
        # Not signed yet: the place where it will be, in a dotted frame.
        c.saveState()
        c.setStrokeColor(HexColor("#7c5cc4"))
        c.setFillColor(HexColor("#f3effb"))
        c.setLineWidth(0.8)
        c.setDash(3, 2)
        c.roundRect(x - 1, y - 1, box_w + 2, box_h + 2, 2, stroke=1, fill=1)
        c.restoreState()

    if kind == FieldKind.LOGO:
        if not logo:
            return
        image = ImageReader(BytesIO(logo))
        c.drawImage(image, x, y, box_w, box_h, preserveAspectRatio=True, anchor="c", mask="auto")
        return

    if kind == FieldKind.SIGNATURE:
        _ensure_font_registered()
        font = _SIGNATURE_FONT_NAME
        size = min(box_h * 0.78, 30.0)
        while size > 7 and pdfmetrics.stringWidth(value, font, size) > box_w:
            size -= 1
        c.setFillColor(_SIGNATURE_INK)
        c.setFont(font, size)
        c.drawString(x + 1, y + (box_h - size) / 2 + size * 0.2, value)
        c.setStrokeColor(HexColor("#98a2b3"))
        c.setLineWidth(0.5)
        c.line(x, y + 1, x + box_w, y + 1)
        return

    c.setFillColor(_INK)
    if kind in INPUT_KINDS and box_h >= 24:
        # A taller box holds several lines of free text.
        size = 10.0
        lines = simpleSplit(value, "Helvetica", size, box_w - 2)
        max_lines = max(int(box_h // (size * 1.25)), 1)
        c.setFont("Helvetica", size)
        top = y + box_h - size
        for index, line in enumerate(lines[:max_lines]):
            c.drawString(x + 1, top - index * size * 1.25, line)
        return
    size = _fit_single_line(value, "Helvetica", box_w - 2, box_h)
    c.setFont("Helvetica", size)
    c.drawString(x + 1, y + (box_h - size) / 2 + size * 0.2, value)


def stamp_fields(original_pdf: bytes, resolved: list[dict[str, Any]], logo: bytes | None) -> bytes:
    """A copy of `original_pdf` with every resolved element drawn in place."""
    if not resolved:
        return original_pdf
    reader = PdfReader(BytesIO(original_pdf))
    writer = PdfWriter()
    for number, source in enumerate(reader.pages, start=1):
        page = writer.add_page(source)
        # Make the page upright first, so the editor's visual coordinates and the
        # drawing coordinates agree whatever the page rotation was.
        if int(page.get("/Rotate", 0) or 0) % 360:
            page.transfer_rotation_to_content()
        here = [r for r in resolved if r["page"] == number]
        if not here:
            continue
        left, bottom, width, height = _visual_box(page)
        buffer = BytesIO()
        overlay = canvas.Canvas(buffer, pagesize=(left + width, bottom + height))
        for item in here:
            _draw_field(overlay, item, left, bottom, width, height, logo)
        overlay.showPage()
        overlay.save()
        page.merge_page(PdfReader(BytesIO(buffer.getvalue())).pages[0])
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def automatic(kind: FieldKind) -> bool:
    return kind in AUTOMATIC_KINDS
