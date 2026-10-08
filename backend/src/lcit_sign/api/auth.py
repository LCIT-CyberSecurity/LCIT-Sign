from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session as DbSession

from lcit_sign.auth.cookies import (
    LOGIN_FLOW_COOKIE,
    SESSION_COOKIE,
    generate_session_token,
    hash_session_token,
    sign_login_flow_cookie,
    verify_login_flow_cookie,
)
from lcit_sign.auth.oidc import (
    OidcError,
    build_authorization_request,
    discover_provider,
    exchange_code,
)
from lcit_sign.config import Settings
from lcit_sign.deps import get_current_user, get_db
from lcit_sign.models.session import Session as SessionRecord
from lcit_sign.models.user import Role, User, UserRole
from lcit_sign.services.audit import actor_snapshot, append_audit_event
from lcit_sign.services.local_auth import (
    LOCAL_ISSUER,
    LoginThrottle,
    PasswordChangeError,
    change_password,
    check_credentials,
)
from lcit_sign.services.sso import SsoConfig, available_sso, resolve_sso

router = APIRouter(tags=["auth"])


def _redirect_uri(request: Request) -> str:
    settings: Settings = request.app.state.settings
    return settings.public_base_url.rstrip("/") + "/api/auth/callback"


def _require_oidc_configured(
    db: DbSession, request: Request, provider: str | None = None
) -> SsoConfig:
    sso = resolve_sso(db, request.app.state.settings, provider)
    if sso is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "SSO is not configured")
    return sso


@router.get("/auth/login")
async def login(
    request: Request, db: DbSession = Depends(get_db), provider: str | None = None
) -> Response:
    sso = _require_oidc_configured(db, request, provider)
    settings: Settings = request.app.state.settings

    try:
        metadata = await discover_provider(sso.issuer)
    except OidcError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "SSO provider unreachable"
        ) from exc
    auth_request = build_authorization_request(
        metadata, client_id=sso.client_id, redirect_uri=_redirect_uri(request)
    )

    response = Response(status_code=status.HTTP_302_FOUND)
    response.headers["Location"] = auth_request.url
    cookie_value = sign_login_flow_cookie(
        {
            "state": auth_request.state,
            "nonce": auth_request.nonce,
            "code_verifier": auth_request.code_verifier,
            "provider": sso.key,
            "issued_at": time.time(),
        },
        settings.session_secret,
    )
    response.set_cookie(
        LOGIN_FLOW_COOKIE,
        cookie_value,
        max_age=300,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/api/auth",
    )
    return response


