from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from lcit_sign import __version__
from lcit_sign.config import Settings
from lcit_sign.database import database_is_ready
from lcit_sign.deps import get_db, require_roles
from lcit_sign.models.directory import DirectorySyncRun
from lcit_sign.models.mail import MailConnector, Notification, NotificationStatus
from lcit_sign.models.signing_key import SigningKey, SigningKeyStatus
from lcit_sign.models.user import Role, User
from lcit_sign.services.signing_keys import derive_private_key, public_key_hex
from lcit_sign.time_utils import ensure_utc

router = APIRouter(
    prefix="/admin", tags=["diagnostics"], dependencies=[Depends(require_roles(Role.ADMIN))]
)

OK, WARN, ERROR, DISABLED = "OK", "WARN", "ERROR", "DISABLED"


def _check(name: str, status: str, detail: str = "") -> dict[str, str]:
    # `detail` is written by this module from fixed phrases and counters
    # only — never from a setting value or an upstream error body — so a
    # diagnostics page cannot leak a secret (spec §117).
    return {"name": name, "status": status, "detail": detail}


def _filesystem(settings: Settings) -> dict[str, str]:
    from pathlib import Path

    root = Path(settings.storage_root)
    probe = root / ".diagnostics" / f"{uuid.uuid4().hex}.tmp"
    try:
        probe.parent.mkdir(parents=True, exist_ok=True)
        probe.write_bytes(b"ok")
        ok = probe.read_bytes() == b"ok"
        probe.unlink()
    except OSError:
        return _check("filesystem", ERROR, "storage root is not writable")
    return _check("filesystem", OK if ok else ERROR, "read/write test")


def _signing_key(db: DbSession, settings: Settings) -> dict[str, str]:
    if not settings.master_key:
        return _check("signing_key", ERROR, "master key is not configured")
    key = db.execute(
        select(SigningKey).where(SigningKey.status == SigningKeyStatus.ACTIVE)
    ).scalar_one_or_none()
    if key is None:
        return _check("signing_key", WARN, "no active key yet (created at first signature)")
    derived = public_key_hex(derive_private_key(settings.master_key, key.key_id))
    if derived != key.public_key_hex:
        return _check("signing_key", ERROR, "master key does not match the stored signing key")
    return _check("signing_key", OK, f"active key {key.key_id}")


def _oidc(settings: Settings, client: httpx.Client) -> dict[str, str]:
    if not settings.oidc_issuer:
        return _check("oidc", ERROR, "issuer is not configured")
    url = settings.oidc_issuer.rstrip("/") + "/.well-known/openid-configuration"
    try:
        response = client.get(url, timeout=3.0, follow_redirects=False)
    except httpx.HTTPError:
        return _check("oidc", ERROR, "discovery endpoint unreachable")
    if response.status_code != 200:
        return _check("oidc", ERROR, f"discovery answered HTTP {response.status_code}")
    return _check("oidc", OK, "discovery reachable")


def _directory(db: DbSession) -> dict[str, str]:
    last = db.execute(
        select(DirectorySyncRun).order_by(DirectorySyncRun.started_at.desc()).limit(1)
    ).scalar_one_or_none()
    if last is None:
        return _check("directory", WARN, "no synchronisation has run yet")
    when = ensure_utc(last.started_at).strftime("%d/%m/%Y %H:%M UTC")
    if last.status == "SUCCESS":
        return _check("directory", OK, f"last sync {last.source} succeeded ({when})")
    return _check("directory", ERROR, f"last sync {last.source} {last.status} ({when})")


def _smtp(db: DbSession) -> dict[str, str]:
    if db.get(MailConnector, 1) is None:
        return _check("smtp", WARN, "mail connector is not configured")
    counts = dict(
        db.execute(select(Notification.status, func.count()).group_by(Notification.status)).all()
    )
    failed = counts.get(NotificationStatus.FAILED, 0)
    retry = counts.get(NotificationStatus.RETRY, 0)
    if failed or retry:
        return _check("smtp", WARN, f"{failed} failed and {retry} retrying notification(s)")
    return _check("smtp", OK, "no failed notification")


def _worker(request: Request, settings: Settings) -> dict[str, str]:
    if not settings.notification_worker_enabled:
        return _check("worker", DISABLED, "background worker is disabled")
    last = getattr(request.app.state, "worker_last_run", None)
    if last is None:
        return _check("worker", WARN, "no cycle completed yet")
    stale_after = timedelta(seconds=settings.notification_worker_interval_seconds * 3 + 30)
    if datetime.now(UTC) - last > stale_after:
        return _check("worker", ERROR, "worker has not completed a cycle recently")
    return _check("worker", OK, "last cycle completed")


def _builtin_admin(db: DbSession, settings: Settings) -> dict[str, str]:
    if not settings.local_auth_enabled:
        return _check("builtin_admin", DISABLED, "built-in administrator is switched off")
    account = db.execute(
        select(User).where(
            User.issuer == "builtin:local", User.subject == settings.local_admin_username
        )
    ).scalar_one_or_none()
    if account is None or not account.active:
        return _check("builtin_admin", OK, "built-in administrator is not in use")
    if account.must_change_password:
        level = ERROR if settings.environment == "production" else WARN
        return _check(
            "builtin_admin",
            level,
            "the initial password of the system account has not been changed",
        )
    return _check("builtin_admin", OK, "password changed")


def get_diagnostics_http_client() -> Any:
    with httpx.Client() as client:
        yield client


@router.get("/diagnostics")
def diagnostics(
    request: Request,
    db: DbSession = Depends(get_db),
    http_client: httpx.Client = Depends(get_diagnostics_http_client),
) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    checks = [
        _check("application", OK, f"version {__version__}"),
        _check(
            "database",
            OK if database_is_ready(request.app.state.engine) else ERROR,
            "SELECT 1",
        ),
        _filesystem(settings),
        _signing_key(db, settings),
        _oidc(settings, http_client),
        _directory(db),
        _smtp(db),
        _worker(request, settings),
        _builtin_admin(db, settings),
    ]
    worst = ERROR if any(c["status"] == ERROR for c in checks) else (
        WARN if any(c["status"] == WARN for c in checks) else OK
    )
    return {"status": worst, "checked_at": datetime.now(UTC).isoformat(), "checks": checks}
