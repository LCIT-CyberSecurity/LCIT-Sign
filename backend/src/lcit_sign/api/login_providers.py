"""Administration > Connexion: the Microsoft and Google sign-in buttons, set up by hand. The
client secret is encrypted with the master key and never returned."""
from __future__ import annotations

import re
from collections.abc import Generator
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import update
from sqlalchemy.orm import Session as DbSession

from lcit_sign.deps import get_db, require_roles
from lcit_sign.models.login_provider import LoginProvider
from lcit_sign.models.user import Role, User
from lcit_sign.services import login_diagnostics
from lcit_sign.services.audit import append_audit_event
from lcit_sign.services.crypto import decrypt_secret, encrypt_secret
from lcit_sign.services.directory import diagnostics
from lcit_sign.services.sso import callback_path, environment_sso

router = APIRouter(prefix="/admin/login-providers", tags=["login"])
_admin = require_roles(Role.ADMIN)

PROVIDERS = ("entra", "google")
_GUID = re.compile(r"^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
_DOMAIN = re.compile(r"^[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


class ProviderRequest(BaseModel):
    client_id: str = Field(min_length=1, max_length=255)
    tenant_id: str | None = Field(default=None, max_length=255)
    # Optional when one is already stored (change the ID without retyping the secret).
    client_secret: str | None = Field(default=None, max_length=2000)


def _redirect_uri(request: Request, provider: str) -> str:
    base: str = request.app.state.settings.public_base_url
    return base.rstrip("/") + callback_path(provider)


def _payload(provider: str, row: LoginProvider | None, request: Request) -> dict[str, Any]:
    return {
        "provider": provider,
        "configured": row is not None,
        "active": bool(row and row.active),
        "client_id": row.client_id if row else "",
        "tenant_id": (row.tenant_id or "") if row else "",
        "updated_at": row.updated_at.isoformat() if row and row.updated_at else None,
        # To register on the provider's side.
        "redirect_uri": _redirect_uri(request, provider),
    }


@router.get("")
def list_providers(
    request: Request, db: DbSession = Depends(get_db), user: User = Depends(_admin)
) -> list[dict[str, Any]]:
    return [_payload(p, db.get(LoginProvider, p), request) for p in PROVIDERS]


@router.get("/status")
def status_of_sso(request: Request, user: User = Depends(_admin)) -> dict[str, Any]:
    """Who decides the SSO: the environment variables when set (they win, visibly), else the
    active provider below."""
    env = environment_sso(request.app.state.settings)
    return {
        "managed_by_environment": env is not None,
        "environment_kind": env.provider if env else None,
    }


def _make_active(db: DbSession, provider: str) -> None:
    db.execute(update(LoginProvider).where(LoginProvider.provider != provider).values(active=False))
    row = db.get(LoginProvider, provider)
    if row is not None:
        row.active = True


@router.post("/{provider}/activate")
def activate_provider(
    provider: str,
    request: Request,
    db: DbSession = Depends(get_db),
    user: User = Depends(_admin),
) -> dict[str, Any]:
    """Switch the sign-in to an already configured provider; the other one stops being offered."""
    row = db.get(LoginProvider, provider) if provider in PROVIDERS else None
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not configured")
    _make_active(db, provider)
    append_audit_event(
        db, action="LOGIN_PROVIDER_ACTIVATED", actor_id=user.id, target_type="login_provider",
        target_id=provider,
    )
    db.commit()
    db.refresh(row)
    return _payload(provider, row, request)


@router.put("/{provider}")
def put_provider(
    provider: str,
    body: ProviderRequest,
    request: Request,
    db: DbSession = Depends(get_db),
    user: User = Depends(_admin),
) -> dict[str, Any]:
    if provider not in PROVIDERS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown provider")
    settings = request.app.state.settings
    if not settings.master_key:
        raise HTTPException(503, "LCIT_SIGN_MASTER_KEY is not configured")
    client_id = body.client_id.strip()
    tenant = (body.tenant_id or "").strip()
    secret = (body.client_secret or "").strip()
    if provider == "entra":
        if not (_GUID.match(tenant) or _DOMAIN.match(tenant)):
            raise HTTPException(
                422, "L'ID du tenant doit ressembler à 73405479-f042-45d7-8149-c90341261b65"
            )
        if not _GUID.match(client_id):
            raise HTTPException(
                422, "L'ID de l'application (client) a la forme 333a1a3e-1d45-4661-…"
            )
    elif not client_id.endswith(".apps.googleusercontent.com"):
        raise HTTPException(422, "L'ID client Google se termine par .apps.googleusercontent.com")
    row = db.get(LoginProvider, provider)
    if not secret and row is None:
        raise HTTPException(422, "Le secret client est à renseigner")
    if secret and (secret in (tenant, client_id) or _GUID.match(secret)):
        raise HTTPException(
            422,
            "Ceci ressemble à un identifiant, pas au secret : copiez la VALEUR du secret client "
            "(visible une seule fois à sa création), pas son ID.",
        )
    if row is None:
        row = LoginProvider(provider=provider, client_id=client_id, encrypted_secret="")
        db.add(row)
    row.client_id = client_id
    row.tenant_id = tenant or None
    row.updated_by = user.id
    if secret:
        row.encrypted_secret = encrypt_secret(settings.master_key, secret)
    # One sign-in provider at a time: the one just saved is the one in use.
    db.flush()
    _make_active(db, provider)
    append_audit_event(
        db, action="LOGIN_PROVIDER_CONFIGURED", actor_id=user.id, target_type="login_provider",
        target_id=provider,
    )
    db.commit()
    db.refresh(row)
    return _payload(provider, row, request)


@router.delete("/{provider}", status_code=status.HTTP_204_NO_CONTENT)
def delete_provider(
    provider: str, db: DbSession = Depends(get_db), user: User = Depends(_admin)
) -> Response:
    row = db.get(LoginProvider, provider) if provider in PROVIDERS else None
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not configured")
    db.delete(row)
    append_audit_event(
        db, action="LOGIN_PROVIDER_REMOVED", actor_id=user.id, target_type="login_provider",
        target_id=provider,
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def get_login_http_client() -> Generator[httpx.Client]:
    # A dependency so tests can swap in a mock transport.
    with httpx.Client(timeout=30.0) as client:
        yield client


@router.post("/{provider}/test")
def test_provider(
    provider: str,
    request: Request,
    db: DbSession = Depends(get_db),
    http_client: httpx.Client = Depends(get_login_http_client),
    user: User = Depends(_admin),
) -> dict[str, Any]:
    """Check the saved provider against the provider itself: reachable, and the application
    identifiers and secret accepted. Read-only: nobody signs in, nothing is stored but the audit
    line. The redirect address cannot be checked without a real sign-in."""
    if provider not in PROVIDERS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown provider")
    row = db.get(LoginProvider, provider)
    settings = request.app.state.settings
    if row is None or not row.encrypted_secret:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ce fournisseur n'est pas configuré.")
    try:
        secret = decrypt_secret(settings.master_key, row.encrypted_secret)
    except Exception:  # an unreadable secret: a different master key, a damaged value
        checks = [
            diagnostics.fail(
                "configuration", diagnostics.INVALID_CONFIGURATION,
                "Le secret enregistré est illisible.",
                action="Enregistrez à nouveau le secret client.",
            )
        ]
    else:
        if provider == "entra":
            checks = login_diagnostics.test_entra(
                http_client, row.tenant_id or "", row.client_id, secret
            )
        else:
            checks = login_diagnostics.test_google(
                http_client, row.client_id, secret, _redirect_uri(request, provider)
            )
    for check in checks:
        diagnostics.log_check(f"login:{provider}", check)
    result = diagnostics.result_payload(provider, checks)
    first_problem = next((c for c in checks if c.status != diagnostics.OK), None)
    append_audit_event(
        db, action="LOGIN_PROVIDER_TESTED", actor_id=user.id, target_type="login_provider",
        target_id=provider,
        metadata={
            "provider": provider,
            "status": result["status"],
            "error_code": first_problem.code if first_problem else None,
            "provider_code": first_problem.provider_code if first_problem else None,
        },
    )
    db.commit()
    return result
