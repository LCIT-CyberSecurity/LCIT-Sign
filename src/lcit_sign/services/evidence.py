from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any


def canonical_evidence_fields(
    *,
    signature_id: uuid.UUID,
    campaign_id: uuid.UUID | None,
    document_id: uuid.UUID,
    document_version_id: uuid.UUID,
    version_label: str,
    original_document_sha256: str,
    user_id: uuid.UUID,
    identity_provider: str,
    issuer: str,
    subject: str,
    email: str,
    display_name: str,
    consent_text: str,
    consent_version: str,
    signed_at_utc: datetime,
    signed_file_sha256: str,
    application_version: str,
    signing_key_id: str,
    fields_sha256: str | None = None,
) -> dict[str, Any]:
    """The exact field set a signature's evidence hash is computed over
    (spec §60). Called both when signing (to produce the hash) and when
    verifying (to recompute it from the stored row) — the two call sites
    must stay structurally identical or every verification would fail.
    """
    evidence = {
        "signature_id": str(signature_id),
        "campaign_id": str(campaign_id) if campaign_id else None,
        "document_id": str(document_id),
        "document_version_id": str(document_version_id),
        "document_version": version_label,
        "original_document_sha256": original_document_sha256,
        "user_internal_id": str(user_id),
        "identity_provider": identity_provider,
        "issuer": issuer,
        "subject": subject,
        "email_snapshot": email,
        "display_name_snapshot": display_name,
        "consent_text": consent_text,
        "consent_version": consent_version,
        "signed_at_utc": signed_at_utc.isoformat(),
        "signed_file_sha256": signed_file_sha256,
        "application_version": application_version,
        "signing_key_id": signing_key_id,
    }
    # Only when elements were stamped: a signature made on a document with none
    # keeps exactly the field set it was signed with, so it still verifies.
    if fields_sha256 is not None:
        evidence["fields_sha256"] = fields_sha256
    return evidence


def canonical_json(fields: dict[str, Any]) -> str:
    return json.dumps(fields, sort_keys=True, separators=(",", ":"), default=str)
