"""FastAPI application factory (P2).

    uvicorn app.main:app            # uses .env / environment settings

Run ONE worker process: live notifications (SSE) and the background scheduler keep
state in memory. Scaling past one process is in the report's future work.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import routes
from app.api.deps import notification_user
from app.bootstrap import Backend
from app.config import Settings, get_settings
from app.errors import http_status_for
from domain.exceptions import ITSMError

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, backend: Backend | None = None) -> FastAPI:
    settings = settings or get_settings()

    # Built here, not in the lifespan, because the notification routes need the live
    # module. Building connects to nothing heavy; P4's models load in the lifespan.
    backend = backend or Backend.build(settings, with_p4=False)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        backend.start_p4()
        backend.start()
        try:
            yield
        finally:
            backend.stop()

    app = FastAPI(title="I-ITSM API", version="1.0.0", lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.backend = backend
    app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ORIGINS,
                       allow_methods=["GET", "POST", "PATCH"],
                       allow_headers=["Authorization", "Content-Type", "Last-Event-ID"])

    @app.exception_handler(ITSMError)
    async def domain_error(_request: Request, error: ITSMError) -> JSONResponse:
        status, code = http_status_for(error)
        if status >= 500:
            log.error("unhandled domain error: %r", error)
        return JSONResponse({"code": code, "message": str(error)}, status_code=status)

    @app.exception_handler(PermissionError)
    async def append_only(_request: Request, error: PermissionError) -> JSONResponse:
        return JSONResponse({"code": "FORBIDDEN", "message": str(error)}, status_code=403)

    @app.exception_handler(RequestValidationError)
    async def bad_request(_request: Request, error: RequestValidationError) -> JSONResponse:
        first = error.errors()[0] if error.errors() else {}
        field = ".".join(str(p) for p in first.get("loc", [])[1:]) or "request"
        return JSONResponse({"code": "INVALID_INPUT",
                             "message": f"{field}: {first.get('msg', 'invalid value')}"},
                            status_code=422)

    @app.get("/health", include_in_schema=False)
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(routes.public, prefix="/api")
    app.include_router(routes.api, prefix="/api")
    app.include_router(routes.admin, prefix="/api")

    app.include_router(backend.notifications.router(notification_user), prefix="/api")

    return app


app = create_app()
