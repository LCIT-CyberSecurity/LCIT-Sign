from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from lcit_sign.config import Settings
from lcit_sign.deps import get_db, require_roles
from lcit_sign.models.document import Document, DocumentVersion, DocumentVersionStatus
from lcit_sign.models.user import Role, User
from lcit_sign.services.audit import append_audit_event
from lcit_sign.services.document_validation import DocumentValidationError, validate_pdf_upload
from lcit_sign.services.storage import StorageService

router = APIRouter(prefix="/documents", tags=["documents"])

DOCUMENTS_BUCKET = "documents"
PDF_SUFFIX = ".pdf"

# Managing documents is an OPERATOR/ADMIN affair for the whole of Phase 2.
# Signer access to a specific PUBLISHED version's content is granted in
# Phase 4 once SignatureAssignment exists to check "is this assigned to me" —
# wiring it up before that model exists would be security theatre, not RBAC.
_manage = require_roles(Role.OPERATOR, Role.ADMIN)


def _version_payload(version: DocumentVersion) -> dict[str, Any]:
    return {
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


def _document_payload(document: Document) -> dict[str, Any]:
    return {
        "id": str(document.id),
        "title": document.title,
        "created_at": document.created_at.isoformat(),
        "versions": [_version_payload(v) for v in document.versions],
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
    file: UploadFile = File(...),
    user: User = Depends(_manage),
    db: DbSession = Depends(get_db),
) -> dict[str, Any]:
    data, sha256 = await _validated_upload(request, file)
    storage: StorageService = request.app.state.storage

    document = Document(title=title, created_by=user.id)
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
    return _document_payload(document)


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


@router.post("/versions/{version_id}/publish")
def publish_version(
    version_id: uuid.UUID, user: User = Depends(_manage), db: DbSession = Depends(get_db)
) -> dict[str, Any]:
    version = db.get(DocumentVersion, version_id)
    if version is None:
        raise HTTPException(404, "Document version not found")
    if version.status != DocumentVersionStatus.DRAFT:
        raise HTTPException(409, "Only a draft version can be published")

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
    db.commit()
    return _version_payload(version)


@router.get("")
def list_documents(
    user: User = Depends(_manage), db: DbSession = Depends(get_db)
) -> list[dict[str, Any]]:
    documents = db.execute(select(Document).order_by(Document.created_at.desc())).scalars()
    return [_document_payload(doc) for doc in documents]


@router.get("/{document_id}")
def get_document(
    document_id: uuid.UUID, user: User = Depends(_manage), db: DbSession = Depends(get_db)
) -> dict[str, Any]:
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(404, "Document not found")
    return _document_payload(document)


@router.get("/versions/{version_id}/content")
def get_version_content(
    request: Request,
    version_id: uuid.UUID,
    download: bool = False,
    user: User = Depends(_manage),
    db: DbSession = Depends(get_db),
) -> Response:
    version = db.get(DocumentVersion, version_id)
    if version is None:
        raise HTTPException(404, "Document version not found")

    storage: StorageService = request.app.state.storage
    if not storage.exists(DOCUMENTS_BUCKET, version.id, PDF_SUFFIX):
        raise HTTPException(404, "Document content missing from storage")
    data = storage.read(DOCUMENTS_BUCKET, version.id, PDF_SUFFIX)

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
