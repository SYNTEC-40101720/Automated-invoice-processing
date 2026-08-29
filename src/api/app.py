"""FastAPI 应用工厂。"""

from __future__ import annotations

import secrets
from collections.abc import Callable, Iterable
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from ..application.job_service import JobService
from ..application.update_checker import UpdateApplyResult
from ..domain.errors import ApplicationError
from ..version import __version__
from .errors import application_error_handler
from .routes import email, events, jobs, settings, system


def create_app(
    job_service: JobService | None = None,
    *,
    local_token: str | None = None,
    version: str = __version__,
    static_dir: str | Path | None = None,
    allowed_origins: Iterable[str] | None = None,
    update_apply: Callable[[str], UpdateApplyResult] | None = None,
) -> FastAPI:
    service = job_service or JobService()
    app = FastAPI(
        title='SYNTEC Invoice Processor API',
        version=version,
        docs_url=None,
        redoc_url=None,
        openapi_url='/api/v1/openapi.json',
    )
    app.state.job_service = service
    app.state.local_token = (
        local_token if local_token is not None else secrets.token_urlsafe(32)
    )
    app.state.version = version
    app.state.update_apply = update_apply
    app.state.allowed_origins = frozenset(
        origin.rstrip('/') for origin in (allowed_origins or ())
    )

    @app.middleware('http')
    async def add_security_headers(request, call_next):
        response = await call_next(request)
        response.headers.setdefault(
            'Content-Security-Policy',
            "default-src 'self'; base-uri 'none'; object-src 'none'; "
            "frame-ancestors 'none'; script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "connect-src 'self' ws: wss:; form-action 'self'",
        )
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('Referrer-Policy', 'no-referrer')
        return response

    app.include_router(system.router, prefix='/api/v1')
    app.include_router(jobs.router, prefix='/api/v1')
    app.include_router(events.router, prefix='/api/v1')
    app.include_router(settings.router, prefix='/api/v1')
    app.include_router(email.router, prefix='/api/v1')
    app.add_exception_handler(ApplicationError, application_error_handler)
    if static_dir is not None:
        static_path = Path(static_dir)
        if static_path.is_dir():
            app.mount(
                '/', StaticFiles(directory=str(static_path), html=True), name='web'
            )
    return app
