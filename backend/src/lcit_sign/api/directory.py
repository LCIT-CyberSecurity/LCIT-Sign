from __future__ import annotations

import json
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
from lcit_sign.services.directory import diagnostics
from lcit_sign.services.directory.base import DirectoryConnector, DirectoryConnectorError
from lcit_sign.services.directory.registry import (
    SPECS,
    active_source,
    available_sources,
    build_remote_connector,
    make_active,
)
from lcit_sign.services.directory_sync import LocalConnector, sync_directory

router = APIRouter(prefix="/admin/directory", tags=["directory"])

_admin = require_roles(Role.ADMIN)
# Reading the roster is also an OPERATOR need (picking groups to target a
# campaign at, spec §33); only mutating the directory (sync) stays
# ADMIN-only, matching spec §12-13's split of responsibilities.
_read = require_roles(Role.SIGNER, Role.OPERATOR, Role.ADMIN)


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
        # What a failed run says, with the provider's code and the advice when the sentence has
        # them (older runs just keep their sentence).
        "error_detail": diagnostics.explain_sync_error(run.error),
    }


def get_directory_http_client() -> Generator[httpx.Client]:
    # A dependency so tests can swap in a mock transport.
    with httpx.Client(timeout=30.0) as client:
        yield client


def _config_payload(
    source: str, config: DirectoryConnectorConfig | None, active: str | None = None
) -> dict[str, Any]:
    fields = json.loads(config.settings_json) if config else {}
    return {
        "source": source,
        "active": source == active,
        "configured": bool(config and config.encrypted_secret),
        "fields": fields,
        "sync_interval_minutes": config.sync_interval_minutes if config else None,
        "updated_at": config.updated_at.isoformat() if config and config.updated_at else None,
    }


@router.get("/sources")
def list_sources(
    request: Request, db: DbSession = Depends(get_db), user: User = Depends(_admin)
) -> list[Any]:
    settings = request.app.state.settings
    active = active_source(db, settings)
    payloads: list[dict[str, Any]] = []
    if "local" in available_sources(settings):  # CrashTest only
        local = db.get(DirectoryConnectorConfig, "local")
        payloads.append({
            "source": "local",
            "active": active == "local",
            "configured": True,
            "fields": {},
            "sync_interval_minutes": local.sync_interval_minutes if local else None,
        })
    for source, spec in SPECS.items():
        payloads.append(
            {
                **_config_payload(source, db.get(DirectoryConnectorConfig, source), active),
                # What the admin page needs to draw this connector's form, help bubbles included.
                "spec": spec.payload(),
            }
        )
    return payloads


class ConnectorConfigRequest(BaseModel):
    fields: dict[str, str] = {}
    # The single secret (Entra client secret / Google service-account JSON).
    # Omitted keeps the stored ciphertext; the API never returns it.
    secret: str | None = None
    # Run this source automatically every N minutes (None = manual only).
    sync_interval_minutes: int | None = Field(default=None, ge=5, le=10080)


@router.put("/sources/{source}/config")
def put_source_config(
    source: str,
    body: ConnectorConfigRequest,
    request: Request,
    db: DbSession = Depends(get_db),
    user: User = Depends(_admin),
) -> dict[str, Any]:
    spec = SPECS.get(source)
    if source not in available_sources(request.app.state.settings):
        raise HTTPException(status_code=404, detail=f"unknown directory source {source!r}")
    # `local` has no credentials: its row only carries the sync schedule.
    fields = body.fields
    if spec is not None:
        unknown = set(body.fields) - {f.name for f in spec.fields}
        if unknown:
            raise HTTPException(status_code=422, detail=f"unknown fields: {sorted(unknown)}")
        fields = spec.with_defaults(body.fields)
        missing = [f.label for f in spec.fields if f.required and not fields[f.name]]
        if missing:
            raise HTTPException(status_code=422, detail="À renseigner : " + ", ".join(missing))
        try:
            spec.validate(fields, body.secret)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    elif body.fields:
        raise HTTPException(status_code=422, detail="the local directory has no settings")
    config = db.get(DirectoryConnectorConfig, source)
    if config is None:
        config = DirectoryConnectorConfig(source=source)
        db.add(config)
    config.settings_json = json.dumps(fields)
    config.sync_interval_minutes = body.sync_interval_minutes
    config.updated_by = user.id
    if source != "local":
        # One directory at a time: saving a connector makes it the one in use.
        db.flush()
        make_active(db, source)
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
    return _config_payload(source, config, active_source(db, request.app.state.settings))


