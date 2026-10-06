from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from lcit_sign import __version__
from lcit_sign.api.documents import DOCUMENTS_BUCKET, PDF_SUFFIX
from lcit_sign.api.fields import load_fields, to_prepared
from lcit_sign.config import Settings
from lcit_sign.deps import get_current_user, get_db, user_roles
from lcit_sign.models.campaign import AssignmentStatus, Campaign, SignatureAssignment
from lcit_sign.models.document import Document, DocumentVersion, DocumentVersionStatus
from lcit_sign.models.mail import NotificationType
from lcit_sign.models.signature import Signature
from lcit_sign.models.user import Role, User
from lcit_sign.services import branding
from lcit_sign.services.audit import append_audit_event
from lcit_sign.services.campaign_roles import (
    load_roles,
    release_next_role,
    role_label,
    waiting_on,
)
from lcit_sign.services.docusign_flow import uses_docusign
from lcit_sign.services.evidence import canonical_evidence_fields, canonical_json
from lcit_sign.services.field_stamping import (
    FieldError,
    fields_digest,
    stamp_fields,
)
from lcit_sign.services.field_stamping import resolve as resolve_fields
from lcit_sign.services.notification_queue import enqueue_notification
from lcit_sign.services.signature_pdf import append_signature_page, render_certificate_pdf
from lcit_sign.services.signing_keys import (
    derive_private_key,
    get_or_create_active_key,
)
from lcit_sign.services.storage import StorageService
from lcit_sign.services.verification import verify_signature_record

router = APIRouter(tags=["signatures"])

SIGNED_BUCKET = "signed"
EVIDENCE_BUCKET = "evidence"
CERTIFICATES_BUCKET = "certificates"
EVIDENCE_SUFFIX = ".json"
IDENTITY_PROVIDER = "oidc"  # only a generic OIDC provider exists today

# Anyone signed in may sign what they were asked to sign: no role is needed, the request is
# addressed to the person (checked in perform_signature). Signing unasked still needs SIGNER.
_sign = get_current_user


class SignRequest(BaseModel):
    consent: bool
    # Free-text elements the signer filled in, by element id.
    values: dict[str, str] = {}


def _signature_payload(signature: Signature) -> dict[str, Any]:
    return {
        "id": str(signature.id),
        "display_id": signature.display_id,
        "campaign_id": str(signature.campaign_id) if signature.campaign_id else None,
        "document_id": str(signature.document_id),
        "document_version_id": str(signature.document_version_id),
        "signed_at_utc": signature.signed_at_utc.isoformat(),
        "display_name_snapshot": signature.display_name_snapshot,
        "email_snapshot": signature.email_snapshot,
    }


def _described(signature: Signature, db: DbSession) -> dict[str, Any]:
    """The signature payload plus what a human needs to recognise it: the
    document title and version, the campaign name and the signed file's hash."""
    version = db.get(DocumentVersion, signature.document_version_id)
    document = db.get(Document, signature.document_id)
    campaign = db.get(Campaign, signature.campaign_id) if signature.campaign_id else None
    return {
        **_signature_payload(signature),
        "document_title": document.title if document else "",
        "version_label": version.version_label if version else "",
        "campaign_name": campaign.name if campaign else None,
        "signed_file_sha256": signature.signed_file_sha256,
        "original_file_sha256": signature.original_file_sha256,
        "signing_key_id": signature.signing_key_id,
    }


def _authorize_signature_access(signature: Signature, user: User, db: DbSession) -> None:
    if signature.user_id == user.id:
        return
    if user_roles(db, user) & {Role.OPERATOR, Role.ADMIN}:
        return
    raise HTTPException(403, "Not authorized to access this signature")


