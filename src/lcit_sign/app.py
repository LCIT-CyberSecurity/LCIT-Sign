from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from lcit_sign import __version__
from lcit_sign.api.admin import router as admin_router
from lcit_sign.api.auth import router as auth_router
from lcit_sign.api.campaigns import me_router as me_assignments_router
from lcit_sign.api.campaigns import router as campaigns_router
from lcit_sign.api.diagnostics import router as diagnostics_router
from lcit_sign.api.directory import router as directory_router
from lcit_sign.api.documents import router as documents_router
from lcit_sign.api.health import router as health_router
from lcit_sign.api.reports import campaign_reports_router
from lcit_sign.api.reports import router as reports_router
from lcit_sign.api.signatures import router as signatures_router
from lcit_sign.config import Settings, get_settings
from lcit_sign.database import make_engine, make_session_factory
from lcit_sign.logging_utils import configure_logging
from lcit_sign.request_context import set_request_id, set_source_ip
from lcit_sign.services.notification_queue import process_pending_notifications
from lcit_sign.services.rate_limit import SlidingWindowLimiter
from lcit_sign.services.scheduler import (
    process_directory_syncs,
    process_reminders,
    process_renewals,
)
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
        http_client = httpx.Client(timeout=30.0)
        try:
            # Scheduled work first, so reminders queued now go out in this
            # same cycle. Each job commits on its own and is idempotent.
            jobs: list[tuple[str, Callable[[], object]]] = [
                ("reminders", lambda: process_reminders(db, settings)),
                ("renewals", lambda: process_renewals(db, settings)),
                ("directory sync", lambda: process_directory_syncs(db, settings, http_client)),
            ]
            for job_name, job in jobs:
                try:
                    job()
                except Exception:
                    db.rollback()
                    logger.exception("scheduled job failed: %s", job_name)
            process_pending_notifications(db, settings)
            app.state.worker_last_run = datetime.now(UTC)
        finally:
            http_client.close()
            db.close()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = make_engine(settings.database_url)
        app.state.session_factory = make_session_factory(app.state.engine)
        app.state.storage = StorageService(settings.storage_root)
        app.state.worker_last_run = None

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

    def client_ip(request: Request) -> str:
        # nginx appends the real peer as the LAST X-Forwarded-For entry;
        # earlier entries are client-supplied and not trusted.
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[-1].strip()
        return request.client.host if request.client else "unknown"

    @app.middleware("http")
    async def add_request_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        set_request_id(request_id)
        set_source_ip(client_ip(request))
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        return response

    limiter = SlidingWindowLimiter()
    # (path prefix, limit, window seconds): tighter on what is expensive or
    # abusable (login, signing, outbound connectivity tests), loose overall.
    limits = [
        ("/api/auth/login", 20, 60.0),
        ("/api/auth/callback", 20, 60.0),
        ("/api/admin/mail-connector/", 10, 60.0),
        ("/api/admin/directory/sync", 10, 60.0),
        ("/api/documents/versions/", 60, 60.0),
        ("/api/", 600, 60.0),
    ]

    @app.middleware("http")
    async def rate_limit(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if settings.rate_limit_enabled and request.url.path.startswith("/api/"):
            ip = client_ip(request)
            for prefix, limit, window in limits:
                if request.url.path.startswith(prefix) and not limiter.allow(
                    f"{prefix}|{ip}", limit, window
                ):
                    return JSONResponse(
                        {"detail": "Too many requests"},
                        status_code=429,
                        headers={"Retry-After": str(int(window))},
                    )
        return await call_next(request)

    def allowed_origin(request: Request) -> bool:
        origin = request.headers.get("origin")
        if origin is None:
            # Browsers always send Origin on cross-site unsafe requests;
            # a request without one is not a cross-site browser request
            # (and Sec-Fetch-Site, when present, must not say otherwise).
            return request.headers.get("sec-fetch-site", "same-origin") in (
                "same-origin",
                "none",
            )
        if origin in settings.cors_allowed_origins:
            return True
        netloc = urlsplit(origin).netloc
        public_netloc = urlsplit(settings.public_base_url).netloc
        return netloc in (request.headers.get("host", ""), public_netloc)

    @app.middleware("http")
    async def csrf_origin_check(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # SameSite cookies are the first line; this rejects cross-origin
        # state-changing requests even if a cookie attribute is lost.
        if (
            request.method in ("POST", "PUT", "PATCH", "DELETE")
            and request.url.path.startswith("/api/")
            and not allowed_origin(request)
        ):
            return JSONResponse({"detail": "Cross-origin request rejected"}, status_code=403)
        return await call_next(request)

    @app.exception_handler(Exception)
    async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        # Full trace goes to the server log (with the request id); the
        # client only ever gets an opaque message (spec §82).
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        request_id = getattr(request.state, "request_id", None)
        return JSONResponse(
            {"detail": "Internal server error", "request_id": request_id}, status_code=500
        )

    @app.middleware("http")
    async def add_security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers[name] = value
        if settings.cookie_secure:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        return response

    app.include_router(health_router, prefix="/api")
    app.include_router(auth_router, prefix="/api")
    app.include_router(admin_router, prefix="/api")
    app.include_router(documents_router, prefix="/api")
    app.include_router(signatures_router, prefix="/api")
    app.include_router(campaigns_router, prefix="/api")
    app.include_router(me_assignments_router, prefix="/api")
    app.include_router(directory_router, prefix="/api")
    app.include_router(diagnostics_router, prefix="/api")
    app.include_router(campaign_reports_router, prefix="/api")
    app.include_router(reports_router, prefix="/api")

    return app
