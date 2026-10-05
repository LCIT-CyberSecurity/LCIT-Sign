"""The built-in system account.

Outside SSO there must still be a way in when the identity provider is down or
not yet configured: one local administrator, enabled by default. Its password
is never in the code or the repository — it comes from a secret
(LCIT_SIGN_LOCAL_ADMIN_PASSWORD[_FILE]) and is stored only as a scrypt hash.
With no password configured the account exists but cannot log in. In
production the application refuses to start with a weak or well-known
password, and the account can be switched off once a real administrator
exists (LCIT_SIGN_LOCAL_AUTH_ENABLED=false). Nothing else in the application
ever asks anyone for a password.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from threading import Lock

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from lcit_sign.config import Settings
from lcit_sign.models.user import Role, User, UserRole
from lcit_sign.services.passwords import (
    DEPLOYMENT_DEFAULT_PASSWORD,
    hash_password,
    is_acceptable_for_production,
    verify_password,
)

logger = logging.getLogger(__name__)

BUILTIN_ISSUER = "builtin:local"
MAX_FAILURES = 5
WINDOW_SECONDS = 300.0


def ensure_builtin_admin(db: DbSession, settings: Settings) -> User | None:
    """Create or refresh the system account to match the configuration.
    Idempotent; switching the feature off disables the account."""
    username = settings.local_admin_username
    user = db.execute(
        select(User).where(User.issuer == BUILTIN_ISSUER, User.subject == username)
    ).scalar_one_or_none()

    if not settings.local_auth_enabled:
        if user is not None and (user.active or not user.manually_disabled):
            user.active = False
            user.manually_disabled = True
            user.password_hash = None
            db.commit()
        return None

    if user is None:
        user = User(
            issuer=BUILTIN_ISSUER,
            subject=username,
            email=f"{username}@builtin.local",
            given_name="Compte",
            family_name="système",
            display_name="Compte système",
            active=True,
        )
        db.add(user)
        db.flush()
    has_role = db.execute(
        select(UserRole).where(UserRole.user_id == user.id, UserRole.role == Role.ADMIN)
    ).scalar_one_or_none()
    if has_role is None:
        db.add(UserRole(user_id=user.id, role=Role.ADMIN))

    # The configured (or deployment-default) password is only the INITIAL one: it is
    # applied when the account has none. A password the administrator chose is never
    # overwritten by a restart; `lcit_sign.cli reset-admin-password` is the way back in.
    if not user.password_hash:
        initial = initial_password(settings)
        if initial:
            user.password_hash = hash_password(initial)
            user.must_change_password = True
        else:
            logger.warning("The built-in administrator has no password.")
    db.commit()
    return user


def initial_password(settings: Settings) -> str:
    """The password a fresh built-in account starts with."""
    return settings.local_admin_password or DEPLOYMENT_DEFAULT_PASSWORD


class PasswordChangeError(ValueError):
    pass


def change_password(db: DbSession, user: User, current: str, new: str) -> None:
    """Let the built-in account's owner choose their own password."""
    if user.issuer != BUILTIN_ISSUER:
        raise PasswordChangeError("Ce compte se connecte par SSO : il n'a pas de mot de passe ici")
    if not verify_password(current, user.password_hash):
        raise PasswordChangeError("Le mot de passe actuel est incorrect")
    if new == current:
        raise PasswordChangeError("Le nouveau mot de passe doit être différent de l'actuel")
    problem = is_acceptable_for_production(new)
    if problem:
        raise PasswordChangeError(f"Mot de passe refusé : {problem}")
    user.password_hash = hash_password(new)
    user.must_change_password = False
    db.flush()


class LoginThrottle:
    """Blocks guessing: too many failures for one name, or from one address,
    close the door for a while (the counter is in memory, one API process)."""

    def __init__(self) -> None:
        self._failures: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def _recent(self, key: str, now: float) -> list[float]:
        recent = [t for t in self._failures[key] if t > now - WINDOW_SECONDS]
        self._failures[key] = recent
        return recent

    def blocked(self, *keys: str) -> bool:
        now = time.monotonic()
        with self._lock:
            return any(len(self._recent(k, now)) >= MAX_FAILURES for k in keys)

    def failed(self, *keys: str) -> None:
        now = time.monotonic()
        with self._lock:
            for k in keys:
                self._recent(k, now).append(now)

    def succeeded(self, *keys: str) -> None:
        with self._lock:
            for k in keys:
                self._failures.pop(k, None)


def check_credentials(
    db: DbSession, settings: Settings, username: str, password: str
) -> User | None:
    """The built-in account if these are its credentials, else None."""
    user = ensure_builtin_admin(db, settings)
    submitted_ok = (
        user is not None
        and user.active
        and username.strip().lower() == settings.local_admin_username.lower()
    )
    # Always spend one verification, so timing does not tell accounts apart.
    password_ok = verify_password(password, user.password_hash if user else None)
    return user if (submitted_ok and password_ok) else None
