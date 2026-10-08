from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Values shipped for development, CrashTest or as examples: public, so refused in production.
MIN_SECRET = 32  # production only: shortest accepted session secret / master key
_PLACEHOLDER = "change-me-to-a-long-random-value"
DEV_SESSION_SECRETS = frozenset({
    "", "insecure-dev-secret-change-me", "dev-only-insecure-secret-change-me",
    "crashtest-only-session-secret", _PLACEHOLDER,
})
DEV_MASTER_KEYS = frozenset({
    "", "dev-only-insecure-master-key-change-me", "crashtest-only-master-key-not-a-secret",
    _PLACEHOLDER,
})


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
    # True only on the throwaway CrashTest stack (crashtest/): the fictional dataset may be loaded
    # and the sign-in page says so. Never set on a real installation.
    crashtest: bool = False
    # Only the look of the sign-in button (logo and wording): the engine is always generic OIDC.
    # Left empty, it is read from the issuer address (Microsoft, Google) and is "generic" otherwise.
    oidc_provider: Literal["", "entra", "google", "generic"] = ""
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    # Public base URL this app is reachable at, used to build the
    # OIDC redirect_uri (e.g. https://sign.example.org).
    public_base_url: str = "http://localhost:8000"

    # The built-in system account (spec: SSO is the only way in for people; this is
    # the one exception). On by default.
    local_auth_enabled: bool = True
    local_admin_username: str = "admin"
    # Initial password of the built-in account. Empty means the documented, public initial
    # password "SecretPassword" (the local administrator must change it: they are reminded at
    # every sign-in until they do). Set it to deploy with something else.
    local_admin_password: str = ""  # noqa: S105

    # Email (case-insensitive) granted ADMIN on every login while set.
    # Unset it once a real administrator has taken over the account.
    bootstrap_admin: str = ""

    # Persistent filesystem root (spec §8) — never PostgreSQL, never S3/MinIO.
    storage_root: str = "/var/lib/lcit-sign"
    max_upload_size_mb: int = 25
    # The isolated converter for Word / LibreOffice files (empty = only PDFs are accepted).
    converter_url: str = ""
    converter_timeout_seconds: int = 90

    # The time zone people live in. "Today's date" and the time stamped on a
    # document follow it; stored timestamps stay UTC.
    timezone: str = "Europe/Paris"

    # Runtime-only secret (spec §64-65, §101): every signing key's Ed25519
    # seed is derived from this via HKDF and a key_id, so the private key
    # material itself is never persisted anywhere, in Postgres or on disk.
    master_key: str = ""  # noqa: S105
    consent_text: str = "J'atteste avoir pris connaissance de ce document."
    consent_version: str = "1.0"

    # Background notification worker (spec §151-152: a plain PostgreSQL-
    # backed worker, no Redis/Celery). Disabled by default in tests via
    # make_app() overrides, so test runs don't race the queue table before
    # Base.metadata.create_all() has run.
    notification_worker_enabled: bool = True
    notification_worker_interval_seconds: int = 30
    rate_limit_enabled: bool = True

    # Docker/Kubernetes secrets: LCIT_SIGN_<NAME>_FILE points at a file whose
    # content is the secret, so it never has to sit in an environment
    # variable or a .env file. When set, it wins over the plain variable.
    session_secret_file: str = ""
    oidc_client_secret_file: str = ""
    master_key_file: str = ""
    local_admin_password_file: str = ""

    @model_validator(mode="after")
    def _load_secret_files(self) -> Settings:
        for name in ("session_secret", "oidc_client_secret", "master_key", "local_admin_password"):
            path = getattr(self, f"{name}_file")
            if path:
                setattr(self, name, Path(path).read_text(encoding="utf-8").strip())
        return self

    @model_validator(mode="after")
    def _production_needs_real_secrets(self) -> Settings:
        """Production refuses the development values of the session secret and the master key,
        and a cookie that is not Secure. Development, test and CrashTest keep them."""
        if self.environment != "production":
            return self
        problems = []
        if self.session_secret in DEV_SESSION_SECRETS or len(self.session_secret) < MIN_SECRET:
            problems.append(
                f"LCIT_SIGN_SESSION_SECRET is empty, short (< {MIN_SECRET}) or a development value"
            )
        if self.master_key in DEV_MASTER_KEYS or len(self.master_key) < MIN_SECRET:
            problems.append(
                f"LCIT_SIGN_MASTER_KEY is empty, short (< {MIN_SECRET}) or a development value"
            )
        if not self.cookie_secure:
            problems.append("LCIT_SIGN_COOKIE_SECURE must be true")
        if problems:
            raise ValueError("Refusing to start in production: " + "; ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
