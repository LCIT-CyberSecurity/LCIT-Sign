from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session as DbSession

from lcit_sign.config import Settings
from lcit_sign.deps import get_current_user, get_db, require_roles, user_roles
from lcit_sign.models.campaign import (
    AssignmentStatus,
    Campaign,
    CampaignDocument,
    CampaignStatus,
    SignatureAssignment,
)
from lcit_sign.models.document import (
    Document,
    DocumentField,
    DocumentVersion,
    DocumentVersionStatus,
    FieldKind,
)
from lcit_sign.models.signature import Signature
from lcit_sign.models.user import Role, User
from lcit_sign.services import branding
from lcit_sign.services.audit import append_audit_event
from lcit_sign.services.document_validation import DocumentValidationError, validate_pdf_upload
from lcit_sign.services.storage import StorageService

router = APIRouter(prefix="/documents", tags=["documents"])

DOCUMENTS_BUCKET = "documents"
PDF_SUFFIX = ".pdf"

# Managing documents (upload/publish/list) stays OPERATOR/ADMIN-only.
# Viewing a version's content is wider: also anyone with a
# SignatureAssignment for it (see get_version_content) — a signer must be
# able to read what they are being asked to sign.
_manage = require_roles(Role.OPERATOR, Role.ADMIN)


def delete_blockers(db: DbSession, version_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[str]]:
    """Why each version cannot be erased, in words an operator can act on.

    A version that has been signed, or that a campaign refers to, is part of
    the evidence trail: signatures name the exact version and its hash, and
    reports list it. Erasing it would orphan that proof, so it can only be
    archived. A version nobody has used can be removed for good.
    """
    blockers: dict[uuid.UUID, list[str]] = {vid: [] for vid in version_ids}
    if not version_ids:
        return blockers
    signed = dict(
        db.execute(
            select(Signature.document_version_id, func.count())
            .where(Signature.document_version_id.in_(version_ids))
            .group_by(Signature.document_version_id)
        ).all()
    )
    for vid, count in signed.items():
        blockers[vid].append(f"{count} signature(s) enregistrée(s)")
    for vid, name in db.execute(
        select(CampaignDocument.document_version_id, Campaign.name)
        .join(Campaign, Campaign.id == CampaignDocument.campaign_id)
        .where(CampaignDocument.document_version_id.in_(version_ids))
        .order_by(Campaign.name)
    ):
        blockers[vid].append(f"utilisé par la campagne « {name} »")
    return blockers


def _version_payload(
    version: DocumentVersion, blockers: dict[uuid.UUID, list[str]] | None = None
) -> dict[str, Any]:
    reasons = (blockers or {}).get(version.id)
    return {
        "can_delete": None if blockers is None else not reasons,
        "delete_blockers": reasons or [],
        "id": str(version.id),
        "document_id": str(version.document_id),
        "version_label": version.version_label,
        "original_filename": version.original_filename,
        "file_size": version.file_size,
        "mime_type": version.mime_type,
        "sha256": version.sha256,
        "status": version.status.value,
        "created_at": version.created_at.isoformat(),
        "published_at": version.published_at.isoformat() if version.published_at else None,
    }


def _document_payload(
    document: Document, blockers: dict[uuid.UUID, list[str]] | None = None
) -> dict[str, Any]:
    return {
        "id": str(document.id),
        "title": document.title,
        "description": document.description,
        "category": document.category,
        "created_at": document.created_at.isoformat(),
        "versions": [_version_payload(v, blockers) for v in document.versions],
        "can_delete": None
        if blockers is None
        else all(not blockers.get(v.id) for v in document.versions),
    }


async def _validated_upload(request: Request, file: UploadFile) -> tuple[bytes, str]:
    settings: Settings = request.app.state.settings
    data = await file.read()
    try:
        validate_pdf_upload(
            file.filename or "",
            file.content_type or "",
            data,
            max_bytes=settings.max_upload_size_mb * 1024 * 1024,
        )
    except DocumentValidationError as exc:
        raise HTTPException(400, str(exc)) from None
    return data, StorageService.sha256_hex(data)


@router.post("", status_code=201)
async def create_document(
    request: Request,
    title: str = Form(...),
    version_label: str = Form("1.0"),
    description: str = Form("", max_length=2000),
    category: str = Form("", max_length=100),
    file: UploadFile = File(...),
    user: User = Depends(_manage),
    db: DbSession = Depends(get_db),
) -> dict[str, Any]:
    data, sha256 = await _validated_upload(request, file)
    storage: StorageService = request.app.state.storage

    document = Document(
        title=title, description=description, category=category.strip(), created_by=user.id
    )
    db.add(document)
    db.flush()

    version = DocumentVersion(
        document_id=document.id,
        version_label=version_label,
        original_filename=file.filename or "document.pdf",
        file_size=len(data),
        mime_type="application/pdf",
        sha256=sha256,
        created_by=user.id,
    )
    db.add(version)
    db.flush()

    storage.save(DOCUMENTS_BUCKET, version.id, PDF_SUFFIX, data)

    append_audit_event(
        db, action="DOCUMENT_CREATED", actor_id=user.id,
        target_type="document", target_id=str(document.id), document_id=document.id,
    )
    append_audit_event(
        db, action="DOCUMENT_VERSION_CREATED", actor_id=user.id,
        target_type="document_version", target_id=str(version.id), document_id=document.id,
    )
    db.commit()
    return _document_payload(document, delete_blockers(db, [v.id for v in document.versions]))


