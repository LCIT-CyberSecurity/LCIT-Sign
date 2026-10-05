from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from lcit_sign.models.signing_key import SigningKey, SigningKeyStatus
from lcit_sign.services.audit import append_audit_event


class SigningKeyError(Exception):
    pass


def derive_private_key(master_key: str, key_id: str) -> Ed25519PrivateKey:
    """Re-derive a signing key's Ed25519 seed on demand.

    HKDF-SHA256 over the runtime master key, salted by nothing and keyed
    by `info=key_id` so distinct key_ids derive distinct, unrelated seeds
    from the same master secret (spec §64-65) — no private key material
    is ever written to Postgres or disk.
    """
    if not master_key:
        raise SigningKeyError("LCIT_SIGN_MASTER_KEY is not configured")
    seed = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None, info=key_id.encode("utf-8")
    ).derive(master_key.encode("utf-8"))
    return Ed25519PrivateKey.from_private_bytes(seed)


def public_key_hex(private_key: Ed25519PrivateKey) -> str:
    return private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()


def load_public_key(public_key_hex_value: str) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex_value))


def get_or_create_active_key(db: DbSession, master_key: str) -> SigningKey:
    """Return the current ACTIVE signing key, lazily minting the very
    first one. Later rotations are an explicit admin action
    (`rotate_signing_key`); this only ever creates a key when none exists
    at all, which is the one-time MVP bootstrap case.
    """
    active = db.execute(
        select(SigningKey).where(SigningKey.status == SigningKeyStatus.ACTIVE)
    ).scalar_one_or_none()
    if active is not None:
        return active

    key_id = secrets.token_hex(8)
    private_key = derive_private_key(master_key, key_id)
    now = datetime.now(UTC)
    signing_key = SigningKey(
        key_id=key_id,
        public_key_hex=public_key_hex(private_key),
        status=SigningKeyStatus.ACTIVE,
        activated_at=now,
    )
    db.add(signing_key)
    db.flush()
    append_audit_event(
        db, action="SIGNING_KEY_CREATED", target_type="signing_key", target_id=signing_key.key_id
    )
    return signing_key


def rotate_signing_key(db: DbSession, master_key: str, *, actor_id: uuid.UUID) -> SigningKey:
    current = db.execute(
        select(SigningKey).where(SigningKey.status == SigningKeyStatus.ACTIVE)
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if current is not None:
        current.status = SigningKeyStatus.RETIRED
        current.retired_at = now

    key_id = secrets.token_hex(8)
    private_key = derive_private_key(master_key, key_id)
    new_key = SigningKey(
        key_id=key_id,
        public_key_hex=public_key_hex(private_key),
        status=SigningKeyStatus.ACTIVE,
        activated_at=now,
    )
    db.add(new_key)
    db.flush()
    append_audit_event(
        db, action="SIGNING_KEY_ROTATED", actor_id=actor_id,
        target_type="signing_key", target_id=new_key.key_id,
        metadata={"previous_key_id": current.key_id if current else None},
    )
    return new_key
