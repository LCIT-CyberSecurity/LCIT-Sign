from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from lcit_sign.auth.cookies import (
    LOGIN_FLOW_COOKIE,
    SESSION_COOKIE,
    generate_session_token,
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

router = APIRouter(tags=["auth"])


def _redirect_uri(request: Request) -> str:
    settings: Settings = request.app.state.settings
    return settings.public_base_url.rstrip("/") + "/api/auth/callback"


def _require_oidc_configured(request: Request) -> None:
    settings: Settings = request.app.state.settings
    if not (settings.oidc_issuer and settings.oidc_client_id and settings.oidc_client_secret):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "SSO is not configured")


@router.get("/auth/login")
async def login(request: Request) -> Response:
    _require_oidc_configured(request)
    settings: Settings = request.app.state.settings

    try:
        metadata = await discover_provider(settings.oidc_issuer)
    except OidcError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "SSO provider unreachable"
        ) from exc
    auth_request = build_authorization_request(
        metadata, client_id=settings.oidc_client_id, redirect_uri=_redirect_uri(request)
    )

    response = Response(status_code=status.HTTP_302_FOUND)
    response.headers["Location"] = auth_request.url
    cookie_value = sign_login_flow_cookie(
        {
            "state": auth_request.state,
            "nonce": auth_request.nonce,
            "code_verifier": auth_request.code_verifier,
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
    _require_oidc_configured(request)
    settings: Settings = request.app.state.settings

    raw_flow_cookie = request.cookies.get(LOGIN_FLOW_COOKIE)
    flow = (
        verify_login_flow_cookie(raw_flow_cookie, settings.session_secret)
        if raw_flow_cookie
        else None
    )

    if flow is None or flow.get("state") != state:
        append_audit_event(
            db, action="LOGIN_FAILURE", result="FAILURE",
            metadata={"reason": "invalid_or_missing_state"},
            source_ip=request.client.host if request.client else None,
        )
        db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid login state")

    try:
        metadata = await discover_provider(settings.oidc_issuer)
        claims = await exchange_code(
            metadata,
            code=code,
            redirect_uri=_redirect_uri(request),
            client_id=settings.oidc_client_id,
            client_secret=settings.oidc_client_secret,
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
    else:
        user.email = claims.email
        user.given_name = claims.given_name
        user.family_name = claims.family_name
        user.display_name = display_name
        user.last_login_at = now
    db.flush()

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
    }