@router.post("/sources/{source}/activate")
def activate_source(
    source: str, request: Request, db: DbSession = Depends(get_db), user: User = Depends(_admin)
) -> dict[str, Any]:
    """Switch to another directory that is already configured (or back to the bundled one):
    only one is in use, so the others stop being synced."""
    settings = request.app.state.settings
    if source not in available_sources(settings):
        raise HTTPException(status_code=404, detail=f"unknown directory source {source!r}")
    config = db.get(DirectoryConnectorConfig, source)
    if source != "local" and (config is None or not config.encrypted_secret):
        raise HTTPException(status_code=409, detail=f"connector {source!r} is not configured")
    make_active(db, source)
    append_audit_event(
        db, action="DIRECTORY_CONNECTOR_ACTIVATED", actor_id=user.id,
        target_type="directory_connector", target_id=source,
    )
    db.commit()
    return {"source": source, "active": active_source(db, settings)}


@router.delete("/sources/{source}/config", status_code=204)
def delete_source_config(
    source: str, db: DbSession = Depends(get_db), user: User = Depends(_admin)
) -> None:
    config = db.get(DirectoryConnectorConfig, source)
    if config is not None:
        # An active connector that goes leaves no active directory (the bundled one applies).
        db.delete(config)
        append_audit_event(
            db, action="DIRECTORY_CONNECTOR_REMOVED", actor_id=user.id,
            target_type="directory_connector", target_id=source,
        )
        db.commit()


@router.post("/sources/{source}/test")
def test_source_connection(
    source: str,
    request: Request,
    db: DbSession = Depends(get_db),
    http_client: httpx.Client = Depends(get_directory_http_client),
    user: User = Depends(_admin),
) -> dict[str, Any]:
    """Check that the saved connector can really read its directory: a few read-only requests
    for one user, one group, one member. Writes nothing but the audit line, and is not a
    synchronisation (that is `/sync`)."""
    if source == "local":
        raise HTTPException(status_code=409, detail="Aucune connexion à tester pour cet annuaire.")
    if source not in SPECS:
        raise HTTPException(status_code=404, detail=f"unknown directory source {source!r}")
    config = db.get(DirectoryConnectorConfig, source)
    if config is None or not config.encrypted_secret:
        raise HTTPException(status_code=409, detail=f"connector {source!r} is not configured")
    try:
        connector = build_remote_connector(
            config, request.app.state.settings.master_key, http_client
        )
    except DirectoryConnectorError as exc:
        # The settings are saved but unusable (an unreadable key, a different master key…).
        checks = [
            diagnostics.fail(
                "configuration",
                diagnostics.INVALID_CONFIGURATION,
                "La configuration enregistrée est inutilisable : "
                + (
                    "la clé du compte de service n'est pas un JSON Google valide."
                    if source == "google"
                    else str(exc)[:300]
                ),
                action="Enregistrez à nouveau la configuration du connecteur.",
            )
        ]
    else:
        checks = connector.test_connection()  # type: ignore[attr-defined]
    for check in checks:
        diagnostics.log_check(source, check)
    result = diagnostics.result_payload(source, checks)
    first_problem = next((c for c in checks if c.status != diagnostics.OK), None)
    append_audit_event(
        db,
        action="DIRECTORY_CONNECTION_TESTED",
        actor_id=user.id,
        target_type="directory_connector",
        target_id=source,
        metadata={
            "source": source,
            "status": result["status"],
            "error_code": first_problem.code if first_problem else None,
            "provider_code": first_problem.provider_code if first_problem else None,
        },
    )
    db.commit()
    return result


@router.post("/sync")
def trigger_sync(
    request: Request,
    source: str | None = None,
    db: DbSession = Depends(get_db),
    http_client: httpx.Client = Depends(get_directory_http_client),
    user: User = Depends(_admin),
) -> dict[str, Any]:
    connector: DirectoryConnector
    active = active_source(db, request.app.state.settings)
    if source is not None and source not in available_sources(request.app.state.settings):
        raise HTTPException(status_code=404, detail=f"unknown directory source {source!r}")
    if active is None:
        raise HTTPException(status_code=409, detail="Aucun annuaire configuré.")
    source = source or active
    if source != active:
        raise HTTPException(
            status_code=409,
            detail=f"Un seul annuaire est actif à la fois : {active!r}. "
            f"Configurez {source!r} pour le rendre actif.",
        )
    if source == "local":
        connector = LocalConnector()
    elif source in SPECS:
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
