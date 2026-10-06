"""Signing through DocuSign, as the worker sees it: when a person's turn comes, an envelope is
queued for them; the worker sends it (DocuSign mails the signer, who signs on DocuSign), follows
its status, and when it is completed brings back the signed PDF and the certificate, records the
signature like any other, and asks the next signer.

Polled, not pushed: DocuSign's webhooks need an address reachable from the Internet, which an
internal server does not have."""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from lcit_sign import __version__
from lcit_sign.config import Settings
from lcit_sign.models.campaign import AssignmentStatus, Campaign, SignatureAssignment
from lcit_sign.models.document import Document, DocumentVersion
from lcit_sign.models.docusign import DocusignConfig, DocusignEnvelope
from lcit_sign.models.signature import Signature
from lcit_sign.models.user import User
from lcit_sign.services.audit import append_audit_event
from lcit_sign.services.crypto import decrypt_secret
from lcit_sign.services.docusign import (
    DocusignClient,
    DocusignError,
    DocusignSettings,
)
from lcit_sign.services.storage import StorageService

logger = logging.getLogger(__name__)

METHOD_LOCAL = "LOCAL"
METHOD_DOCUSIGN = "DOCUSIGN"
MAX_ATTEMPTS = 5


def load_settings(db: DbSession, master_key: str) -> DocusignSettings | None:
    """The saved connection, or None while it is not complete."""
    row = db.get(DocusignConfig, 1)
    if (
        row is None
        or not row.encrypted_private_key
        or not (row.integration_key and row.user_id and row.account_id)
    ):
        return None
    return DocusignSettings(
        environment=row.environment,
        integration_key=row.integration_key,
        user_id=row.user_id,
        account_id=row.account_id,
        private_key=decrypt_secret(master_key, row.encrypted_private_key),
        auth_url=row.auth_url,
        api_url=row.api_url,
    )


def is_configured(db: DbSession) -> bool:
    row = db.get(DocusignConfig, 1)
    return bool(
        row
        and row.encrypted_private_key
        and row.integration_key
        and row.user_id
        and row.account_id
    )


def queue_envelope(db: DbSession, assignment: SignatureAssignment) -> None:
    """It is this person's turn on a DocuSign campaign: the worker will send the envelope."""
    if db.execute(
        select(DocusignEnvelope.id).where(DocusignEnvelope.assignment_id == assignment.id)
    ).first():
        return
    db.add(DocusignEnvelope(assignment_id=assignment.id, status="QUEUED"))


def uses_docusign(db: DbSession, campaign_id: uuid.UUID) -> bool:
    campaign = db.get(Campaign, campaign_id)
    return campaign is not None and campaign.signature_method == METHOD_DOCUSIGN


def envelope_of(db: DbSession, assignment_id: uuid.UUID) -> DocusignEnvelope | None:
    return db.execute(
        select(DocusignEnvelope).where(DocusignEnvelope.assignment_id == assignment_id)
    ).scalar_one_or_none()


def follow_up(
    db: DbSession, assignment: SignatureAssignment, public_base_url: str
) -> dict[str, str | None] | None:
    """What the signer is told about their DocuSign envelope; None when the request is not a
    DocuSign one. `inbox_url` only exists on the test stack (the mock's mailbox)."""
    if not uses_docusign(db, assignment.campaign_id):
        return None
    row = envelope_of(db, assignment.id)
    config = db.get(DocusignConfig, 1)
    inbox = (
        f"{public_base_url.rstrip('/')}/mock-docusign/"
        if config is not None and config.environment == "test"
        else None
    )
    return {
        "status": row.status if row else "QUEUED",
        "error": row.error if row else None,
        "inbox_url": inbox,
    }


# -- sending ---------------------------------------------------------------------------------


def _source_pdf(
    db: DbSession,
    storage: StorageService,
    assignment: SignatureAssignment,
    version: DocumentVersion,
) -> bytes:
    """What this signer is given: the original, or — after an earlier signer — that signer's
    signed copy, so the stamps and signatures so far are on what they sign."""
    from lcit_sign.api.documents import DOCUMENTS_BUCKET, PDF_SUFFIX
    from lcit_sign.api.signatures import SIGNED_BUCKET

    earlier = db.execute(
        select(SignatureAssignment)
        .where(
            SignatureAssignment.campaign_id == assignment.campaign_id,
            SignatureAssignment.document_version_id == assignment.document_version_id,
            SignatureAssignment.role < assignment.role,
            SignatureAssignment.status == AssignmentStatus.SIGNED,
            SignatureAssignment.signature_id.is_not(None),
        )
        .order_by(SignatureAssignment.role.desc())
    ).scalars().first()
    if earlier is not None and earlier.signature_id is not None:
        return storage.read(SIGNED_BUCKET, earlier.signature_id, PDF_SUFFIX)
    return storage.read(DOCUMENTS_BUCKET, version.id, PDF_SUFFIX)


