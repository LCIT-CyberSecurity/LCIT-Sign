from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, Response, status

from lcit_sign import __version__
from lcit_sign.config import Settings
from lcit_sign.deps import get_current_user
from lcit_sign.models.user import User

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness: the process is up. Must never depend on the database."""
    return {"status": "ok"}


@router.get("/ready")
def ready(request: Request, response: Response) -> dict[str, str]:
    """Readiness: the application can actually serve requests."""
    from lcit_sign.database import database_is_ready

    if database_is_ready(request.app.state.engine):
        return {"status": "ready"}
    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "not-ready"}


@router.get("/config")
def public_config(request: Request, user: User = Depends(get_current_user)) -> dict[str, Any]:
    """Non-secret, display-only config the frontend needs (consent text
    shown before signing, app version shown on evidence) — gated behind
    auth only because it's meaningless to an anonymous visitor, not
    because it's sensitive."""
    settings: Settings = request.app.state.settings
    return {
        "app_version": __version__,
        "office_conversion": bool(settings.converter_url),
        "consent_text": settings.consent_text,
        "consent_version": settings.consent_version,
    }