@router.get("/auth/callback")
async def callback(
    request: Request, code: str, state: str, db: DbSession = Depends(get_db)
) -> Response:
    settings: Settings = request.app.state.settings

    raw_flow_cookie = request.cookies.get(LOGIN_FLOW_COOKIE)
    flow = (
        verify_login_flow_cookie(raw_flow_cookie, settings.session_secret)
        if raw_flow_cookie
        else None
    )
    sso = _require_oidc_configured(db, request, flow.get("provider") if flow else None)

    if flow is None or flow.get("state") != state:
        append_audit_event(
            db, action="LOGIN_FAILURE", result="FAILURE",
            metadata={"reason": "invalid_or_missing_state"},
            source_ip=request.client.host if request.client else None,
        )
        db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid login state")

    try:
        metadata = await discover_provider(sso.issuer)
        claims = await exchange_code(
            metadata,
            code=code,
            redirect_uri=_redirect_uri(request),
            client_id=sso.client_id,
            client_secret=sso.client_secret,
            code_verifier=flow["code_verifier"],
            expected_nonce=flow["nonce"],
        )
    except OidcError:
        append_audit_event(
            db, action="LOGIN_FAILURE", result="FAILURE",
            metadata={"reason": "oidc_exchange_failed"},
            source_ip=request.client.host if request.client else None,
        )
        db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Login failed") from None

    user = db.execute(
        select(User).where(User.issuer == claims.issuer, User.subject == claims.subject)
    ).scalar_one_or_none()
    if user is None:
        # A directory sync (Phase 6) may already have provisioned this
        # person from the roster, ahead of their first login — adopt that
        # row instead of creating a duplicate (spec §20-22: SSO and the
        # directory are different sources that still name the same user).
        # (A local account an administrator created for this person is adopted the same way,
        # and keeps its password.)
        user = db.execute(
            select(User).where(
                or_(User.issuer.like("directory:%"), User.issuer == LOCAL_ISSUER),
                User.email == claims.email,
            )
        ).scalar_one_or_none()

    full_name = f"{claims.given_name} {claims.family_name}".strip()
    display_name = claims.name or full_name or claims.email
    now = datetime.now(UTC)
    if user is None:
        user = User(
            issuer=claims.issuer,
            subject=claims.subject,
            email=claims.email,
            given_name=claims.given_name,
            family_name=claims.family_name,
            display_name=display_name,
            last_login_at=now,
        )
        db.add(user)
        db.flush()
        # Everyone can sign by default; an administrator may take the role away.
        db.add(UserRole(user_id=user.id, role=Role.SIGNER))
    else:
        user.issuer = claims.issuer
        user.subject = claims.subject
        user.email = claims.email
        user.given_name = claims.given_name
        user.family_name = claims.family_name
        user.display_name = display_name
        user.last_login_at = now
    db.flush()

    if not user.active:
        append_audit_event(
            db, action="LOGIN_FAILURE", result="FAILURE", actor_id=user.id,
            metadata={"reason": "user_disabled"},
            source_ip=request.client.host if request.client else None,
        )
        db.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Ce compte est désactivé")

    if settings.bootstrap_admin and user.email.lower() == settings.bootstrap_admin.lower():
        has_admin = db.execute(
            select(UserRole).where(UserRole.user_id == user.id, UserRole.role == Role.ADMIN)
        ).scalar_one_or_none()
        if has_admin is None:
            db.add(UserRole(user_id=user.id, role=Role.ADMIN))

    raw_token, token_hash = generate_session_token()
    session = SessionRecord(
        session_token_hash=token_hash,
        user_id=user.id,
        expires_at=now + timedelta(hours=settings.session_absolute_timeout_hours),
    )
    db.add(session)

    append_audit_event(
        db,
        action="LOGIN_SUCCESS",
        actor_id=user.id,
        actor_identity_snapshot=actor_snapshot(user),
        source_ip=request.client.host if request.client else None,
    )
    db.commit()

    response = Response(status_code=status.HTTP_302_FOUND)
    response.headers["Location"] = "/"
    response.delete_cookie(LOGIN_FLOW_COOKIE, path="/api/auth")
    response.set_cookie(
        SESSION_COOKIE,
        raw_token,
        max_age=settings.session_absolute_timeout_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return response


class LocalLoginRequest(BaseModel):
    username: str
    password: str


@router.get("/auth/options")
def login_options(request: Request) -> dict[str, Any]:
    """What the sign-in page may offer: the SSO (and which provider's button), and the local
    form (the built-in administrator and the accounts an administrator gave a password to)."""
    settings: Settings = request.app.state.settings
    factory = getattr(request.app.state, "session_factory", None)
    if factory is None:  # no database (some tests): the environment only
        choices = available_sso(None, settings)
    else:
        with factory() as db:
            choices = available_sso(db, settings)
    return {
        "sso": bool(choices),
        "provider": choices[0].provider if choices else None,
        "local": settings.local_auth_enabled,
        # The CrashTest stack (fictional accounts): the sign-in page says so.
        "crashtest": settings.crashtest,
    }


@router.post("/auth/local-login")
def local_login(
    request: Request, body: LocalLoginRequest, db: DbSession = Depends(get_db)
) -> Response:
    """Sign in with a local account: the built-in administrator, or a person an administrator
    gave a password to. An account without a password (everyone who uses the SSO) never matches."""
    settings: Settings = request.app.state.settings
    if not settings.local_auth_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    ip = request.client.host if request.client else "unknown"
    name_key, ip_key = f"user:{body.username.strip().lower()[:64]}", f"ip:{ip}"
    throttle: LoginThrottle = request.app.state.login_throttle
    if throttle.blocked(name_key, ip_key):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Trop de tentatives, réessayez plus tard"
        )

    user = check_credentials(db, settings, body.username, body.password)
    if user is None:
        throttle.failed(name_key, ip_key)
        append_audit_event(
            db, action="LOGIN_FAILURE", result="FAILURE",
            metadata={
                "reason": "bad_credentials",
                "method": "local",
                "username": body.username[:64],
            },
            source_ip=ip,
        )
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Identifiant ou mot de passe incorrect")

    throttle.succeeded(name_key, ip_key)
    now = datetime.now(UTC)
    user.last_login_at = now
    raw_token, token_hash = generate_session_token()
    db.add(
        SessionRecord(
            session_token_hash=token_hash,
            user_id=user.id,
            expires_at=now + timedelta(hours=settings.session_absolute_timeout_hours),
        )
    )
    append_audit_event(
        db, action="LOGIN_SUCCESS", actor_id=user.id, actor_identity_snapshot=actor_snapshot(user),
        metadata={"method": "local", "must_change_password": user.must_change_password},
        source_ip=ip,
    )
    db.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.set_cookie(
        SESSION_COOKIE, raw_token, max_age=settings.session_absolute_timeout_hours * 3600,
        httponly=True, secure=settings.cookie_secure, samesite="lax", path="/",
    )
    return response


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/auth/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_my_password(
    request: Request,
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
) -> None:
    """The built-in account's owner sets their own password. Every other session of
    that account ends, so a leaked initial password stops working at once."""
    throttle: LoginThrottle = request.app.state.login_throttle
    key = f"change:{user.id}"
    if throttle.blocked(key):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Trop de tentatives, réessayez plus tard"
        )
    try:
        change_password(db, user, body.current_password, body.new_password)
    except PasswordChangeError as exc:
        throttle.failed(key)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    throttle.succeeded(key)

    raw = request.cookies.get(SESSION_COOKIE)
    keep = hash_session_token(raw) if raw else None
    for session in db.execute(
        select(SessionRecord).where(
            SessionRecord.user_id == user.id, SessionRecord.revoked_at.is_(None)
        )
    ).scalars():
        if session.session_token_hash != keep:
            session.revoked_at = datetime.now(UTC)
    append_audit_event(
        db, action="USER_UPDATED", actor_id=user.id, target_type="user", target_id=str(user.id),
        metadata={"change": "password_changed"},
        source_ip=request.client.host if request.client else None,
    )
    db.commit()


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, db: DbSession = Depends(get_db)) -> None:
    from lcit_sign.auth.cookies import hash_session_token

    raw_token = request.cookies.get(SESSION_COOKIE)
    if raw_token:
        token_hash = hash_session_token(raw_token)
        session = db.execute(
            select(SessionRecord).where(SessionRecord.session_token_hash == token_hash)
        ).scalar_one_or_none()
        if session and session.revoked_at is None:
            session.revoked_at = datetime.now(UTC)
            append_audit_event(db, action="LOGOUT", actor_id=session.user_id)
            db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/auth/me")
async def me(
    user: User = Depends(get_current_user), db: DbSession = Depends(get_db)
) -> dict[str, Any]:
    from lcit_sign.deps import user_roles

    roles = user_roles(db, user)
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "roles": sorted(role.value for role in roles),
        # True only for the built-in account while it still has its initial password:
        # the interface reminds its owner, at every sign-in, until it is changed.
        "must_change_password": user.must_change_password,
        # How they sign in: the built-in account, a local account (it has a password here, which
        # they may change), or the SSO alone.
        "source": (
            "builtin"
            if user.issuer.startswith("builtin:")
            else "local"
            if user.password_hash
            else "sso"
        ),
    }
