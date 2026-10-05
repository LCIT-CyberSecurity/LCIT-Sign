from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, sourced only from the environment.

    Every field is prefixed LCIT_SIGN_ so the application never guesses at an
    ambient variable meant for something else sharing the same host.
    """

    model_config = SettingsConfigDict(env_prefix="LCIT_SIGN_", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    database_url: str = "postgresql+psycopg://lcit_sign:lcit_sign@localhost:5432/lcit_sign"
    log_level: str = "INFO"
    cors_allowed_origins: list[str] = []

    # Signs the short-lived login-flow cookie (state/nonce/PKCE verifier).
    # Not the same key space as the audit/evidence signing key (Phase 3).
    session_secret: str = "insecure-dev-secret-change-me"  # noqa: S105
    # False only for plain-http local development; nginx/TLS terminates in
    # every other deployment, so this must be true anywhere real.
    cookie_secure: bool = True
    session_idle_timeout_minutes: int = 60
    session_absolute_timeout_hours: int = 12

    # Generic OIDC Authorization Code + PKCE provider. Left empty, auth
    # endpoints return a clear configuration error rather than failing open.
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    # Public base URL this app is reachable at, used to build the
    # OIDC redirect_uri (e.g. https://sign.example.org).
    public_base_url: str = "http://localhost:8000"

    # Email (case-insensitive) granted ADMIN on every login while set.
    # Unset it once a real administrator has taken over the account.
    bootstrap_admin: str = ""

    # Persistent filesystem root (spec §8) — never PostgreSQL, never S3/MinIO.
    storage_root: str = "/var/lib/lcit-sign"
    max_upload_size_mb: int = 25


@lru_cache
def get_settings() -> Settings:
    return Settings()
