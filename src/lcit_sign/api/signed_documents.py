"""The signed documents of one or several campaigns, in one place: who signed what, who still
has to, the PDFs themselves, and a ZIP of them all. For operators and administrators."""

from __future__ import annotations

import csv
import io
import re
import uuid
import zipfile
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from lcit_sign.deps import get_db, require_roles
from lcit_sign.models.campaign import (
    AssignmentStatus,
    Campaign,
    CampaignStatus,
    SignatureAssignment,
)
from lcit_sign.models.document import Document, DocumentVersion
from lcit_sign.models.signature import Signature
from lcit_sign.models.user import Role, User
from lcit_sign.services.audit import append_audit_event
from lcit_sign.services.storage import StorageService

router = APIRouter(prefix="/signed", tags=["signed"])

_manage = require_roles(Role.OPERATOR, Role.ADMIN)

SIGNED_BUCKET = "signed"
PDF_SUFFIX = ".pdf"
MAX_ROWS = 2000
# A ZIP is built in memory: bounded, with a message that says how to narrow it down.
MAX_ZIP_FILES = 500
MAX_ZIP_BYTES = 200 * 1024 * 1024
OUTSTANDING = (AssignmentStatus.WAITING, AssignmentStatus.PENDING, AssignmentStatus.VIEWED)


