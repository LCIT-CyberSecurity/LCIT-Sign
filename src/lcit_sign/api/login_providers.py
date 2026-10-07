"""Administration > Connexion: the Microsoft and Google sign-in buttons, set up by hand. The
client secret is encrypted with the master key and never returned."""
from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DbSession

from lcit_sign.deps import get_db, require_roles
from lcit_sign.models.login_provider import LoginProvider
from lcit_sign.models.user import Role, User
from lcit_sign.services.audit import append_audit_event
from lcit_sign.services.crypto import encrypt_secret

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


def _redirect_uri(request: Request) -> str:
    base: str = request.app.state.settings.public_base_url
    return base.rstrip("/") + "/api/auth/callback"


def _payload(provider: str, row: LoginProvider | None, request: Request) -> dict[str, Any]:
    return {
        "provider": provider,
        "configured": row is not None,
        "client_id": row.client_id if row else "",
        "tenant_id": (row.tenant_id or "") if row else "",
        "updated_at": row.updated_at.isoformat() if row and row.updated_at else None,
        # To register on the provider's side.
        "redirect_uri": _redirect_uri(request),
    }


@router.get("")
def list_providers(
    request: Request, db: DbSession = Depends(get_db), user: User = Depends(_admin)
) -> list[dict[str, Any]]:
    return [_payload(p, db.get(LoginProvider, p), request) for p in PROVIDERS]


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
