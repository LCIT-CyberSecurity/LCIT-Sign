from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from cryptography.exceptions import InvalidSignature
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from lcit_sign.config import Settings
from lcit_sign.deps import get_db, require_roles
from lcit_sign.models.campaign import Campaign, SignatureAssignment
from lcit_sign.models.document import Document, DocumentVersion
from lcit_sign.models.report import Report
from lcit_sign.models.signature import Signature
from lcit_sign.models.signing_key import SigningKey
from lcit_sign.models.user import Role, User
from lcit_sign.services.audit import append_audit_event
from lcit_sign.services.report_rendering import (
    ReportAssignmentRow,
    ReportDocumentRow,
    render_report_csv,
    render_report_pdf,
)
from lcit_sign.services.signing_keys import (
    SigningKeyError,
    derive_private_key,
    get_or_create_active_key,
    load_public_key,
)
from lcit_sign.services.storage import StorageService

REPORTS_BUCKET = "reports"
PDF_SUFFIX = ".pdf"
CSV_SUFFIX = ".csv"

_manage = require_roles(Role.OPERATOR, Role.ADMIN)

# Mounted under /campaigns: create and list a campaign's PVs.
campaign_reports_router = APIRouter(prefix="/campaigns", tags=["reports"])
# Mounted under /reports: operate on one PV by its own id.
router = APIRouter(prefix="/reports", tags=["reports"])


def _report_payload(report: Report) -> dict[str, Any]:
    return {
        "id": str(report.id),
        "display_id": report.display_id,
        "campaign_id": str(report.campaign_id),
        "generated_at": report.generated_at.isoformat(),
        "pdf_sha256": report.pdf_sha256,
        "csv_sha256": report.csv_sha256,
    }


@campaign_reports_router.post("/{campaign_id}/reports", status_code=201)
def create_report(
    request: Request,
    campaign_id: uuid.UUID,
    user: User = Depends(_manage),
    db: DbSession = Depends(get_db),
) -> dict[str, Any]:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, "Campaign not found")

    settings: Settings = request.app.state.settings
    try:
        signing_key = get_or_create_active_key(db, settings.master_key)
    except SigningKeyError as exc:
        raise HTTPException(503, "Signing is not configured") from exc

    document_rows = []
    for campaign_document in campaign.documents:
        version = db.get(DocumentVersion, campaign_document.document_version_id)
        document = db.get(Document, version.document_id) if version else None
        if version is not None and document is not None:
            document_rows.append(
                ReportDocumentRow(
                    title=document.title, version_label=version.version_label, sha256=version.sha256
                )
            )

    assignment_rows = db.execute(
        select(SignatureAssignment, User)
        .join(User, SignatureAssignment.user_id == User.id)
        .where(SignatureAssignment.campaign_id == campaign.id)
    ).all()
    signature_ids = [a.signature_id for a, _ in assignment_rows if a.signature_id is not None]
    signatures_by_id = {}
    if signature_ids:
        signatures = db.execute(select(Signature).where(Signature.id.in_(signature_ids))).scalars()
        signatures_by_id = {s.id: s for s in signatures}

    assignment_report_rows = [
        ReportAssignmentRow(
            email=target_user.email,
            display_name=target_user.display_name,
            status=assignment.status.value,
            signed_at=assignment.signed_at,
            signature_display_id=(
                signatures_by_id[assignment.signature_id].display_id
                if assignment.signature_id in signatures_by_id
                else None
            ),
        )
        for assignment, target_user in assignment_rows
    ]

    report_id = uuid.uuid4()
    generated_at = datetime.now(UTC)
    display_id = f"PV-{report_id.hex[:12].upper()}"

    pdf_bytes = render_report_pdf(
        report_id=display_id,
        generated_at=generated_at,
        generated_by_name=user.display_name,
        campaign_name=campaign.name,
        campaign_status=campaign.status.value,
        documents=document_rows,
        assignments=assignment_report_rows,
    )
    csv_bytes = render_report_csv(
        report_id=display_id,
        generated_at=generated_at,
        campaign_name=campaign.name,
        campaign_status=campaign.status.value,
        assignments=assignment_report_rows,
    )

    pdf_sha256 = StorageService.sha256_hex(pdf_bytes)
    csv_sha256 = StorageService.sha256_hex(csv_bytes)
    private_key = derive_private_key(settings.master_key, signing_key.key_id)
    cryptographic_signature = private_key.sign(bytes.fromhex(pdf_sha256)).hex()

    report = Report(
        id=report_id,
        campaign_id=campaign.id,
        generated_by=user.id,
        pdf_sha256=pdf_sha256,
        csv_sha256=csv_sha256,
        signing_key_id=signing_key.key_id,
        cryptographic_signature=cryptographic_signature,
    )
    db.add(report)
    db.flush()

    storage: StorageService = request.app.state.storage
    storage.save(REPORTS_BUCKET, report.id, PDF_SUFFIX, pdf_bytes)
    storage.save(REPORTS_BUCKET, report.id, CSV_SUFFIX, csv_bytes)

    append_audit_event(
        db, action="REPORT_CREATED", actor_id=user.id,
        target_type="report", target_id=str(report.id), campaign_id=campaign.id,
    )
    db.commit()
    return _report_payload(report)


