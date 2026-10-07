"""The sign-in buttons the login page offers.

Each one is an OpenID Connect provider:
  * "entra" and "google": set up by an administrator under Administration > Connexion, the secret
    stored encrypted in the database (nothing in Git, nothing in the environment);
  * "sso": the single provider given by the LCIT_SIGN_OIDC_* variables, for installations that
    prefer configuring it that way;
  * "test": on the CrashTest stack, the same variables point at the mock SSO (fictional people).
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


def _from_database(db: Session, settings: Settings) -> list[SsoConfig]:
    if not settings.master_key:
        return []
    try:
        rows = db.execute(select(LoginProvider).order_by(LoginProvider.provider)).scalars().all()
    except SQLAlchemyError:  # no table yet (first start)
        return []
    found: dict[str, SsoConfig] = {}
    for row in rows:
        try:
            secret = decrypt_secret(settings.master_key, row.encrypted_secret)
        except Exception:  # noqa: S112 - unreadable (another master key): no button
            continue
        if row.provider == "entra" and row.tenant_id:
            found["entra"] = SsoConfig(
                "entra", entra_issuer(row.tenant_id), row.client_id, secret, "entra"
            )
        elif row.provider == "google":
            found["google"] = SsoConfig("google", GOOGLE_ISSUER, row.client_id, secret, "google")
    return [found[k] for k in ("entra", "google") if k in found]


def available_sso(db: Session | None, settings: Settings) -> list[SsoConfig]:
    """The buttons, in display order: Microsoft, Google, then the environment's provider."""
    configured = _from_database(db, settings) if db is not None else []
    env = _from_environment(settings)
    return [*configured, *([env] if env else [])]


def resolve_sso(db: Session | None, settings: Settings, key: str | None = None) -> SsoConfig | None:
    """The provider asked for, or the first one when none is named."""
    choices = available_sso(db, settings)
    if key is None:
        return choices[0] if choices else None
    return next((c for c in choices if c.key == key), None)