@router.post("/{document_id}/versions", status_code=201)
async def create_document_version(
    request: Request,
    document_id: uuid.UUID,
    version_label: str = Form(...),
    file: UploadFile = File(...),
    user: User = Depends(_manage),
    db: DbSession = Depends(get_db),
) -> dict[str, Any]:
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(404, "Document not found")

    data, sha256 = await _validated_upload(request, file)
    storage: StorageService = request.app.state.storage

    version = DocumentVersion(
        document_id=document.id,
        version_label=version_label,
        original_filename=file.filename or "document.pdf",
        file_size=len(data),
        mime_type="application/pdf",
        sha256=sha256,
        created_by=user.id,
    )
    db.add(version)
    db.flush()

    storage.save(DOCUMENTS_BUCKET, version.id, PDF_SUFFIX, data)

    append_audit_event(
        db, action="DOCUMENT_VERSION_CREATED", actor_id=user.id,
        target_type="document_version", target_id=str(version.id), document_id=document.id,
    )
    db.commit()
    return _version_payload(version)


def check_publishable(db: DbSession, storage: StorageService, version: DocumentVersion) -> None:
    """What would refuse the publication of a draft. Raises HTTPException."""
    if version.status != DocumentVersionStatus.DRAFT:
        raise HTTPException(409, "Only a draft version can be published")

    placed = list(
        db.execute(
            select(DocumentField.kind).where(DocumentField.document_version_id == version.id)
        ).scalars()
    )
    if FieldKind.LOGO in placed and branding.read_logo(storage) is None:
        raise HTTPException(
            409,
            "Ce document comporte un logo d'entreprise, mais aucun logo n'est configuré "
            "(Administration → Logo).",
        )


def publish_draft(
    db: DbSession, storage: StorageService, user: User, version: DocumentVersion
) -> None:
    """Freeze a draft version (file and prepared elements) as the published one.
    Used by the Publish button and by a campaign launch, which publishes the
    drafts it was prepared with. Does not commit. Raises HTTPException."""
    check_publishable(db, storage, version)

    currently_published = db.execute(
        select(DocumentVersion).where(
            DocumentVersion.document_id == version.document_id,
            DocumentVersion.status == DocumentVersionStatus.PUBLISHED,
        )
    ).scalar_one_or_none()
    if currently_published is not None:
        currently_published.status = DocumentVersionStatus.SUPERSEDED

    version.status = DocumentVersionStatus.PUBLISHED
    version.published_at = datetime.now(UTC)

    append_audit_event(
        db, action="DOCUMENT_PUBLISHED", actor_id=user.id,
        target_type="document_version", target_id=str(version.id), document_id=version.document_id,
    )


@router.post("/versions/{version_id}/publish")
def publish_version(
    request: Request,
    version_id: uuid.UUID,
    user: User = Depends(_manage),
    db: DbSession = Depends(get_db),
) -> dict[str, Any]:
    version = db.get(DocumentVersion, version_id)
    if version is None:
        raise HTTPException(404, "Document version not found")
    publish_draft(db, request.app.state.storage, user, version)
    db.commit()
    return _version_payload(version)


@router.post("/versions/{version_id}/archive")
def archive_version(
    version_id: uuid.UUID, user: User = Depends(_manage), db: DbSession = Depends(get_db)
) -> dict[str, Any]:
    """Retire a version from use (spec §20 ARCHIVED). Signatures already made
    on it stay valid and verifiable; what is refused is archiving a version an
    active campaign is still asking people to sign."""
    version = db.get(DocumentVersion, version_id)
    if version is None:
        raise HTTPException(404, "Document version not found")
    if version.status == DocumentVersionStatus.ARCHIVED:
        raise HTTPException(409, "Version is already archived")

    in_active_campaign = db.execute(
        select(CampaignDocument.campaign_id)
        .join(Campaign, Campaign.id == CampaignDocument.campaign_id)
        .where(
            CampaignDocument.document_version_id == version.id,
            Campaign.status == CampaignStatus.ACTIVE,
        )
        .limit(1)
    ).first()
    if in_active_campaign is not None:
        raise HTTPException(409, "An active campaign still uses this version")

    version.status = DocumentVersionStatus.ARCHIVED
    append_audit_event(
        db, action="DOCUMENT_ARCHIVED", actor_id=user.id,
        target_type="document_version", target_id=str(version.id), document_id=version.document_id,
    )
    db.commit()
    return _version_payload(version)


def _erase_version(db: DbSession, storage: StorageService, version: DocumentVersion) -> None:
    db.execute(delete(DocumentField).where(DocumentField.document_version_id == version.id))
    db.delete(version)
    storage.delete(DOCUMENTS_BUCKET, version.id, PDF_SUFFIX)


