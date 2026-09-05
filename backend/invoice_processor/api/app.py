"""FastAPI 应用工厂。"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from pathlib import Path

from fastapi import FastAPI

from devbase.application.job_runtime import JobRuntime
from devbase.api.app import create_app as create_devbase_app

from ..application.invoice_task import build_invoice_registry
from ..application.job_service import JobService
from ..application.update_checker import UpdateApplyResult, UpdateProgress
from ..domain.errors import ApplicationError
from ..version import __version__
from .errors import application_error_handler
from .routes import email, events, jobs, settings, system, tools


def create_app(
    job_service: JobService | None = None,
    *,
    local_token: str | None = None,
    version: str = __version__,
    static_dir: str | Path | None = None,
    allowed_origins: Iterable[str] | None = None,
    update_apply: Callable[[str], UpdateApplyResult] | None = None,
    update_progress: Callable[[], UpdateProgress] | None = None,
) -> FastAPI:
    service = job_service or JobService()
    runtime = JobRuntime(registry=build_invoice_registry(service))
    app = create_devbase_app(
        runtime=runtime,
        title='SYNTEC Invoice Processor API',
        version=version,
        local_token=local_token,
        static_dir=static_dir,
        lifecycle_policy=None,
        allowed_origins=allowed_origins,
        include_default_routes=False,
    )
    app.state.job_service = service
    app.state.devbase_runtime = runtime
    app.state.version = version
    app.state.update_apply = update_apply
    app.state.update_progress = update_progress

    app.include_router(system.router, prefix='/api/v1')
    app.include_router(jobs.router, prefix='/api/v1')
    app.include_router(events.router, prefix='/api/v1')
    app.include_router(settings.router, prefix='/api/v1')
    app.include_router(email.router, prefix='/api/v1')
    app.include_router(tools.router, prefix='/api/v1')
    app.add_exception_handler(ApplicationError, application_error_handler)
    return app


def create_app_from_environment() -> FastAPI:
    """Create the browser-mode app from the launcher environment."""
    return create_app(
        local_token=os.getenv('PLATFORM_LOCAL_TOKEN'),
        static_dir=os.getenv('PLATFORM_STATIC_DIR'),
    )