def prior_stamps(
    db: DbSession, campaign_id: uuid.UUID | None, version_id: uuid.UUID, role: int
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """What the signers before this position have already put on the document, and which
    signatures those are. Cumulative: the latest earlier signature carries all of it."""
    if campaign_id is None or role <= 1:
        return [], []
    earlier = list(
        db.execute(
            select(Signature)
            .join(SignatureAssignment, SignatureAssignment.signature_id == Signature.id)
            .where(
                SignatureAssignment.campaign_id == campaign_id,
                SignatureAssignment.document_version_id == version_id,
                SignatureAssignment.role < role,
                SignatureAssignment.status == AssignmentStatus.SIGNED,
            )
            .order_by(SignatureAssignment.role)
        ).scalars()
    )
    if not earlier:
        return [], []
    return (
        list(earlier[-1].field_values or []),
        [{"signature_id": str(e.id), "evidence_hash": e.evidence_hash} for e in earlier],
    )


@router.get("/assignments/{assignment_id}/preview")
def preview_assignment(
    request: Request,
    assignment_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
) -> Response:
    """The document as this person sees it: once signed, their signed copy; before, the
    document with what the signers before them have already put on it (the RSSI's signature
    and date), so they sign what they are shown."""
    assignment = db.get(SignatureAssignment, assignment_id)
    if assignment is None or assignment.user_id != user.id:
        raise HTTPException(404, "Assignment not found")
    storage: StorageService = request.app.state.storage

    if assignment.signature_id is not None and assignment.status == AssignmentStatus.SIGNED:
        data = storage.read(SIGNED_BUCKET, assignment.signature_id, PDF_SUFFIX)
    else:
        data = storage.read(DOCUMENTS_BUCKET, assignment.document_version_id, PDF_SUFFIX)
        values, _ = prior_stamps(
            db, assignment.campaign_id, assignment.document_version_id, assignment.role
        )
        logo = branding.read_logo(storage)
        settings: Settings = request.app.state.settings
        # The person's own elements too, where they will be, with their real name and today's date
        # (an answer not typed yet shows its label), in a dotted frame: not signed yet.
        own = resolve_fields(
            to_prepared(load_fields(db, assignment.document_version_id)),
            role=assignment.role,
            signer_name=user.display_name,
            signer_email=user.email,
            signed_at=datetime.now(UTC),
            inputs={},
            logo_sha256=logo[1] if logo else None,
            signer_first_name=user.given_name or "",
            signer_last_name=user.family_name or "",
            tz=settings.timezone,
            preview=True,
        )
        if values or own:
            data = stamp_fields(data, [*values, *own], logo[0] if logo else None)
        if assignment.status == AssignmentStatus.PENDING:
            assignment.status = AssignmentStatus.VIEWED
            assignment.first_viewed_at = datetime.now(UTC)
    version = db.get(DocumentVersion, assignment.document_version_id)
    append_audit_event(
        db, action="DOCUMENT_VIEWED", actor_id=user.id,
        target_type="document_version", target_id=str(assignment.document_version_id),
        document_id=version.document_id if version else None,
    )
    db.commit()
    return Response(
        content=data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'inline; filename="apercu.pdf"',
            "Cache-Control": "no-store",
        },
    )


