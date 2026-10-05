from __future__ import annotations

import json
import re
import uuid
from collections.abc import Generator
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from lcit_sign.deps import get_db, require_roles
from lcit_sign.models.directory import (
    DirectoryConnectorConfig,
    DirectorySyncRun,
    Group,
    GroupMembership,
)
from lcit_sign.models.user import Role, User
from lcit_sign.services.audit import append_audit_event
from lcit_sign.services.crypto import encrypt_secret
from lcit_sign.services.directory_connectors import (
    REMOTE_SOURCES,
    DirectoryConnector,
    DirectoryConnectorError,
    build_remote_connector,
)
from lcit_sign.services.directory_sync import LocalConnector, sync_directory

router = APIRouter(prefix="/admin/directory", tags=["directory"])

_admin = require_roles(Role.ADMIN)
# Reading the roster is also an OPERATOR need (picking groups to target a
# campaign at, spec §33); only mutating the directory (sync) stays
# ADMIN-only, matching spec §12-13's split of responsibilities.
_read = require_roles(Role.OPERATOR, Role.ADMIN)


def _run_payload(run: DirectorySyncRun) -> dict[str, Any]:
    return {
        "id": str(run.id),
        "source": run.source,
        "status": run.status,
        "started_at": run.started_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "users_added": run.users_added,
        "users_updated": run.users_updated,
        "users_deactivated": run.users_deactivated,
        "groups_added": run.groups_added,
        "groups_updated": run.groups_updated,
        "memberships_added": run.memberships_added,
        "memberships_removed": run.memberships_removed,
        "error": run.error,
    }


def get_directory_http_client() -> Generator[httpx.Client]:
    # A dependency so tests can swap in a mock transport.
    with httpx.Client(timeout=30.0) as client:
        yield client


def _config_payload(source: str, config: DirectoryConnectorConfig | None) -> dict[str, Any]:
    fields = json.loads(config.settings_json) if config else {}
    return {
        "source": source,
        "configured": bool(config and config.encrypted_secret),
        "fields": fields,
        "sync_interval_minutes": config.sync_interval_minutes if config else None,
        "updated_at": config.updated_at.isoformat() if config and config.updated_at else None,
    }


@router.get("/sources")
def list_sources(db: DbSession = Depends(get_db), user: User = Depends(_admin)) -> list[Any]:
    local = db.get(DirectoryConnectorConfig, "local")
    payloads: list[dict[str, Any]] = [
        {
            "source": "local",
            "configured": True,
            "fields": {},
            "sync_interval_minutes": local.sync_interval_minutes if local else None,
        }
    ]
    for source in REMOTE_SOURCES:
        payloads.append(_config_payload(source, db.get(DirectoryConnectorConfig, source)))
    return payloads


class ConnectorConfigRequest(BaseModel):
    fields: dict[str, str] = {}
    # The single secret (Entra client secret / Google service-account JSON).
    # Omitted keeps the stored ciphertext; the API never returns it.
    secret: str | None = None
    # Run this source automatically every N minutes (None = manual only).
    sync_interval_minutes: int | None = Field(default=None, ge=5, le=10080)


_GUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_DOMAIN = re.compile(r"^(?=.{4,253}$)([A-Za-z0-9-]+\.)+[A-Za-z]{2,}$")


def check_connector_input(source: str, fields: dict[str, str], secret: str | None) -> None:
    """Catch the classic mix-ups at the moment of typing, in words that say what
    to do — a wrong value would otherwise only surface later as a refusal from
    Microsoft or Google. Raises HTTPException(422)."""

    def refuse(message: str) -> None:
        raise HTTPException(status_code=422, detail=message)

    if source == "entra":
        tenant, client = fields.get("tenant_id", "").strip(), fields.get("client_id", "").strip()
        if not (_GUID.match(tenant) or _DOMAIN.match(tenant)):
            refuse(
                "L'ID du tenant doit ressembler à 73405479-f042-45d7-8149-c90341261b65 "
                "(Entra → Vue d'ensemble → ID de locataire) ou à votre domaine "
                "(entreprise.onmicrosoft.com)."
            )
        if "~" in client:
            refuse(
                "Ce qui est saisi dans « ID de l'application (client) » ressemble à un "
                "secret : le secret va dans le champ « Secret client »."
            )
        if not _GUID.match(client):
            refuse(
                "L'ID de l'application (client) doit être un code du type "
                "9a8b7c6d-5e4f-4321-b0a9-8c7d6e5f4a3b : page « Vue d'ensemble » de l'application "
                "dans Entra, ligne « ID de l'application (client) »."
            )
        if secret is not None:
            if _GUID.match(secret.strip()):
                refuse(
                    "Ceci est un identifiant (ID de secret ou de l'application), pas la valeur du "
                    "secret. Dans Entra → Certificats et secrets, copiez la colonne « Valeur » "
                    "(une suite d'environ 40 caractères avec un « ~ »)."
                )
            if secret.strip() in (tenant, client):
                refuse("Le secret client ne peut pas être identique à un des identifiants.")
    elif source == "google":
        if "@" not in fields.get("admin_email", ""):
            refuse("L'e-mail de l'administrateur doit être une adresse (admin@votre-domaine.fr).")
        if secret is not None:
            try:
                key = json.loads(secret)
                valid = isinstance(key, dict) and "client_email" in key and "private_key" in key
            except ValueError:
                valid = False
            if not valid:
                refuse(
                    "La clé du compte de service doit être le fichier JSON téléchargé "
                    "depuis Google Cloud (« client_email » et « private_key »)."
                )


