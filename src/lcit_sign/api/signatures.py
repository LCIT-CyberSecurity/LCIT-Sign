from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from cryptography.exceptions import InvalidSignature
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from lcit_sign import __version__
from lcit_sign.api.documents import DOCUMENTS_BUCKET, PDF_SUFFIX
from lcit_sign.config import Settings
from lcit_sign.deps import get_current_user, get_db, require_roles, user_roles
from lcit_sign.models.campaign import AssignmentStatus, SignatureAssignment
from lcit_sign.models.document import Document, DocumentVersion, DocumentVersionStatus
from lcit_sign.models.mail import NotificationType
from lcit_sign.models.signature import Signature
from lcit_sign.models.signing_key import SigningKey
from lcit_sign.models.user import Role, User
from lcit_sign.services.audit import append_audit_event
from lcit_sign.services.evidence import canonical_evidence_fields, canonical_json
from lcit_sign.services.notification_queue import enqueue_notification
from lcit_sign.services.signature_pdf import append_signature_page, render_certificate_pdf
from lcit_sign.services.signing_keys import (
    derive_private_key,
    get_or_create_active_key,
    load_public_key,
)
from lcit_sign.services.storage import StorageService
from lcit_sign.time_utils import ensure_utc

router = APIRouter(tags=["signatures"])

SIGNED_BUCKET = "signed"
EVIDENCE_BUCKET = "evidence"
CERTIFICATES_BUCKET = "certificates"
EVIDENCE_SUFFIX = ".json"
IDENTITY_PROVIDER = "oidc"  # only a generic OIDC provider exists today

_sign = require_roles(Role.SIGNER)


class SignRequest(BaseModel):
    consent: bool


def _signature_payload(signature: Signature) -> dict[str, Any]:
    return {
        "id": str(signature.id),
        "display_id": signature.display_id,
        "document_id": str(signature.document_id),
        "document_version_id": str(signature.document_version_id),
        "signed_at_utc": signature.signed_at_utc.isoformat(),
        "display_name_snapshot": signature.display_name_snapshot,
        "email_snapshot": signature.email_snapshot,
    }


def _authorize_signature_access(signature: Signature, user: User, db: DbSession) -> None:
    if signature.user_id == user.id:
        return
    if user_roles(db, user) & {Role.OPERATOR, Role.ADMIN}:
        return
    raise HTTPException(403, "Not authorized to access this signature")


def _evidence_fields_for(signature: Signature, db: DbSession) -> dict[str, Any]:
    version = db.get(DocumentVersion, signature.document_version_id)
    return canonical_evidence_fields(
        signature_id=signature.id,
        campaign_id=signature.campaign_id,
        document_id=signature.document_id,
        document_version_id=signature.document_version_id,
        version_label=version.version_label if version else "",
        original_document_sha256=signature.original_file_sha256,
        user_id=signature.user_id,
        identity_provider=signature.identity_provider,
        issuer=signature.issuer,
        subject=signature.subject,
        email=signature.email_snapshot,
        display_name=signature.display_name_snapshot,
        consent_text=signature.consent_text,
        consent_version=signature.consent_version,
        signed_at_utc=ensure_utc(signature.signed_at_utc),
        signed_file_sha256=signature.signed_file_sha256,
        application_version=signature.application_version,
        signing_key_id=signature.signing_key_id,
    )


