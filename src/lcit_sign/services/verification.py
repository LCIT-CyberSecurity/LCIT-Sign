from __future__ import annotations

import hashlib
import uuid
from typing import Any

from cryptography.exceptions import InvalidSignature
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from lcit_sign.models.document import DocumentVersion
from lcit_sign.models.report import Report
from lcit_sign.models.signature import Signature
from lcit_sign.models.signing_key import SigningKey, SigningKeyStatus
from lcit_sign.services.evidence import canonical_evidence_fields, canonical_json
from lcit_sign.services.field_stamping import fields_digest
from lcit_sign.services.signing_keys import load_public_key
from lcit_sign.services.storage import StorageService
from lcit_sign.time_utils import ensure_utc

DOCUMENTS_BUCKET = "documents"
SIGNED_BUCKET = "signed"
REPORTS_BUCKET = "reports"
PDF_SUFFIX = ".pdf"


def evidence_fields_for(signature: Signature, db: DbSession) -> dict[str, Any]:
    """Rebuild a signature's evidence field set from its stored row — the
    exact inverse of what signing hashed (the two must stay identical)."""
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
        fields_sha256=(
            fields_digest(signature.field_values) if signature.field_values is not None else None
        ),
        prior_signatures=signature.prior_signatures,
    )


def _file_hash_matches(storage: StorageService, bucket: str, object_id: Any, expected: str) -> bool:
    try:
        return StorageService.sha256_hex(storage.read(bucket, object_id, PDF_SUFFIX)) == expected
    except OSError:
        return False


def _signature_valid(
    key: SigningKey | None, signature_hex: str, signed_digest_hex: str
) -> bool:
    if key is None:
        return False
    try:
        load_public_key(key.public_key_hex).verify(
            bytes.fromhex(signature_hex), bytes.fromhex(signed_digest_hex)
        )
    except (InvalidSignature, ValueError):
        return False
    return True


def verify_signature_record(
    db: DbSession, storage: StorageService, signature: Signature
) -> dict[str, bool]:
    """Spec §45: original hash, signed-PDF hash, evidence hash, the
    cryptographic signature, the key used, and metadata consistency."""
    checks: dict[str, bool] = {}
    checks["original_document_hash"] = _file_hash_matches(
        storage, DOCUMENTS_BUCKET, signature.document_version_id, signature.original_file_sha256
    )
    checks["signed_document_hash"] = _file_hash_matches(
        storage, SIGNED_BUCKET, signature.id, signature.signed_file_sha256
    )

    recomputed = hashlib.sha256(
        canonical_json(evidence_fields_for(signature, db)).encode("utf-8")
    ).hexdigest()
    checks["evidence_hash"] = recomputed == signature.evidence_hash

    key = db.execute(
        select(SigningKey).where(SigningKey.key_id == signature.signing_key_id)
    ).scalar_one_or_none()
    checks["cryptographic_signature"] = _signature_valid(
        key, signature.cryptographic_signature, signature.evidence_hash
    )
    # A copy that carries earlier signers' stamps points at their signatures: each
    # must still exist with the same evidence hash.
    if signature.prior_signatures:
        checks["prior_signatures"] = all(
            (earlier := db.get(Signature, uuid.UUID(ref["signature_id"]))) is not None
            and earlier.evidence_hash == ref["evidence_hash"]
            for ref in signature.prior_signatures
        )
    # A revoked key no longer vouches for what it signed; a retired one still does.
    checks["signing_key_trusted"] = key is not None and key.status != SigningKeyStatus.REVOKED

    version = db.get(DocumentVersion, signature.document_version_id)
    checks["metadata_consistent"] = (
        version is not None
        and version.document_id == signature.document_id
        and version.sha256 == signature.original_file_sha256
    )
    return checks


def verify_report_record(
    db: DbSession, storage: StorageService, report: Report
) -> dict[str, bool]:
    checks = {
        "pdf_hash": _file_hash_matches(storage, REPORTS_BUCKET, report.id, report.pdf_sha256)
    }
    key = db.execute(
        select(SigningKey).where(SigningKey.key_id == report.signing_key_id)
    ).scalar_one_or_none()
    checks["cryptographic_signature"] = _signature_valid(
        key, report.cryptographic_signature, report.pdf_sha256
    )
    return checks