@campaign_reports_router.get("/{campaign_id}/reports")
def list_campaign_reports(
    campaign_id: uuid.UUID, user: User = Depends(_manage), db: DbSession = Depends(get_db)
) -> list[dict[str, Any]]:
    reports = db.execute(
        select(Report).where(Report.campaign_id == campaign_id).order_by(Report.generated_at.desc())
    ).scalars()
    return [_report_payload(r) for r in reports]


def _get_report_or_404(db: DbSession, report_id: uuid.UUID) -> Report:
    report = db.get(Report, report_id)
    if report is None:
        raise HTTPException(404, "Report not found")
    return report


@router.get("/{report_id}/pdf")
def download_report_pdf(
    request: Request,
    report_id: uuid.UUID,
    user: User = Depends(_manage),
    db: DbSession = Depends(get_db),
) -> Response:
    report = _get_report_or_404(db, report_id)
    storage: StorageService = request.app.state.storage
    data = storage.read(REPORTS_BUCKET, report.id, PDF_SUFFIX)
    append_audit_event(
        db, action="REPORT_DOWNLOADED", actor_id=user.id,
        target_type="report", target_id=str(report.id), campaign_id=report.campaign_id,
    )
    db.commit()
    return Response(
        content=data, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{report.display_id}.pdf"'},
    )


@router.get("/{report_id}/csv")
def download_report_csv(
    request: Request,
    report_id: uuid.UUID,
    user: User = Depends(_manage),
    db: DbSession = Depends(get_db),
) -> Response:
    report = _get_report_or_404(db, report_id)
    storage: StorageService = request.app.state.storage
    data = storage.read(REPORTS_BUCKET, report.id, CSV_SUFFIX)
    append_audit_event(
        db, action="REPORT_DOWNLOADED", actor_id=user.id,
        target_type="report", target_id=str(report.id), campaign_id=report.campaign_id,
    )
    db.commit()
    return Response(
        content=data, media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{report.display_id}.csv"'},
    )


@router.get("/{report_id}/verify")
def verify_report(
    request: Request,
    report_id: uuid.UUID,
    user: User = Depends(_manage),
    db: DbSession = Depends(get_db),
) -> dict[str, Any]:
    report = _get_report_or_404(db, report_id)
    storage: StorageService = request.app.state.storage

    checks: dict[str, bool] = {}
    try:
        data = storage.read(REPORTS_BUCKET, report.id, PDF_SUFFIX)
        checks["pdf_hash"] = StorageService.sha256_hex(data) == report.pdf_sha256
    except OSError:
        checks["pdf_hash"] = False

    signing_key = db.execute(
        select(SigningKey).where(SigningKey.key_id == report.signing_key_id)
    ).scalar_one_or_none()
    if signing_key is None:
        checks["cryptographic_signature"] = False
    else:
        try:
            load_public_key(signing_key.public_key_hex).verify(
                bytes.fromhex(report.cryptographic_signature), bytes.fromhex(report.pdf_sha256)
            )
            checks["cryptographic_signature"] = True
        except InvalidSignature:
            checks["cryptographic_signature"] = False

    return {"valid": all(checks.values()), "checks": checks}