def _send(
    db: DbSession,
    storage: StorageService,
    client: DocusignClient,
    row: DocusignEnvelope,
    assignment: SignatureAssignment,
) -> None:
    from lcit_sign.api.fields import load_fields, to_prepared

    version = db.get(DocumentVersion, assignment.document_version_id)
    document = db.get(Document, version.document_id) if version else None
    person = db.get(User, assignment.user_id)
    campaign = db.get(Campaign, assignment.campaign_id)
    if version is None or document is None or person is None or campaign is None:
        raise DocusignError("Le document ou le signataire n'existe plus.")
    fields = [f for f in to_prepared(load_fields(db, version.id)) if f.role == assignment.role]
    row.envelope_id = client.create_envelope(
        subject=f"{document.title} — à signer",
        message=(
            f'Bonjour {person.display_name}, vous êtes invité(e) à signer "{document.title}" '
            f"(demande « {campaign.name} »)."
        ),
        document_name=f"{document.title}.pdf",
        pdf=_source_pdf(db, storage, assignment, version),
        signer_name=person.display_name,
        signer_email=person.email,
        fields=fields,
    )
    row.status = "SENT"
    row.error = None
    append_audit_event(
        db, action="DOCUSIGN_ENVELOPE_SENT", target_type="assignment", target_id=str(assignment.id),
        campaign_id=campaign.id, metadata={"envelope_id": row.envelope_id},
    )


# -- coming back -----------------------------------------------------------------------------


def _complete(
    db: DbSession,
    settings: Settings,
    storage: StorageService,
    client: DocusignClient,
    row: DocusignEnvelope,
    assignment: SignatureAssignment,
) -> None:
    """DocuSign says it is signed: bring back the signed PDF and the certificate and record the
    signature, with the same proof file as any other (hash, our key) plus DocuSign's references."""
    from lcit_sign.api.documents import PDF_SUFFIX
    from lcit_sign.api.signatures import (
        CERTIFICATES_BUCKET,
        EVIDENCE_BUCKET,
        EVIDENCE_SUFFIX,
        SIGNED_BUCKET,
    )
    from lcit_sign.services.campaign_roles import release_next_role
    from lcit_sign.services.evidence import canonical_evidence_fields, canonical_json
    from lcit_sign.services.signing_keys import derive_private_key, get_or_create_active_key

    assert row.envelope_id  # noqa: S101 - only a sent envelope is followed
    version = db.get(DocumentVersion, assignment.document_version_id)
    document = db.get(Document, version.document_id) if version else None
    person = db.get(User, assignment.user_id)
    campaign = db.get(Campaign, assignment.campaign_id)
    if version is None or document is None or person is None or campaign is None:
        raise DocusignError("Le document ou le signataire n'existe plus.")
    signed_pdf = client.signed_pdf(row.envelope_id)
    certificate = client.certificate(row.envelope_id)
    signing_key = get_or_create_active_key(db, settings.master_key)

    signed_at = datetime.now(UTC)
    signature_id = uuid.uuid4()
    signed_sha = StorageService.sha256_hex(signed_pdf)
    consent = (
        "Signature électronique réalisée avec DocuSign "
        f"(enveloppe {row.envelope_id}), après invitation par LCIT Sign."
    )
    evidence_fields = canonical_evidence_fields(
        signature_id=signature_id,
        campaign_id=campaign.id,
        document_id=document.id,
        document_version_id=version.id,
        version_label=version.version_label,
        original_document_sha256=version.sha256,
        user_id=person.id,
        identity_provider="docusign",
        issuer=person.issuer,
        subject=person.subject,
        email=person.email,
        display_name=person.display_name,
        consent_text=consent,
        consent_version=settings.consent_version,
        signed_at_utc=signed_at,
        signed_file_sha256=signed_sha,
        application_version=__version__,
        signing_key_id=signing_key.key_id,
    )
    evidence_hash = hashlib.sha256(canonical_json(evidence_fields).encode("utf-8")).hexdigest()
    cryptographic_signature = (
        derive_private_key(settings.master_key, signing_key.key_id)
        .sign(bytes.fromhex(evidence_hash))
        .hex()
    )
    signature = Signature(
        id=signature_id,
        campaign_id=campaign.id,
        document_id=document.id,
        document_version_id=version.id,
        user_id=person.id,
        identity_provider="docusign",
        issuer=person.issuer,
        subject=person.subject,
        email_snapshot=person.email,
        display_name_snapshot=person.display_name,
        consent_text=consent,
        consent_version=settings.consent_version,
        signed_at_utc=signed_at,
        original_file_sha256=version.sha256,
        signed_file_sha256=signed_sha,
        application_version=__version__,
        signing_key_id=signing_key.key_id,
        evidence_hash=evidence_hash,
        cryptographic_signature=cryptographic_signature,
    )
    db.add(signature)
    db.flush()
    storage.save(SIGNED_BUCKET, signature.id, PDF_SUFFIX, signed_pdf)
    storage.save(CERTIFICATES_BUCKET, signature.id, PDF_SUFFIX, certificate)
    storage.save(
        EVIDENCE_BUCKET,
        signature.id,
        EVIDENCE_SUFFIX,
        json.dumps(
            {
                **evidence_fields,
                "field_values": [],
                "evidence_hash": evidence_hash,
                "cryptographic_signature": cryptographic_signature,
                "docusign": {
                    "envelope_id": row.envelope_id,
                    "certificate_sha256": StorageService.sha256_hex(certificate),
                },
            },
            indent=2,
        ).encode("utf-8"),
    )
    assignment.status = AssignmentStatus.SIGNED
    assignment.signed_at = signed_at
    assignment.signature_id = signature.id
    row.status = "COMPLETED"
    row.error = None
    db.flush()
    release_next_role(
        db, campaign.id, version.id, assignment.role,
        document_title=document.title,
        campaign_name=campaign.name,
        signed_by=person.display_name,
        public_base_url=settings.public_base_url,
    )
    append_audit_event(
        db, action="SIGNATURE_CREATED", actor_id=person.id,
        target_type="signature", target_id=str(signature.id),
        document_id=document.id, signature_id=signature.id,
        metadata={"docusign_envelope_id": row.envelope_id},
    )


