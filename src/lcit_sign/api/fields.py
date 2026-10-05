from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from lcit_sign.deps import get_current_user, get_db, require_roles
from lcit_sign.models.document import (
    DocumentField,
    DocumentVersion,
    DocumentVersionStatus,
    FieldKind,
)
from lcit_sign.models.user import Role, User
from lcit_sign.services import branding
from lcit_sign.services.audit import append_audit_event
from lcit_sign.services.field_stamping import (
    FieldError,
    PreparedField,
    automatic,
    page_sizes,
    validate_layout,
)
from lcit_sign.services.storage import StorageService

router = APIRouter(tags=["document-fields"])

_manage = require_roles(Role.OPERATOR, Role.ADMIN)
_DOCUMENTS = "documents"


class FieldIn(BaseModel):
    id: str | None = None
    page: int
    x: float
    y: float
    width: float
    height: float
    kind: FieldKind
    label: str = Field(default="", max_length=120)
    required: bool = True
    role: int = 1
    group_key: str | None = Field(default=None, max_length=60)


class FieldsIn(BaseModel):
    fields: list[FieldIn]


def field_payload(row: DocumentField) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "page": row.page,
        "x": row.x,
        "y": row.y,
        "width": row.width,
        "height": row.height,
        "kind": row.kind.value,
        "label": row.label,
        "required": row.required,
        "role": row.role,
        "group_key": row.group_key,
        "automatic": automatic(row.kind),
    }


def load_fields(db: DbSession, version_id: uuid.UUID) -> list[DocumentField]:
    return list(
        db.execute(
            select(DocumentField)
            .where(DocumentField.document_version_id == version_id)
            .order_by(DocumentField.position, DocumentField.id)
        ).scalars()
    )


def to_prepared(rows: list[DocumentField]) -> list[PreparedField]:
    return [
        PreparedField(
            id=str(r.id), page=r.page, x=r.x, y=r.y, width=r.width, height=r.height,
            kind=r.kind, label=r.label, required=r.required, role=r.role, group_key=r.group_key,
        )
        for r in rows
    ]


def _version_or_404(db: DbSession, version_id: uuid.UUID) -> DocumentVersion:
    version = db.get(DocumentVersion, version_id)
    if version is None:
        raise HTTPException(404, "Document version not found")
    return version