@router.post("/documents/versions/{version_id}/sign", status_code=201)
def sign_document_version(
    request: Request,
    version_id: uuid.UUID,
    body: SignRequest,
    user: User = Depends(_sign),
    db: DbSession = Depends(get_db),
) -> dict[str, Any]:
    if not body.consent:
        raise HTTPException(400, "Explicit consent is required to sign")

    version = db.get(DocumentVersion, version_id)
    if version is None:
        raise HTTPException(404, "Document version not found")
    if version.status != DocumentVersionStatus.PUBLISHED:
        raise HTTPException(409, "Only a published version can be signed")

    already_signed = db.execute(
        select(Signature).where(
            Signature.user_id == user.id, Signature.document_version_id == version.id
        )
    ).scalar_one_or_none()
    if already_signed is not None:
        raise HTTPException(409, "You have already signed this document version")

    document = db.get(Document, version.document_id)
    if document is None:
        raise HTTPException(404, "Document not found")

    settings: Settings = request.app.state.settings
    storage: StorageService = request.app.state.storage
    try:
        signing_key = get_or_create_active_key(db, settings.master_key)
    except Exception as exc:  # signing_keys.SigningKeyError, kept generic for the HTTP boundary
        raise HTTPException(503, "Signing is not configured") from exc

    signed_at = datetime.now(UTC)
    signature_id = uuid.uuid4()
    display_id = f"SIG-{signature_id.hex[:12].upper()}"

    original_pdf = storage.read(DOCUMENTS_BUCKET, version.id, PDF_SUFFIX)
    signed_pdf = append_signature_page(
        original_pdf,
        document_title=document.title,
        version_label=version.version_label,
        display_name=user.display_name,
        email=user.email,
        signed_at=signed_at,
        consent_text=settings.consent_text,
        display_id=display_id,
    )
    signed_file_sha256 = StorageService.sha256_hex(signed_pdf)

    evidence_fields = canonical_evidence_fields(
        signature_id=signature_id,
        campaign_id=None,
        document_id=document.id,
        document_version_id=version.id,
        version_label=version.version_label,
        original_document_sha256=version.sha256,
        user_id=user.id,
        identity_provider=IDENTITY_PROVIDER,
        issuer=user.issuer,
        subject=user.subject,
        email=user.email,
        display_name=user.display_name,
        consent_text=settings.consent_text,
        consent_version=settings.consent_version,
        signed_at_utc=signed_at,
        signed_file_sha256=signed_file_sha256,
        application_version=__version__,
        signing_key_id=signing_key.key_id,
    )
    evidence_hash = hashlib.sha256(canonical_json(evidence_fields).encode("utf-8")).hexdigest()
    private_key = derive_private_key(settings.master_key, signing_key.key_id)
    cryptographic_signature = private_key.sign(bytes.fromhex(evidence_hash)).hex()

    certificate_pdf = render_certificate_pdf(
        document_title=document.title,
        version_label=version.version_label,
        display_name=user.display_name,
        email=user.email,
        signed_at=signed_at,
        consent_text=settings.consent_text,
        display_id=display_id,
    )

    signature = Signature(
        id=signature_id,
        document_id=document.id,
        document_version_id=version.id,
        user_id=user.id,
        identity_provider=IDENTITY_PROVIDER,
        issuer=user.issuer,
        subject=user.subject,
        email_snapshot=user.email,
        display_name_snapshot=user.display_name,
        consent_text=settings.consent_text,
        consent_version=settings.consent_version,
        signed_at_utc=signed_at,
        original_file_sha256=version.sha256,
        signed_file_sha256=signed_file_sha256,
        application_version=__version__,
        signing_key_id=signing_key.key_id,
        evidence_hash=evidence_hash,
        cryptographic_signature=cryptographic_signature,
    )
    db.add(signature)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "You have already signed this document version") from None

    evidence_export = {
        **evidence_fields,
        "evidence_hash": evidence_hash,
        "cryptographic_signature": cryptographic_signature,
    }
    storage.save(SIGNED_BUCKET, signature.id, PDF_SUFFIX, signed_pdf)
    storage.save(
        EVIDENCE_BUCKET,
        signature.id,
        EVIDENCE_SUFFIX,
        json.dumps(evidence_export, indent=2).encode("utf-8"),
    )
    storage.save(CERTIFICATES_BUCKET, signature.id, PDF_SUFFIX, certificate_pdf)

    pending_assignments = db.execute(
        select(SignatureAssignment).where(
            SignatureAssignment.document_version_id == version.id,
            SignatureAssignment.user_id == user.id,
            SignatureAssignment.status.in_([AssignmentStatus.PENDING, AssignmentStatus.VIEWED]),
        )
    ).scalars()
    for assignment in pending_assignments:
        assignment.status = AssignmentStatus.SIGNED
        assignment.signed_at = signed_at
        assignment.signature_id = signature.id

    enqueue_notification(
        db,
        notification_type=NotificationType.SIGNATURE_CONFIRMATION,
        recipient_email=user.email,
        recipient_user_id=user.id,
        subject=f"Confirmation de signature — {document.title}",
        body_text=(
            f"Bonjour {user.display_name},\n\n"
            f'Votre signature du document "{document.title}" (version {version.version_label}) '
            f"a bien été enregistrée.\n"
            f"Identifiant : {display_id}\n"
            f"Date : {signed_at.strftime('%d/%m/%Y à %H:%M UTC')}\n"
        ),
    )

    append_audit_event(
        db, action="SIGNATURE_CREATED", actor_id=user.id,
        target_type="signature", target_id=str(signature.id),
        document_id=document.id, signature_id=signature.id,
    )
    db.commit()
    return _signature_payload(signature)