def _fail(row: DocusignEnvelope, exc: Exception) -> None:
    row.attempts += 1
    row.error = str(exc)[:1000]
    if row.attempts >= MAX_ATTEMPTS:
        row.status = "FAILED"


def process_docusign(
    db: DbSession,
    settings: Settings,
    storage: StorageService,
    client_factory: Callable[[DocusignSettings], DocusignClient] | None = None,
) -> int:
    """Send what is queued, follow what was sent, bring back what is signed. Idempotent and
    safe to run often. Returns how many envelopes changed."""
    active = list(
        db.execute(
            select(DocusignEnvelope).where(DocusignEnvelope.status.in_(["QUEUED", "SENT"]))
        ).scalars()
    )
    if not active:
        return 0
    config = load_settings(db, settings.master_key)
    if config is None:
        return 0  # not configured (any more): they wait
    http = httpx.Client(timeout=30.0)
    client = client_factory(config) if client_factory else DocusignClient(http, config)
    changed = 0
    try:
        for row in active:
            assignment = db.get(SignatureAssignment, row.assignment_id)
            if assignment is None:
                continue
            try:
                with db.begin_nested():  # nothing half-done is kept if DocuSign fails midway
                    if assignment.status in (AssignmentStatus.CANCELLED, AssignmentStatus.EXPIRED):
                        # The request was cancelled: withdraw the envelope.
                        if row.envelope_id:
                            client.void(row.envelope_id, "Demande annulée dans LCIT Sign")
                        row.status = "VOIDED"
                    elif row.status == "QUEUED":
                        _send(db, storage, client, row, assignment)
                    else:
                        assert row.envelope_id  # noqa: S101
                        state = client.status(row.envelope_id)
                        if state == "completed":
                            _complete(db, settings, storage, client, row, assignment)
                        elif state in ("declined", "voided"):
                            row.status = state.upper()
                        else:
                            continue
                changed += 1
            except Exception as exc:  # one envelope failing must not stop the others
                logger.warning("DocuSign envelope %s: %s", row.id, exc)
                _fail(row, exc)
                changed += 1
            db.commit()
    finally:
        http.close()
    return changed