@router.get("/documents/versions/{version_id}/pages")
def get_pages(
    request: Request,
    version_id: uuid.UUID,
    user: User = Depends(_manage),
    db: DbSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Page sizes as a viewer shows them, so the editor draws proportions right."""
    version = _version_or_404(db, version_id)
    storage: StorageService = request.app.state.storage
    pdf = storage.read(_DOCUMENTS, version.id, ".pdf")
    return [
        {"number": n, "width": s.width, "height": s.height}
        for n, s in enumerate(page_sizes(pdf), start=1)
    ]


@router.get("/documents/versions/{version_id}/fields")
def get_fields(
    version_id: uuid.UUID, user: User = Depends(_manage), db: DbSession = Depends(get_db)
) -> dict[str, Any]:
    version = _version_or_404(db, version_id)
    return {
        "editable": version.status == DocumentVersionStatus.DRAFT,
        "fields": [field_payload(r) for r in load_fields(db, version.id)],
    }


@router.put("/documents/versions/{version_id}/fields")
def put_fields(
    request: Request,
    version_id: uuid.UUID,
    body: FieldsIn,
    user: User = Depends(_manage),
    db: DbSession = Depends(get_db),
) -> dict[str, Any]:
    """Replace the prepared elements of a draft. Once a version is published the
    set is frozen with the file: people have signed (or will sign) exactly it."""
    version = _version_or_404(db, version_id)
    if version.status != DocumentVersionStatus.DRAFT:
        raise HTTPException(409, "Les éléments d'une version publiée ne peuvent plus être modifiés")

    storage: StorageService = request.app.state.storage
    page_count = len(page_sizes(storage.read(_DOCUMENTS, version.id, ".pdf")))
    prepared = [
        PreparedField(
            id=f.id or "", page=f.page, x=f.x, y=f.y, width=f.width, height=f.height,
            kind=f.kind, label=f.label.strip(), required=f.required, role=f.role,
            group_key=(f.group_key or "").strip() or None,
        )
        for f in body.fields
    ]
    try:
        validate_layout(prepared, page_count)
    except FieldError as exc:
        raise HTTPException(422, str(exc)) from exc

    db.execute(delete(DocumentField).where(DocumentField.document_version_id == version.id))
    saved: list[DocumentField] = []
    for position, f in enumerate(prepared):
        try:
            field_id = uuid.UUID(f.id) if f.id else uuid.uuid4()
        except ValueError:
            field_id = uuid.uuid4()
        row = DocumentField(
            id=field_id, document_version_id=version.id, page=f.page, x=f.x, y=f.y,
            width=f.width, height=f.height, kind=f.kind, label=f.label, required=f.required,
            role=f.role, group_key=f.group_key, position=position,
        )
        db.add(row)
        saved.append(row)
    append_audit_event(
        db, action="DOCUMENT_FIELDS_UPDATED", actor_id=user.id,
        target_type="document_version", target_id=str(version.id),
        document_id=version.document_id, metadata={"count": len(saved)},
    )
    db.commit()
    return {"editable": True, "fields": [field_payload(r) for r in saved]}


@router.get("/documents/versions/{version_id}/signing-form")
def get_signing_form(
    version_id: uuid.UUID,
    user: User = Depends(require_roles(Role.SIGNER)),
    db: DbSession = Depends(get_db),
) -> dict[str, Any]:
    """What the signer is asked to provide for this version: the free-text
    elements to fill in (role 1) and a note of what will be filled for them."""
    version = _version_or_404(db, version_id)
    mine = [r for r in load_fields(db, version.id) if r.role == 1]
    return {
        "inputs": [field_payload(r) for r in mine if r.kind == FieldKind.TEXT],
        "automatic": [field_payload(r) for r in mine if automatic(r.kind)],
    }


# --- Company logo -------------------------------------------------------------


@router.get("/branding")
def branding_status(
    request: Request, user: User = Depends(get_current_user)
) -> dict[str, Any]:
    logo = branding.read_logo(request.app.state.storage)
    return {"has_logo": logo is not None, "logo_sha256": logo[1] if logo else None}


@router.get("/branding/logo")
def get_logo(request: Request, user: User = Depends(get_current_user)) -> Response:
    logo = branding.read_logo(request.app.state.storage)
    if logo is None:
        raise HTTPException(404, "No logo configured")
    data, _ = logo
    media = "image/png" if data.startswith(b"\x89PNG") else "image/jpeg"
    return Response(content=data, media_type=media, headers={"Cache-Control": "no-cache"})


@router.put("/admin/branding/logo")
async def put_logo(
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(require_roles(Role.ADMIN)),
    db: DbSession = Depends(get_db),
) -> dict[str, Any]:
    data = await file.read(branding.MAX_LOGO_BYTES + 1)
    try:
        sha = branding.save_logo(request.app.state.storage, data)
    except branding.LogoError as exc:
        raise HTTPException(422, str(exc)) from exc
    append_audit_event(
        db, action="SECURITY_CONFIGURATION_CHANGED", actor_id=user.id,
        target_type="branding", target_id="logo", metadata={"change": "logo_set", "sha256": sha},
    )
    db.commit()
    return {"has_logo": True, "logo_sha256": sha}


@router.delete("/admin/branding/logo")
def remove_logo(
    request: Request,
    user: User = Depends(require_roles(Role.ADMIN)),
    db: DbSession = Depends(get_db),
) -> dict[str, Any]:
    branding.delete_logo(request.app.state.storage)
    append_audit_event(
        db, action="SECURITY_CONFIGURATION_CHANGED", actor_id=user.id,
        target_type="branding", target_id="logo", metadata={"change": "logo_removed"},
    )
    db.commit()
    return {"has_logo": False, "logo_sha256": None}