@router.get("/signatures/me")
def list_my_signatures(
    user: User = Depends(get_current_user), db: DbSession = Depends(get_db)
) -> list[dict[str, Any]]:
    rows = db.execute(
        select(Signature)
        .where(Signature.user_id == user.id)
        .order_by(Signature.signed_at_utc.desc())
    ).scalars()
    return [_signature_payload(row) for row in rows]


@router.get("/signatures/{signature_id}")
def get_signature(
    signature_id: uuid.UUID, user: User = Depends(get_current_user), db: DbSession = Depends(get_db)
) -> dict[str, Any]:
    signature = db.get(Signature, signature_id)
    if signature is None:
        raise HTTPException(404, "Signature not found")
    _authorize_signature_access(signature, user, db)
    return _signature_payload(signature)


@router.get("/signatures/{signature_id}/signed-pdf")
def download_signed_pdf(
    request: Request,
    signature_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
) -> Response:
    signature = db.get(Signature, signature_id)
    if signature is None:
        raise HTTPException(404, "Signature not found")
    _authorize_signature_access(signature, user, db)
    storage: StorageService = request.app.state.storage
    data = storage.read(SIGNED_BUCKET, signature.id, PDF_SUFFIX)
    return Response(
        content=data, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{signature.display_id}.pdf"'},
    )


@router.get("/signatures/{signature_id}/certificate")
def download_certificate(
    request: Request,
    signature_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
) -> Response:
    signature = db.get(Signature, signature_id)
    if signature is None:
        raise HTTPException(404, "Signature not found")
    _authorize_signature_access(signature, user, db)
    storage: StorageService = request.app.state.storage
    data = storage.read(CERTIFICATES_BUCKET, signature.id, PDF_SUFFIX)
    return Response(
        content=data, media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{signature.display_id}-certificate.pdf"'
        },
    )


@router.get("/signatures/{signature_id}/evidence")
def get_evidence(
    request: Request,
    signature_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
) -> dict[str, Any]:
    signature = db.get(Signature, signature_id)
    if signature is None:
        raise HTTPException(404, "Signature not found")
    _authorize_signature_access(signature, user, db)
    storage: StorageService = request.app.state.storage
    data = storage.read(EVIDENCE_BUCKET, signature.id, EVIDENCE_SUFFIX)
    evidence: dict[str, Any] = json.loads(data)
    return evidence


@router.get("/signatures/{signature_id}/verify")
def verify_signature(
    request: Request,
    signature_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
) -> dict[str, Any]:
    signature = db.get(Signature, signature_id)
    if signature is None:
        raise HTTPException(404, "Signature not found")
    _authorize_signature_access(signature, user, db)

    storage: StorageService = request.app.state.storage
    checks: dict[str, bool] = {}

    try:
        original_bytes = storage.read(DOCUMENTS_BUCKET, signature.document_version_id, PDF_SUFFIX)
        checks["original_document_hash"] = (
            StorageService.sha256_hex(original_bytes) == signature.original_file_sha256
        )
    except OSError:
        checks["original_document_hash"] = False

    try:
        signed_bytes = storage.read(SIGNED_BUCKET, signature.id, PDF_SUFFIX)
        checks["signed_document_hash"] = (
            StorageService.sha256_hex(signed_bytes) == signature.signed_file_sha256
        )
    except OSError:
        checks["signed_document_hash"] = False

    evidence_fields = _evidence_fields_for(signature, db)
    recomputed_hash = hashlib.sha256(canonical_json(evidence_fields).encode("utf-8")).hexdigest()
    checks["evidence_hash"] = recomputed_hash == signature.evidence_hash

    signing_key = db.execute(
        select(SigningKey).where(SigningKey.key_id == signature.signing_key_id)
    ).scalar_one_or_none()
    if signing_key is None:
        checks["cryptographic_signature"] = False
    else:
        try:
            load_public_key(signing_key.public_key_hex).verify(
                bytes.fromhex(signature.cryptographic_signature),
                bytes.fromhex(signature.evidence_hash),
            )
            checks["cryptographic_signature"] = True
        except InvalidSignature:
            checks["cryptographic_signature"] = False

    result = "VALID" if all(checks.values()) else "INVALID"
    append_audit_event(
        db, action="SIGNATURE_VERIFIED" if result == "VALID" else "SIGNATURE_VERIFICATION_FAILED",
        actor_id=user.id, target_type="signature", target_id=str(signature.id),
        signature_id=signature.id, result=result,
    )
    db.commit()
    return {"valid": result == "VALID", "checks": checks}
