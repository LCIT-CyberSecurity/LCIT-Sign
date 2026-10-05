from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_NONCE_LENGTH = 12
# Domain-separates this key from the Ed25519 signing-key derivation
# (services/signing_keys.py), which uses the same master key but a
# different HKDF info tag — the two must never collide.
_HKDF_INFO = b"credential-encryption"


def _derive_aes_key(master_key: str) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_HKDF_INFO).derive(
        master_key.encode("utf-8")
    )


def encrypt_secret(master_key: str, plaintext: str) -> str:
    """AES-256-GCM encrypt a credential for storage (spec §99-101).

    Nothing but this ciphertext ever reaches Postgres; the key itself is
    derived from the runtime-only master key and never persisted.
    """
    aesgcm = AESGCM(_derive_aes_key(master_key))
    nonce = os.urandom(_NONCE_LENGTH)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")


def decrypt_secret(master_key: str, token: str) -> str:
    raw = base64.urlsafe_b64decode(token)
    nonce, ciphertext = raw[:_NONCE_LENGTH], raw[_NONCE_LENGTH:]
    aesgcm = AESGCM(_derive_aes_key(master_key))
    return aesgcm.decrypt(nonce, ciphertext, None).decode("utf-8")
