"""The directory connectors that read an outside directory, in one place."""

from __future__ import annotations

import json

import httpx

from lcit_sign.models.directory import DirectoryConnectorConfig
from lcit_sign.services.crypto import decrypt_secret
from lcit_sign.services.directory import entra, google, ldap
from lcit_sign.services.directory.base import (
    ConnectorSpec,
    DirectoryConnector,
    DirectoryConnectorError,
)

SPECS: dict[str, ConnectorSpec] = {
    spec.source: spec for spec in (entra.SPEC, google.SPEC, ldap.SPEC)
}

# Per remote source: the non-secret fields kept in clear, and the single secret kept only
# as AES-GCM ciphertext under the runtime master key.
REMOTE_SOURCES: dict[str, tuple[tuple[str, ...], str]] = {
    source: (tuple(f.name for f in spec.fields), spec.secret.name) for source, spec in SPECS.items()
}


def build_remote_connector(
    config: DirectoryConnectorConfig, master_key: str, client: httpx.Client
) -> DirectoryConnector:
    if not master_key:
        raise DirectoryConnectorError("LCIT_SIGN_MASTER_KEY is not configured")
    if not config.encrypted_secret:
        raise DirectoryConnectorError(f"connector {config.source!r} has no secret configured")
    spec = SPECS.get(config.source)
    if spec is None:
        raise DirectoryConnectorError(f"unknown directory source {config.source!r}")
    try:
        secret = decrypt_secret(master_key, config.encrypted_secret)
    except Exception as exc:  # wrong master key / corrupted ciphertext
        raise DirectoryConnectorError(f"cannot decrypt {config.source!r} secret") from exc
    fields: dict[str, str] = json.loads(config.settings_json)
    return spec.build(client, fields, secret)
