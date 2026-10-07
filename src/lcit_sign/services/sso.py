"""Which identity provider the sign-in page uses.

Normally the LCIT_SIGN_OIDC_* variables. When none are set (or on the CrashTest stack, where they
point at a mock), the Microsoft Entra application an administrator already configured under
Administration > Annuaires is used for sign-in too: same tenant, same application, secret read
from the encrypted store. The application must list /api/auth/callback as a redirect URI.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from lcit_sign.config import Settings
from lcit_sign.models.directory import DirectoryConnectorConfig
from lcit_sign.services.crypto import decrypt_secret


@dataclass(frozen=True)
class SsoConfig:
    issuer: str
    client_id: str
    client_secret: str
    provider: str


def _provider_of(settings: Settings, issuer: str) -> str:
    if settings.oidc_provider:
        return settings.oidc_provider
    host = (urlparse(issuer).hostname or "").lower()
    if host in ("login.microsoftonline.com", "sts.windows.net"):
        return "entra"
    if host == "accounts.google.com":
        return "google"
    return "generic"


def _from_directory(db: Session, settings: Settings) -> SsoConfig | None:
    if not settings.master_key:
        return None
    row = db.execute(
        select(DirectoryConnectorConfig).where(DirectoryConnectorConfig.source == "entra")
    ).scalar_one_or_none()
    if row is None or not row.encrypted_secret:
        return None
    try:
        fields = json.loads(row.settings_json)
        secret = decrypt_secret(settings.master_key, row.encrypted_secret)
    except Exception:  # unreadable store: fall back to the environment
        return None
    tenant, client = fields.get("tenant_id", "").strip(), fields.get("client_id", "").strip()
    if not (tenant and client and secret):
        return None
    return SsoConfig(
        f"https://login.microsoftonline.com/{tenant}/v2.0", client, secret, "entra"
    )


def resolve_sso(db: Session | None, settings: Settings) -> SsoConfig | None:
    env = None
    if settings.oidc_issuer and settings.oidc_client_id and settings.oidc_client_secret:
        env = SsoConfig(
            settings.oidc_issuer, settings.oidc_client_id, settings.oidc_client_secret,
            _provider_of(settings, settings.oidc_issuer),
        )
    if env is None or settings.crashtest:
        return (_from_directory(db, settings) if db is not None else None) or env
    return env