@router.delete("/versions/{version_id}")
def delete_version(
    request: Request,
    version_id: uuid.UUID,
    user: User = Depends(_manage),
    db: DbSession = Depends(get_db),
) -> dict[str, Any]:
    """Erase a version nobody has signed or used (draft, or a stray upload).
    Anything that is part of the evidence trail is refused with the reason and
    must be archived instead."""
    version = db.get(DocumentVersion, version_id)
    if version is None:
        raise HTTPException(404, "Document version not found")
    reasons = delete_blockers(db, [version.id])[version.id]
    if reasons:
        raise HTTPException(
            409,
            "Cette version fait partie de la preuve et ne peut pas être supprimée ("
            + " ; ".join(reasons)
            + "). Archivez-la à la place.",
        )
    document = db.get(Document, version.document_id)
    storage: StorageService = request.app.state.storage
    metadata = {
        "title": document.title if document else "",
        "version": version.version_label,
        "sha256": version.sha256,
        "status": version.status.value,
    }
    document_id = version.document_id
    _erase_version(db, storage, version)
    db.flush()
    # The last version going takes its (now empty) document with it.
    remaining = db.execute(
        select(func.count()).select_from(DocumentVersion).where(
            DocumentVersion.document_id == document_id
        )
    ).scalar_one()
    if remaining == 0 and document is not None:
        db.delete(document)
    append_audit_event(
        db, action="DOCUMENT_DELETED", actor_id=user.id,
        target_type="document_version", target_id=str(version_id), document_id=None,
        metadata=metadata,
    )
    db.commit()
    return {"deleted": str(version_id), "document_removed": remaining == 0}


@router.delete("/{document_id}")
def delete_document(
    request: Request,
    document_id: uuid.UUID,
    user: User = Depends(_manage),
    db: DbSession = Depends(get_db),
) -> dict[str, Any]:
    """Erase a whole document — only if none of its versions is signed or used."""
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(404, "Document not found")
    blockers = delete_blockers(db, [v.id for v in document.versions])
    problems = [
        f"v{v.version_label} : " + " ; ".join(blockers[v.id])
        for v in document.versions
        if blockers[v.id]
    ]
    if problems:
        raise HTTPException(
            409,
            "Ce document contient des versions qui font partie de la preuve ("
            + " | ".join(problems)
            + "). Archivez les versions concernées à la place.",
        )
    storage: StorageService = request.app.state.storage
    versions = list(document.versions)
    metadata = {"title": document.title, "versions": [v.version_label for v in versions]}
    for version in versions:
        _erase_version(db, storage, version)
    db.flush()
    db.delete(document)
    append_audit_event(
        db, action="DOCUMENT_DELETED", actor_id=user.id,
        target_type="document", target_id=str(document_id), metadata=metadata,
    )
    db.commit()
    return {"deleted": str(document_id), "versions_removed": len(versions)}


@router.get("")
def list_documents(
    user: User = Depends(_manage), db: DbSession = Depends(get_db)
) -> list[dict[str, Any]]:
    documents = list(
        db.execute(select(Document).order_by(Document.created_at.desc())).scalars()
    )
    blockers = delete_blockers(db, [v.id for doc in documents for v in doc.versions])
    return [_document_payload(doc, blockers) for doc in documents]


@router.get("/{document_id}")
def get_document(
    document_id: uuid.UUID, user: User = Depends(_manage), db: DbSession = Depends(get_db)
) -> dict[str, Any]:
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(404, "Document not found")
    return _document_payload(document, delete_blockers(db, [v.id for v in document.versions]))


@router.get("/versions/{version_id}/content")
def get_version_content(
    request: Request,
    version_id: uuid.UUID,
    download: bool = False,
    user: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
) -> Response:
    version = db.get(DocumentVersion, version_id)
    if version is None:
        raise HTTPException(404, "Document version not found")

    assignment = db.execute(
        select(SignatureAssignment).where(
            SignatureAssignment.document_version_id == version.id,
            SignatureAssignment.user_id == user.id,
        )
    ).scalar_one_or_none()
    if assignment is None and not (user_roles(db, user) & {Role.OPERATOR, Role.ADMIN}):
        raise HTTPException(403, "Not authorized to view this document version")

    storage: StorageService = request.app.state.storage
    if not storage.exists(DOCUMENTS_BUCKET, version.id, PDF_SUFFIX):
        raise HTTPException(404, "Document content missing from storage")
    data = storage.read(DOCUMENTS_BUCKET, version.id, PDF_SUFFIX)

    if assignment is not None and assignment.status == AssignmentStatus.PENDING:
        assignment.status = AssignmentStatus.VIEWED
        assignment.first_viewed_at = datetime.now(UTC)

    append_audit_event(
        db, action="DOCUMENT_VIEWED", actor_id=user.id,
        target_type="document_version", target_id=str(version.id), document_id=version.document_id,
    )
    db.commit()

    disposition = "attachment" if download else "inline"
    filename = version.original_filename.replace('"', "")
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
    )
