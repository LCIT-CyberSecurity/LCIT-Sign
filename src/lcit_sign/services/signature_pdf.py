from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
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


def render_attestation_page(
    *,
    page_width: float,
    page_height: float,
    document_title: str,
    version_label: str,
    display_name: str,
    email: str,
    signed_at: datetime,
    consent_text: str,
    display_id: str,
) -> bytes:
    """Render a one-page attestation: sober metadata plus a cursive
    rendering of the signer's authenticated display name (spec §52, §58).
    Used both as the page appended to the signed PDF and, standalone, as
    the human-readable certificate PDF (spec §59).
    """
    _ensure_font_registered()
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=(page_width, page_height))
    margin = 56
    y = page_height - margin

    c.setFillColor(HexColor("#101828"))
    c.setFont("Helvetica-Bold", 16)
    c.drawString(margin, y, "Attestation de signature électronique")
    y -= 30

    c.setFont("Helvetica", 10)
    c.setFillColor(HexColor("#475467"))
    for line in (
        f"Document : {document_title} (version {version_label})",
        f"Signé par : {display_name} <{email}>",
        f"Date : {signed_at.strftime('%d/%m/%Y à %H:%M UTC')}",
        f"Identifiant : {display_id}",
    ):
        c.drawString(margin, y, line)
        y -= 16

    y -= 20
    c.setFont("Helvetica-Oblique", 9)
    c.drawString(margin, y, consent_text)
    y -= 70

    c.setStrokeColor(HexColor("#c7ccd6"))
    c.line(margin, y, margin + 280, y)
    c.setFont(_SIGNATURE_FONT_NAME, 34)
    c.setFillColor(HexColor("#101828"))
    c.drawString(margin, y + 8, display_name)

    y -= 18
    c.setFont("Helvetica", 8)
    c.setFillColor(HexColor("#5d6778"))
    c.drawString(margin, y, "Signé avec LCIT Sign — ce rendu ne constitue pas la preuve à lui seul")

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
) -> bytes:
    """Return the original PDF with one attestation page appended.

    The original pages are never modified (spec §57) — a fresh writer
    copies them as-is and only the new last page is generated content.
    """
    reader = PdfReader(BytesIO(original_pdf))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)

    last_page = reader.pages[-1]
    attestation_bytes = render_attestation_page(
        page_width=float(last_page.mediabox.width),
        page_height=float(last_page.mediabox.height),
        document_title=document_title,
        version_label=version_label,
        display_name=display_name,
        email=email,
        signed_at=signed_at,
        consent_text=consent_text,
        display_id=display_id,
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
) -> bytes:
    return render_attestation_page(
        page_width=A4[0],
        page_height=A4[1],
        document_title=document_title,
        version_label=version_label,
        display_name=display_name,
        email=email,
        signed_at=signed_at,
        consent_text=consent_text,
        display_id=display_id,
    )