def _csv_safe(value: object) -> str:
    """A cell that a spreadsheet would run as a formula is turned into plain text."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def _file_part(value: str, limit: int = 80) -> str:
    """A piece of a file name: no path separators or control characters."""
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", value)
    return re.sub(r"\s+", " ", cleaned).strip()[:limit] or "sans-nom"


def _matches(query: str, *parts: str) -> bool:
    needle = query.strip().lower()
    return not needle or needle in " ".join(parts).lower()


def _signed_rows(db: DbSession, campaign_ids: list[uuid.UUID], query: str) -> list[dict[str, Any]]:
    stmt = (
        select(Signature, Document, DocumentVersion, Campaign)
        .join(Document, Document.id == Signature.document_id)
        .join(DocumentVersion, DocumentVersion.id == Signature.document_version_id)
        .outerjoin(Campaign, Campaign.id == Signature.campaign_id)
        .order_by(Signature.signed_at_utc.desc())
    )
    if campaign_ids:
        stmt = stmt.where(Signature.campaign_id.in_(campaign_ids))
    rows = []
    for signature, document, version, campaign in db.execute(stmt):
        if not _matches(
            query,
            signature.display_name_snapshot,
            signature.email_snapshot,
            document.title,
            campaign.name if campaign else "",
        ):
            continue
        rows.append(
            {
                "id": str(signature.id),
                "display_id": signature.display_id,
                "signed_at": signature.signed_at_utc.isoformat(),
                "document_title": document.title,
                "version_label": version.version_label,
                "campaign_id": str(campaign.id) if campaign else None,
                "campaign_name": campaign.name if campaign else None,
                "signer_name": signature.display_name_snapshot,
                "signer_email": signature.email_snapshot,
                "signed_file_sha256": signature.signed_file_sha256,
            }
        )
        if len(rows) >= MAX_ROWS:
            break
    return rows


def _outstanding_rows(
    db: DbSession, campaign_ids: list[uuid.UUID], query: str
) -> list[dict[str, Any]]:
    stmt = (
        select(SignatureAssignment, User, Document, DocumentVersion, Campaign)
        .join(User, User.id == SignatureAssignment.user_id)
        .join(DocumentVersion, DocumentVersion.id == SignatureAssignment.document_version_id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .join(Campaign, Campaign.id == SignatureAssignment.campaign_id)
        .where(
            SignatureAssignment.status.in_(OUTSTANDING),
            Campaign.status == CampaignStatus.ACTIVE,
        )
        .order_by(Campaign.name, User.display_name)
    )
    if campaign_ids:
        stmt = stmt.where(SignatureAssignment.campaign_id.in_(campaign_ids))
    rows = []
    for assignment, person, document, version, campaign in db.execute(stmt):
        if not _matches(query, person.display_name, person.email, document.title, campaign.name):
            continue
        rows.append(
            {
                "id": str(assignment.id),
                "status": assignment.status.value,
                "document_title": document.title,
                "version_label": version.version_label,
                "campaign_id": str(campaign.id),
                "campaign_name": campaign.name,
                "signer_name": person.display_name,
                "signer_email": person.email,
                "deadline": assignment.deadline.isoformat() if assignment.deadline else None,
            }
        )
        if len(rows) >= MAX_ROWS:
            break
    return rows


@router.get("/documents")
def signed_documents(
    campaign_ids: list[uuid.UUID] = Query(default=[]),
    q: str = "",
    user: User = Depends(_manage),
    db: DbSession = Depends(get_db),
) -> dict[str, Any]:
    """What was signed and what is still to sign, for the campaigns chosen (all when none)."""
    signed = _signed_rows(db, campaign_ids, q)
    outstanding = _outstanding_rows(db, campaign_ids, q)
    campaigns = db.execute(
        select(Campaign)
        .where(Campaign.status != CampaignStatus.DRAFT)
        .order_by(Campaign.created_at.desc())
    ).scalars()
    return {
        "campaigns": [
            {"id": str(c.id), "name": c.name, "status": c.status.value} for c in campaigns
        ],
        "signed": signed,
        "outstanding": outstanding,
        "totals": {
            "signed": len(signed),
            "outstanding": len(outstanding),
            "waiting": sum(1 for r in outstanding if r["status"] == "WAITING"),
        },
    }


@router.get("/export.zip")
def export_signed_documents(
    request: Request,
    campaign_ids: list[uuid.UUID] = Query(default=[]),
    q: str = "",
    user: User = Depends(_manage),
    db: DbSession = Depends(get_db),
) -> Response:
    """A ZIP of the signed PDFs (one folder per campaign) with an index of what was signed and
    what is still to sign."""
    signed = _signed_rows(db, campaign_ids, q)
    if not signed:
        raise HTTPException(404, "Aucun document signé pour cette sélection.")
    if len(signed) > MAX_ZIP_FILES:
        raise HTTPException(
            413,
            f"Trop de documents pour un seul export ({len(signed)}, {MAX_ZIP_FILES} au maximum) : "
            "choisissez moins de campagnes ou affinez la recherche.",
        )
    storage: StorageService = request.app.state.storage
    buffer = io.BytesIO()
    total = 0
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        used: set[str] = set()
        for row in signed:
            try:
                data = storage.read(SIGNED_BUCKET, uuid.UUID(row["id"]), PDF_SUFFIX)
            except OSError:
                continue  # a file missing from the storage is reported by the integrity check
            total += len(data)
            if total > MAX_ZIP_BYTES:
                raise HTTPException(
                    413,
                    "L'export dépasse la taille maximale : choisissez moins de campagnes.",
                )
            name = (
                f"{_file_part(row['campaign_name'] or 'Sans campagne', 60)}/"
                f"{_file_part(row['document_title'])} - {_file_part(row['signer_name'], 50)}"
                f" - {row['display_id']}.pdf"
            )
            while name in used:
                name = name.replace(".pdf", " (2).pdf")
            used.add(name)
            archive.writestr(name, data)

        index = io.StringIO()
        writer = csv.writer(index)
        writer.writerow(
            [
                "Signature",
                "Campagne",
                "Document",
                "Version",
                "Signataire",
                "E-mail",
                "Signé le (UTC)",
                "SHA-256 du PDF signé",
            ]
        )
        for row in signed:
            writer.writerow(
                [
                    _csv_safe(v)
                    for v in (
                        row["display_id"],
                        row["campaign_name"] or "",
                        row["document_title"],
                        row["version_label"],
                        row["signer_name"],
                        row["signer_email"],
                        row["signed_at"],
                        row["signed_file_sha256"],
                    )
                ]
            )
        archive.writestr("index-signes.csv", index.getvalue().encode("utf-8-sig"))

        remaining = _outstanding_rows(db, campaign_ids, q)
        pending = io.StringIO()
        writer = csv.writer(pending)
        writer.writerow(
            ["Campagne", "Document", "Version", "Signataire", "E-mail", "Statut", "Échéance"]
        )
        for row in remaining:
            writer.writerow(
                [
                    _csv_safe(v)
                    for v in (
                        row["campaign_name"],
                        row["document_title"],
                        row["version_label"],
                        row["signer_name"],
                        row["signer_email"],
                        row["status"],
                        row["deadline"] or "",
                    )
                ]
            )
        archive.writestr("reste-a-signer.csv", pending.getvalue().encode("utf-8-sig"))

    append_audit_event(
        db,
        action="SIGNED_DOCUMENTS_EXPORTED",
        actor_id=user.id,
        metadata={"documents": len(signed), "campaigns": [str(c) for c in campaign_ids]},
    )
    db.commit()
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="documents-signes.zip"'},
    )