def perform_signature(
    request: Request,
    db: DbSession,
    user: User,
    version_id: uuid.UUID,
    values: dict[str, str],
    *,
    only_campaign: uuid.UUID | None = None,
    dry_run: bool = False,
) -> Signature | None:
    """Sign one document version as `user`: stamp their elements, build the proof, store the
    files, mark the assignment signed and ask the next signer. Does not commit. With
    `dry_run` it stops after checking everything that can refuse (inputs included) and
    returns None. `only_campaign` restricts which campaign's assignment is answered.
    Raises HTTPException."""
    version = db.get(DocumentVersion, version_id)
    if version is None:
        raise HTTPException(404, "Document version not found")
    if version.status != DocumentVersionStatus.PUBLISHED:
        raise HTTPException(409, "Only a published version can be signed")

    # The campaign this signature answers: the oldest outstanding assignment
    # for this user and version (spec §125 — "dans quelle campagne"). With
    # none, the signature is campaign-less and can only happen once.
    pending_assignments = list(
        db.execute(
            select(SignatureAssignment)
            .where(
                SignatureAssignment.document_version_id == version.id,
                SignatureAssignment.user_id == user.id,
                SignatureAssignment.status.in_([AssignmentStatus.PENDING, AssignmentStatus.VIEWED]),
                *([SignatureAssignment.campaign_id == only_campaign] if only_campaign else []),
            )
            .order_by(SignatureAssignment.assigned_at)
        ).scalars()
    )
    if not pending_assignments:
        # Asked, but not yet: an earlier signer (the RSSI, say) has to sign first.
        waiting = db.execute(
            select(SignatureAssignment).where(
                SignatureAssignment.document_version_id == version.id,
                SignatureAssignment.user_id == user.id,
                SignatureAssignment.status == AssignmentStatus.WAITING,
            )
        ).scalars().first()
        if waiting is not None:
            who = ", ".join(waiting_on(db, waiting)) or "le signataire précédent"
            raise HTTPException(
                409, f"Ce document n'est pas encore à signer : {who} doit signer d'abord"
            )
        # A campaign that was cancelled or closed no longer accepts signatures: its
        # outstanding assignments were ended, and signing must not slip through as
        # if the person had never been asked.
        ended = db.execute(
            select(SignatureAssignment.id).where(
                SignatureAssignment.document_version_id == version.id,
                SignatureAssignment.user_id == user.id,
                SignatureAssignment.status.in_(
                    [AssignmentStatus.CANCELLED, AssignmentStatus.EXPIRED]
                ),
            )
        ).first()
        if ended is not None:
            raise HTTPException(409, "Cette campagne n'est plus ouverte à la signature")
    if only_campaign and not pending_assignments:
        # Never fall through to a campaign-less signature when a campaign was asked for.
        raise HTTPException(409, "Rien à signer pour cette campagne")
    if not pending_assignments and Role.SIGNER not in user_roles(db, user):
        # Signing of one's own accord (nobody asked) stays a role; being asked needs none.
        raise HTTPException(403, "Insufficient role")
    campaign_id = pending_assignments[0].campaign_id if pending_assignments else None
    if campaign_id is not None and uses_docusign(db, campaign_id):
        raise HTTPException(
            409,
            "Cette demande se signe avec DocuSign : ouvrez l'e-mail que DocuSign vous a envoyé.",
        )
    role = pending_assignments[0].role if pending_assignments else 1
    # With an outstanding assignment, only a signature for that same
    # campaign counts as "already signed" (a renewal asks again). Without
    # one, any earlier signature of this version means there is nothing
    # left to ask.
    already_signed_query = select(Signature.id).where(
        Signature.user_id == user.id, Signature.document_version_id == version.id
    )
    if campaign_id is not None:
        already_signed_query = already_signed_query.where(Signature.campaign_id == campaign_id)
    already_signed = db.execute(already_signed_query).first()
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

    # Elements the operator placed on the document: resolve this signer's values
    # (automatic ones from the account and the clock, text from what was typed)
    # and stamp them on a copy of the original.
    logo = branding.read_logo(storage)

    # In a campaign with several signers, this copy carries the stamps of those who signed before.
    prior_values, prior_refs = prior_stamps(db, campaign_id, version.id, role)
    try:
        own_fields = resolve_fields(
            to_prepared(load_fields(db, version.id)),
            role=role,
            signer_name=user.display_name,
            signer_email=user.email,
            signed_at=signed_at,
            inputs=values,
            logo_sha256=logo[1] if logo else None,
            signer_first_name=user.given_name or "",
            signer_last_name=user.family_name or "",
            tz=settings.timezone,
        )
    except FieldError as exc:
        raise HTTPException(422, str(exc)) from exc
    if dry_run:
        return None
    resolved_fields = prior_values + own_fields
    stamped_pdf = stamp_fields(original_pdf, resolved_fields, logo[0] if logo else None)

    signed_pdf = append_signature_page(
        stamped_pdf,
        document_title=document.title,
        version_label=version.version_label,
        display_name=user.display_name,
        email=user.email,
        signed_at=signed_at,
        consent_text=settings.consent_text,
        display_id=display_id,
        original_sha256=version.sha256,
    )
    signed_file_sha256 = StorageService.sha256_hex(signed_pdf)

    evidence_fields = canonical_evidence_fields(
        signature_id=signature_id,
        campaign_id=campaign_id,
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
        fields_sha256=fields_digest(resolved_fields) if resolved_fields else None,
        prior_signatures=prior_refs or None,
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
        original_sha256=version.sha256,
    )

    signature = Signature(
        id=signature_id,
        campaign_id=campaign_id,
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
        field_values=resolved_fields or None,
        prior_signatures=prior_refs or None,
    )
    db.add(signature)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "You have already signed this document version") from None

    evidence_export = {
        **evidence_fields,
        "field_values": resolved_fields,
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

    for assignment in pending_assignments:
        assignment.status = AssignmentStatus.SIGNED
        assignment.signed_at = signed_at
        assignment.signature_id = signature.id
    # Then it is the next signer's turn on that document (the queries below must
    # see the assignments just marked signed).
    db.flush()
    for released in {(a.campaign_id, a.role) for a in pending_assignments}:
        campaign = db.get(Campaign, released[0])
        release_next_role(
            db, released[0], version.id, released[1],
            document_title=document.title,
            campaign_name=campaign.name if campaign else "",
            signed_by=user.display_name,
            public_base_url=settings.public_base_url,
        )

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
    return signature


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
    signature = perform_signature(request, db, user, version_id, body.values)
    assert signature is not None  # noqa: S101 - only a dry run returns None
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
    return [_described(row, db) for row in rows]


@router.get("/signatures/{signature_id}/chain")
def signature_chain(
    signature_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
) -> dict[str, Any]:
    """Who signed this document in this campaign, in order, and who is still to. Someone from
    the "every recipient" list sees their own line and a count for the others (colleagues'
    names are not theirs to read); named signers (the RSSI) are visible to everyone in the chain;
    operators and administrators see everyone."""
    signature = db.get(Signature, signature_id)
    if signature is None:
        raise HTTPException(404, "Signature not found")
    _authorize_signature_access(signature, user, db)
    staff = bool(user_roles(db, user) & {Role.OPERATOR, Role.ADMIN})

    if signature.campaign_id is None:
        return {
            "steps": [_step(signature.display_name_snapshot, signature.email_snapshot, "SIGNED",
                            signature, 1, "")],
            "others": None,
            "complete": True,
        }

    rows = db.execute(
        select(SignatureAssignment, User)
        .join(User, User.id == SignatureAssignment.user_id)
        .where(
            SignatureAssignment.campaign_id == signature.campaign_id,
            SignatureAssignment.document_version_id == signature.document_version_id,
            SignatureAssignment.status != AssignmentStatus.CANCELLED,
        )
        .order_by(SignatureAssignment.role, User.display_name)
    ).all()
    roles = {r.role: r for r in load_roles(db, signature.campaign_id)}
    signatures = {
        s.id: s
        for s in db.execute(
            select(Signature).where(
                Signature.id.in_([a.signature_id for a, _ in rows if a.signature_id])
            )
        ).scalars()
    }
    steps: list[dict[str, Any]] = []
    hidden = {"count": 0, "signed": 0}
    for assignment, person in rows:
        crowd = roles.get(assignment.role) is not None and roles[assignment.role].mode == "EACH"
        mine = assignment.user_id == user.id
        if crowd and not mine and not staff:
            hidden["count"] += 1
            hidden["signed"] += 1 if assignment.status == AssignmentStatus.SIGNED else 0
            continue
        steps.append(
            _step(
                person.display_name, person.email, assignment.status.value,
                signatures.get(assignment.signature_id) if assignment.signature_id else None,
                assignment.role, role_label(roles.get(assignment.role), assignment.role),
                mine=mine,
            )
        )
    return {
        "steps": steps,
        "others": hidden if hidden["count"] else None,
        "complete": all(a.status == AssignmentStatus.SIGNED for a, _ in rows),
    }


def _step(
    name: str,
    email: str,
    status: str,
    signature: Signature | None,
    role: int,
    label: str,
    *,
    mine: bool = True,
) -> dict[str, Any]:
    return {
        "role": role,
        "role_label": label,
        "name": name,
        "email": email,
        "status": status,
        "signed_at": signature.signed_at_utc.isoformat() if signature else None,
        "display_id": signature.display_id if signature else None,
        "mine": mine,
    }


@router.get("/signatures/{signature_id}")
def get_signature(
    signature_id: uuid.UUID, user: User = Depends(get_current_user), db: DbSession = Depends(get_db)
) -> dict[str, Any]:
    signature = db.get(Signature, signature_id)
    if signature is None:
        raise HTTPException(404, "Signature not found")
    _authorize_signature_access(signature, user, db)
    return _described(signature, db)


@router.get("/signatures/{signature_id}/signed-pdf")
def download_signed_pdf(
    request: Request,
    signature_id: uuid.UUID,
    inline: bool = False,
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
        headers={
            "Content-Disposition": (
                f'{"inline" if inline else "attachment"}; filename="{signature.display_id}.pdf"'
            )
        },
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
    checks = verify_signature_record(db, storage, signature)

    result = "VALID" if all(checks.values()) else "INVALID"
    append_audit_event(
        db, action="SIGNATURE_VERIFIED" if result == "VALID" else "SIGNATURE_VERIFICATION_FAILED",
        actor_id=user.id, target_type="signature", target_id=str(signature.id),
        signature_id=signature.id, result=result,
    )
    db.commit()
    return {"valid": result == "VALID", "checks": checks}
