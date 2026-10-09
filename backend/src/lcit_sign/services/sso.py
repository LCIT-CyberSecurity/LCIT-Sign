"""The one external sign-in the login page offers (next to the local form).

It is an OpenID Connect provider, and exactly one is in use, chosen without any hidden priority:
  1. when the LCIT_SIGN_OIDC_* variables are set, they ARE the SSO ("sso"; "test" on CrashTest,
     where they point at the mock SSO). Administration > Connexion says so;
  2. otherwise the provider an administrator marked active under Administration > Identités &
     accès ("entra" or "google"), its secret stored encrypted in the database.
Several can be configured; only the active one is offered.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from lcit_sign.config import Settings
from lcit_sign.models.login_provider import LoginProvider
from lcit_sign.services.crypto import decrypt_secret

GOOGLE_ISSUER = "https://accounts.google.com"


def entra_issuer(tenant: str) -> str:
    return f"https://login.microsoftonline.com/{tenant}/v2.0"


def callback_path(key: str) -> str:
    """The return address the provider is told: Microsoft Entra ID has its own (an Entra
    application often already has /api/auth/callback registered as a single-page app, which Entra
    refuses to mix with a secret); every other sign-in keeps the historical one."""
    return "/api/auth/callback/entra" if key == "entra" else "/api/auth/callback"


@dataclass(frozen=True)
class SsoConfig:
    key: str  # entra | google | sso | test
    issuer: str
    client_id: str
    client_secret: str
    provider: str  # entra | google | generic: the logo and the wording


def _kind_of(settings: Settings, issuer: str) -> str:
    if settings.oidc_provider:
        return settings.oidc_provider
    host = (urlparse(issuer).hostname or "").lower()
    if host in ("login.microsoftonline.com", "sts.windows.net"):
        return "entra"
    if host == "accounts.google.com":
        return "google"
    return "generic"


def _from_environment(settings: Settings) -> SsoConfig | None:
    if not (settings.oidc_issuer and settings.oidc_client_id and settings.oidc_client_secret):
        return None
    return SsoConfig(
        "test" if settings.crashtest else "sso",
        settings.oidc_issuer, settings.oidc_client_id, settings.oidc_client_secret,
        _kind_of(settings, settings.oidc_issuer),
    )


def _from_database(db: Session, settings: Settings) -> SsoConfig | None:
    if not settings.master_key:
        return None
    try:
        row = db.execute(
            select(LoginProvider).where(LoginProvider.active.is_(True))
        ).scalars().first()
    except SQLAlchemyError:  # no table yet (first start)
        return None
    if row is None:
        return None
    try:
        secret = decrypt_secret(settings.master_key, row.encrypted_secret)
    except Exception:  # noqa: BLE001 - unreadable (another master key): no button
        return None
    if row.provider == "entra" and row.tenant_id:
        return SsoConfig("entra", entra_issuer(row.tenant_id), row.client_id, secret, "entra")
    if row.provider == "google":
        return SsoConfig("google", GOOGLE_ISSUER, row.client_id, secret, "google")
    return None


def environment_sso(settings: Settings) -> SsoConfig | None:
    """The SSO imposed by the LCIT_SIGN_OIDC_* variables, if they are set."""
    return _from_environment(settings)


def available_sso(db: Session | None, settings: Settings) -> list[SsoConfig]:
    """The SSO in use: zero or one. The environment's, when set; else the active provider."""
    env = _from_environment(settings)
    if env is not None:
        return [env]
    configured = _from_database(db, settings) if db is not None else None
    return [configured] if configured else []


def resolve_sso(db: Session | None, settings: Settings, key: str | None = None) -> SsoConfig | None:
    """The SSO in use, or None; a named provider that is no longer the one in use is refused."""
    choices = available_sso(db, settings)
    if key is None:
        return choices[0] if choices else None
    return next((c for c in choices if c.key == key), None)