@router.put("/sources/{source}/config")
def put_source_config(
    source: str,
    body: ConnectorConfigRequest,
    request: Request,
    db: DbSession = Depends(get_db),
    user: User = Depends(_admin),
) -> dict[str, Any]:
    if source != "local" and source not in REMOTE_SOURCES:
        raise HTTPException(status_code=404, detail=f"unknown directory source {source!r}")
    # `local` has no credentials: its row only carries the sync schedule.
    allowed_fields = REMOTE_SOURCES[source][0] if source in REMOTE_SOURCES else ()
    unknown = set(body.fields) - set(allowed_fields)
    if unknown:
        raise HTTPException(status_code=422, detail=f"unknown fields: {sorted(unknown)}")
    check_connector_input(source, body.fields, body.secret)
    config = db.get(DirectoryConnectorConfig, source)
    if config is None:
        config = DirectoryConnectorConfig(source=source)
        db.add(config)
    config.settings_json = json.dumps(body.fields)
    config.sync_interval_minutes = body.sync_interval_minutes
    config.updated_by = user.id
    if body.secret and source == "local":
        raise HTTPException(status_code=422, detail="the local directory has no secret")
    if body.secret:
        master_key = request.app.state.settings.master_key
        if not master_key:
            raise HTTPException(503, "LCIT_SIGN_MASTER_KEY is not configured")
        config.encrypted_secret = encrypt_secret(master_key, body.secret)
    append_audit_event(
        db, action="DIRECTORY_CONNECTOR_CONFIGURED", actor_id=user.id,
        target_type="directory_connector", target_id=source,
    )
    db.commit()
    db.refresh(config)
    return _config_payload(source, config)


@router.delete("/sources/{source}/config", status_code=204)
def delete_source_config(
    source: str, db: DbSession = Depends(get_db), user: User = Depends(_admin)
) -> None:
    config = db.get(DirectoryConnectorConfig, source)
    if config is not None:
        db.delete(config)
        append_audit_event(
            db, action="DIRECTORY_CONNECTOR_REMOVED", actor_id=user.id,
            target_type="directory_connector", target_id=source,
        )
        db.commit()


@router.post("/sync")
def trigger_sync(
    request: Request,
    source: str = "local",
    db: DbSession = Depends(get_db),
    http_client: httpx.Client = Depends(get_directory_http_client),
    user: User = Depends(_admin),
) -> dict[str, Any]:
    connector: DirectoryConnector
    if source == "local":
        connector = LocalConnector()
    elif source in REMOTE_SOURCES:
        config = db.get(DirectoryConnectorConfig, source)
        if config is None:
            raise HTTPException(status_code=409, detail=f"connector {source!r} is not configured")
        try:
            connector = build_remote_connector(
                config, request.app.state.settings.master_key, http_client
            )
        except DirectoryConnectorError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    else:
        raise HTTPException(status_code=404, detail=f"unknown directory source {source!r}")
    append_audit_event(
        db, action="DIRECTORY_SYNC_STARTED", actor_id=user.id, metadata={"source": source}
    )
    db.commit()
    return _run_payload(sync_directory(db, connector))


@router.get("/sync-runs")
def list_sync_runs(
    db: DbSession = Depends(get_db), user: User = Depends(_admin)
) -> list[dict[str, Any]]:
    stmt = select(DirectorySyncRun).order_by(DirectorySyncRun.started_at.desc())
    runs = db.execute(stmt).scalars()
    return [_run_payload(r) for r in runs]


@router.get("/groups")
def list_groups(
    db: DbSession = Depends(get_db), user: User = Depends(_read)
) -> list[dict[str, Any]]:
    counts = dict(
        db.execute(
            select(GroupMembership.group_id, func.count()).group_by(GroupMembership.group_id)
        ).all()
    )
    groups = db.execute(select(Group).order_by(Group.name)).scalars()
    return [
        {
            "id": str(g.id),
            "source": g.source,
            "name": g.name,
            "description": g.description,
            "active": g.active,
            "member_count": counts.get(g.id, 0),
        }
        for g in groups
    ]


@router.get("/groups/{group_id}/members")
def list_group_members(
    group_id: uuid.UUID, db: DbSession = Depends(get_db), user: User = Depends(_read)
) -> list[dict[str, Any]]:
    rows = db.execute(
        select(User)
        .join(GroupMembership, GroupMembership.user_id == User.id)
        .where(GroupMembership.group_id == group_id)
        .order_by(User.email)
    ).scalars()
    return [
        {"id": str(u.id), "email": u.email, "display_name": u.display_name, "active": u.active}
        for u in rows
    ]
