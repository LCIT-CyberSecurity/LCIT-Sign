from __future__ import annotations

from collections.abc import Callable, Generator
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from lcit_sign.auth.cookies import SESSION_COOKIE, hash_session_token
from lcit_sign.config import Settings
from lcit_sign.models.session import Session as SessionRecord
from lcit_sign.models.user import Role, User, UserRole
from lcit_sign.time_utils import ensure_utc


def get_db(request: Request) -> Generator[DbSession]:
    session_factory = request.app.state.session_factory
    db = session_factory()
    try:
        yield db
    finally:
        db.close()


def get_current_session(request: Request, db: DbSession = Depends(get_db)) -> SessionRecord:
    raw_token = request.cookies.get(SESSION_COOKIE)
    if not raw_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

    token_hash = hash_session_token(raw_token)
    session = db.execute(
        select(SessionRecord).where(SessionRecord.session_token_hash == token_hash)
    ).scalar_one_or_none()

    now = datetime.now(UTC)
    settings: Settings = request.app.state.settings
    idle_cutoff = now - timedelta(minutes=settings.session_idle_timeout_minutes)

    if (
        session is None
        or session.revoked_at is not None
        or ensure_utc(session.expires_at) < now
        or ensure_utc(session.last_activity_at) < idle_cutoff
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired or invalid")

    session.last_activity_at = now
    db.flush()
    return session


def get_current_user(
    session: SessionRecord = Depends(get_current_session), db: DbSession = Depends(get_db)
) -> User:
    user = db.get(User, session.user_id)
    if user is None or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")
    return user


def user_roles(db: DbSession, user: User) -> set[Role]:
    rows = db.execute(select(UserRole.role).where(UserRole.user_id == user.id)).scalars()
    return set(rows)


def require_roles(*allowed_roles: Role) -> Callable[..., User]:
    """Backend-enforced RBAC gate (spec §14): deny unless the user holds at
    least one of the given roles. There is no implicit role hierarchy — an
    OPERATOR never passes an ADMIN-only gate without also holding ADMIN.
    """

    def dependency(
        user: User = Depends(get_current_user), db: DbSession = Depends(get_db)
    ) -> User:
        if not user_roles(db, user) & set(allowed_roles):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")
        return user

    return dependency
