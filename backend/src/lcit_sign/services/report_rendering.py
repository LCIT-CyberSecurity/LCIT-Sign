from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


@dataclass(frozen=True)
class ReportDocumentRow:
    title: str
    version_label: str
    sha256: str


@dataclass(frozen=True)
class ReportAssignmentRow:
    email: str
    display_name: str
    status: str
    signed_at: datetime | None
    signature_display_id: str | None


def render_report_pdf(
    *,
    report_id: str,
    generated_at: datetime,
    generated_by_name: str,
    campaign_name: str,
    campaign_status: str,
    documents: list[ReportDocumentRow],
    assignments: list[ReportAssignmentRow],
) -> bytes:
    """A sober, paginated PV: metadata, the signed document versions
    (with their hashes), then who signed and who didn't (spec §86)."""
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    margin = 50
    y = height - margin

    def ensure_space(min_y: float = 80) -> None:
        nonlocal y
        if y < min_y:
            c.showPage()
            y = height - margin

    def line(text: str, *, font: str = "Helvetica", size: int = 10, gap: int = 14) -> None:
        nonlocal y
        c.setFont(font, size)
        c.setFillColor(HexColor("#101828"))
        c.drawString(margin, y, text)
        y -= gap
        ensure_space()

    line("Procès-verbal de signature", font="Helvetica-Bold", size=16, gap=24)
    line(f"Identifiant : {report_id}")
    line(f"Généré le : {generated_at.strftime('%d/%m/%Y à %H:%M UTC')}")
    line(f"Par : {generated_by_name}")
    line(f"Campagne : {campaign_name} (statut : {campaign_status})")
    y -= 10

    line("Documents", font="Helvetica-Bold", size=12, gap=18)
    for doc in documents:
        line(f"- {doc.title} (version {doc.version_label}) — SHA-256 : {doc.sha256}", size=8)
    y -= 10

    signed = [a for a in assignments if a.status == "SIGNED"]
    not_signed = [a for a in assignments if a.status != "SIGNED"]

    line(f"Signataires ({len(signed)})", font="Helvetica-Bold", size=12, gap=18)
    for a in signed:
        signed_at = a.signed_at.strftime("%d/%m/%Y %H:%M UTC") if a.signed_at else "?"
        line(
            f"- {a.display_name} <{a.email}> — signé le {signed_at} — "
            f"{a.signature_display_id}",
            size=8,
        )
    y -= 10

    line(f"Non-signataires ({len(not_signed)})", font="Helvetica-Bold", size=12, gap=18)
    for a in not_signed:
        line(f"- {a.display_name} <{a.email}> — statut : {a.status}", size=8)

    c.showPage()
    c.save()
    return buffer.getvalue()


def render_report_csv(
    *,
    report_id: str,
    generated_at: datetime,
    campaign_name: str,
    campaign_status: str,
    assignments: list[ReportAssignmentRow],
) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["report_id", report_id])
    writer.writerow(["generated_at_utc", generated_at.isoformat()])
    writer.writerow(["campaign_name", campaign_name])
    writer.writerow(["campaign_status", campaign_status])
    writer.writerow([])
    writer.writerow(["email", "display_name", "status", "signed_at_utc", "signature_id"])
    for a in assignments:
        writer.writerow(
            [
                a.email,
                a.display_name,
                a.status,
                a.signed_at.isoformat() if a.signed_at else "",
                a.signature_display_id or "",
            ]
        )
    return buffer.getvalue().encode("utf-8")
