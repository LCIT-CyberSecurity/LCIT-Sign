from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from lcit_sign import __version__
from lcit_sign.api.admin import router as admin_router
from lcit_sign.api.auth import router as auth_router
from lcit_sign.api.campaigns import me_router as me_assignments_router
from lcit_sign.api.campaigns import router as campaigns_router
from lcit_sign.api.directory import router as directory_router
from lcit_sign.api.documents import router as documents_router
from lcit_sign.api.health import router as health_router
from lcit_sign.api.signatures import router as signatures_router
from lcit_sign.config import Settings, get_settings
from lcit_sign.database import make_engine, make_session_factory
from lcit_sign.logging_utils import configure_logging
from lcit_sign.request_context import set_request_id
from lcit_sign.services.notification_queue import process_pending_notifications
from lcit_sign.services.storage import StorageService

logger = logging.getLogger(__name__)

# LCIT Sign is a Backend-For-Frontend: the browser only ever talks to nginx,
# which proxies same-origin to this API. Nothing here is meant to be called
# cross-origin, so CORS stays empty unless a deployment explicitly opts in
# (e.g. a local dev server on a different port).
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    async def _notification_worker_loop(app: FastAPI) -> None:
        while True:
            await asyncio.sleep(settings.notification_worker_interval_seconds)
            try:
                await asyncio.to_thread(_process_notifications_once, app)
            except Exception:
                logger.exception("notification worker iteration failed")

    def _process_notifications_once(app: FastAPI) -> None:
        db = app.state.session_factory()
        try:
            process_pending_notifications(db, settings)
        finally:
            db.close()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = make_engine(settings.database_url)
        app.state.session_factory = make_session_factory(app.state.engine)
        app.state.storage = StorageService(settings.storage_root)

        worker_task = None
        if settings.notification_worker_enabled:
            worker_task = asyncio.create_task(_notification_worker_loop(app))

        yield

        if worker_task is not None:
            worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker_task
        app.state.engine.dispose()

    app = FastAPI(title="LCIT Sign", version=__version__, lifespan=lifespan)
    app.state.settings = settings

    if settings.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allowed_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.middleware("http")
    async def add_request_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        set_request_id(request_id)
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        return response

    @app.middleware("http")
    async def add_security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers[name] = value
        return response

    app.include_router(health_router, prefix="/api")
    app.include_router(auth_router, prefix="/api")
    app.include_router(admin_router, prefix="/api")
    app.include_router(documents_router, prefix="/api")
    app.include_router(signatures_router, prefix="/api")
    app.include_router(campaigns_router, prefix="/api")
    app.include_router(me_assignments_router, prefix="/api")
    app.include_router(directory_router, prefix="/api")

    return app
