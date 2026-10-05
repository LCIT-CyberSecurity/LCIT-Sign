from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

# Caveat (SIL OFL) — bundled so the signature rendering never depends on a
# font being present on the viewer's machine (spec §53).
_FONT_PATH = Path(__file__).resolve().parent.parent / "assets" / "fonts" / "Caveat-Variable.ttf"
_SIGNATURE_FONT_NAME = "CaveatHandwriting"
_font_registered = False


def _ensure_font_registered() -> None:
    global _font_registered
    if not _font_registered:
        pdfmetrics.registerFont(TTFont(_SIGNATURE_FONT_NAME, str(_FONT_PATH)))
        _font_registered = True


_MARGIN = 56
_PURPLE = HexColor("#65459b")
_INK = HexColor("#101828")
_MUTED = HexColor("#475467")
_FAINT = HexColor("#667085")
_RULE = HexColor("#d5d9e3")


def _wrapped(
    c: canvas.Canvas, text: str, *, font: str, size: float, x: float, y: float, width: float,
    leading: float, color: HexColor,
) -> float:
    """Draw `text` wrapped to `width`; return the y below the last line.
    Nothing is ever cut off, whatever the length of a title or an address."""
    c.setFont(font, size)
    c.setFillColor(color)
    for line in simpleSplit(text, font, size, width) or [""]:
        c.drawString(x, y, line)
        y -= leading
    return y


def render_attestation_page(
    *,
    document_title: str,
    version_label: str,
    display_name: str,
    email: str,
    signed_at: datetime,
    consent_text: str,
    display_id: str,
    original_sha256: str | None = None,
) -> bytes:
    """Render the attestation page (spec §36): who signed what, when, with a
    cursive rendering of the authenticated name.

    It is always a portrait A4 page, whatever the size of the document it is
    appended to: the page has to hold its content, and the original pages are
    left untouched. Long values wrap instead of running off the page. Used both
    as the page appended to the signed PDF and, standalone, as the certificate.
    """
    _ensure_font_registered()
    page_width, page_height = A4
    content_width = page_width - 2 * _MARGIN
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)

    # Header band.
    c.setFillColor(_PURPLE)
    c.rect(0, page_height - 92, page_width, 92, stroke=0, fill=1)
    c.setFillColor(HexColor("#ffffff"))
    c.setFont("Helvetica-Bold", 11)
    c.drawString(_MARGIN, page_height - 38, "LCIT SIGN")
    c.setFont("Helvetica-Bold", 20)
    c.drawString(_MARGIN, page_height - 66, "Attestation de signature")

    y = page_height - 92 - 40
    rows = [
        ("DOCUMENT", f"{document_title} — version {version_label}"),
        ("SIGNATAIRE", f"{display_name}  <{email}>"),
        ("SIGNÉ LE", signed_at.strftime("%d/%m/%Y à %H:%M:%S UTC")),
        ("IDENTIFIANT", display_id),
    ]
    if original_sha256:
        rows.append(("EMPREINTE DU DOCUMENT ORIGINAL (SHA-256)", original_sha256))
    for label, value in rows:
        c.setFont("Helvetica-Bold", 8)
        c.setFillColor(_FAINT)
        c.drawString(_MARGIN, y, label)
        mono = label.startswith("EMPREINTE")
        y = _wrapped(
            c, value, font="Courier" if mono else "Helvetica", size=9 if mono else 12,
            x=_MARGIN, y=y - 16, width=content_width, leading=15 if mono else 17, color=_INK,
        )
        y -= 12

    # Consent, in a box that grows with its text.
    y -= 6
    consent_lines = simpleSplit(consent_text, "Helvetica-Oblique", 10.5, content_width - 32)
    box_height = 26 + 15 * len(consent_lines)
    c.setStrokeColor(_RULE)
    c.setFillColor(HexColor("#f6f4fb"))
    c.roundRect(_MARGIN, y - box_height, content_width, box_height, 8, stroke=1, fill=1)
    c.setFont("Helvetica-Bold", 8)
    c.setFillColor(_PURPLE)
    c.drawString(_MARGIN + 16, y - 18, "ATTESTATION")
    _wrapped(
        c, consent_text, font="Helvetica-Oblique", size=10.5, x=_MARGIN + 16, y=y - 34,
        width=content_width - 32, leading=15, color=_INK,
    )
    y -= box_height + 56

    # Signature: the name shrinks until it fits, so it can never be clipped.
    max_width = min(content_width, 360)
    size = 40.0
    def too_wide(font_size: float) -> bool:
        width = pdfmetrics.stringWidth(display_name, _SIGNATURE_FONT_NAME, font_size)
        return bool(width > max_width)

    while size > 16 and too_wide(size):
        size -= 2
    c.setFont(_SIGNATURE_FONT_NAME, size)
    c.setFillColor(_INK)
    c.drawString(_MARGIN, y, display_name)
    c.setStrokeColor(HexColor("#98a2b3"))
    c.line(_MARGIN, y - 8, _MARGIN + max_width, y - 8)
    c.setFont("Helvetica", 8.5)
    c.setFillColor(_FAINT)
    stamp = signed_at.strftime("%d/%m/%Y à %H:%M UTC")
    c.drawString(_MARGIN, y - 22, f"Signé avec LCIT Sign le {stamp}")

    # Footer.
    c.setStrokeColor(_RULE)
    c.line(_MARGIN, 64, page_width - _MARGIN, 64)
    _wrapped(
        c,
        "Ce rendu visuel ne constitue pas la preuve à lui seul : la preuve est l'empreinte du "
        "document, la preuve de signature et sa signature cryptographique, "
        "vérifiables dans LCIT Sign.",
        font="Helvetica", size=8, x=_MARGIN, y=50, width=content_width, leading=11, color=_FAINT,
    )

    c.showPage()
    c.save()
    return buffer.getvalue()


def append_signature_page(
    original_pdf: bytes,
    *,
    document_title: str,
    version_label: str,
    display_name: str,
    email: str,
    signed_at: datetime,
    consent_text: str,
    display_id: str,
    original_sha256: str | None = None,
) -> bytes:
    """Return the original PDF with one attestation page appended.

    The original pages are never modified (spec §57) — a fresh writer
    copies them as-is and only the new last page is generated content.
    """
    reader = PdfReader(BytesIO(original_pdf))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)

    attestation_bytes = render_attestation_page(
        document_title=document_title,
        version_label=version_label,
        display_name=display_name,
        email=email,
        signed_at=signed_at,
        consent_text=consent_text,
        display_id=display_id,
        original_sha256=original_sha256,
    )
    writer.add_page(PdfReader(BytesIO(attestation_bytes)).pages[0])

    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def render_certificate_pdf(
    *,
    document_title: str,
    version_label: str,
    display_name: str,
    email: str,
    signed_at: datetime,
    consent_text: str,
    display_id: str,
    original_sha256: str | None = None,
) -> bytes:
    return render_attestation_page(
        document_title=document_title,
        version_label=version_label,
        display_name=display_name,
        email=email,
        signed_at=signed_at,
        consent_text=consent_text,
        display_id=display_id,
        original_sha256=original_sha256,
    )
