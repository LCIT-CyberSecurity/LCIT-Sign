from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from lcit_sign.models.audit import GENESIS_HASH, AuditChainState, AuditEvent
from lcit_sign.models.user import User
from lcit_sign.request_context import get_request_id, get_source_ip
from lcit_sign.time_utils import ensure_utc


def _canonical_json(fields: dict[str, Any]) -> str:
    return json.dumps(fields, sort_keys=True, separators=(",", ":"), default=str)


def actor_snapshot(user: User) -> dict[str, str]:
    return {
        "email": user.email,
        "display_name": user.display_name,
        "issuer": user.issuer,
        "subject": user.subject,
    }


def append_audit_event(
    db: DbSession,
    *,
    action: str,
    actor_id: uuid.UUID | None = None,
    actor_identity_snapshot: dict[str, str] | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    campaign_id: uuid.UUID | None = None,
    document_id: uuid.UUID | None = None,
    signature_id: uuid.UUID | None = None,
    request_id: str | None = None,
    source_ip: str | None = None,
    result: str = "SUCCESS",
    metadata: dict[str, Any] | None = None,
) -> AuditEvent:
    """Append one row to the audit trail and extend its hash chain.

    The `SELECT ... FOR UPDATE` on the singleton chain-state row is what
    actually serializes concurrent appenders within one transaction; without
    it two simultaneous writers could both read the same previous hash and
    produce a forked chain.
    """
    chain_state = db.execute(
        select(AuditChainState).where(AuditChainState.id == 1).with_for_update()
    ).scalar_one_or_none()
    if chain_state is None:
        chain_state = AuditChainState(id=1, last_event_hash=GENESIS_HASH)
        db.add(chain_state)
        db.flush()

    # Correlation (spec §70, §72): every event carries the request it came from
    # and the caller's address unless a call site says otherwise.
    request_id = request_id or get_request_id()
    source_ip = source_ip or get_source_ip()

    event_id = uuid.uuid4()
    timestamp_utc = datetime.now(UTC)
    canonical_fields = {
        "event_id": str(event_id),
        "timestamp_utc": timestamp_utc.isoformat(),
        "actor_id": str(actor_id) if actor_id else None,
        "actor_identity_snapshot": actor_identity_snapshot,
        "action": action,
        "target_type": target_type,
        "target_id": target_id,
        "campaign_id": str(campaign_id) if campaign_id else None,
        "document_id": str(document_id) if document_id else None,
        "signature_id": str(signature_id) if signature_id else None,
        "request_id": request_id,
        "source_ip": source_ip,
        "result": result,
        "metadata": metadata,
    }
    previous_hash = chain_state.last_event_hash
    event_hash = hashlib.sha256(
        (_canonical_json(canonical_fields) + previous_hash).encode("utf-8")
    ).hexdigest()

    event = AuditEvent(
        event_id=event_id,
        timestamp_utc=timestamp_utc,
        actor_id=actor_id,
        actor_identity_snapshot=actor_identity_snapshot,
        action=action,
        target_type=target_type,
        target_id=target_id,
        campaign_id=campaign_id,
        document_id=document_id,
        signature_id=signature_id,
        request_id=request_id,
        source_ip=source_ip,
        result=result,
        metadata_json=metadata,
        previous_event_hash=previous_hash,
        event_hash=event_hash,
    )
    db.add(event)
    chain_state.last_event_hash = event_hash
    db.flush()
    return event


def verify_audit_chain(db: DbSession) -> tuple[bool, int | None]:
    """Recompute the chain from genesis; return (is_valid, first_bad_sequence)."""
    previous_hash = GENESIS_HASH
    for event in db.execute(select(AuditEvent).order_by(AuditEvent.sequence)).scalars():
        if event.previous_event_hash != previous_hash:
            return False, event.sequence
        canonical_fields = {
            "event_id": str(event.event_id),
            "timestamp_utc": ensure_utc(event.timestamp_utc).isoformat(),
            "actor_id": str(event.actor_id) if event.actor_id else None,
            "actor_identity_snapshot": event.actor_identity_snapshot,
            "action": event.action,
            "target_type": event.target_type,
            "target_id": event.target_id,
            "campaign_id": str(event.campaign_id) if event.campaign_id else None,
            "document_id": str(event.document_id) if event.document_id else None,
            "signature_id": str(event.signature_id) if event.signature_id else None,
            "request_id": event.request_id,
            "source_ip": event.source_ip,
            "result": event.result,
            "metadata": event.metadata_json,
        }
        expected_hash = hashlib.sha256(
            (_canonical_json(canonical_fields) + previous_hash).encode("utf-8")
        ).hexdigest()
        if expected_hash != event.event_hash:
            return False, event.sequence
        previous_hash = event.event_hash
    return True, None
