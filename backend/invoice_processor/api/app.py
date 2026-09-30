"""FastAPI 应用工厂。"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

from devbase.api.app import (
    create_app as create_devbase_app,
)
from devbase.api.app import (
    mount_static_frontend,
)
from devbase.application.job_runtime import JobRuntime
from fastapi import FastAPI

from ..application.invoice_task import build_invoice_registry
from ..application.job_history import JobHistoryStore, default_history_path
from ..application.job_service import JobService
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
) -> FastAPI:
    service = job_service or JobService(job_history_store=JobHistoryStore(default_history_path()))
    # 总线单实例化（融合二期）：runtime 复用 service 的总线，业务事件
    # 与生命周期事件共享同一 event_id 编号空间。注入 service 的场景
    # （测试、launcher）同样保证单实例。
    runtime = JobRuntime(
        registry=build_invoice_registry(service),
        event_bus=service.events,
    )
    app = create_devbase_app(
        runtime=runtime,
        title='SYNTEC Invoice Processor API',
        version=version,
        local_token=local_token,
        static_dir=static_dir,
        lifecycle_policy=None,
        allowed_origins=allowed_origins if allowed_origins is not None else (),
        include_default_routes=False,
        defer_static_mount=True,
    )
    app.state.job_service = service
    app.state.devbase_runtime = runtime
    app.state.version = version

    app.include_router(system.router, prefix='/api/v1')
    app.include_router(jobs.router, prefix='/api/v1')
    app.include_router(events.router, prefix='/api/v1')
    app.include_router(settings.router, prefix='/api/v1')
    app.include_router(email.router, prefix='/api/v1')
    app.include_router(tools.router, prefix='/api/v1')
    app.add_exception_handler(ApplicationError, application_error_handler)
    mount_static_frontend(app, static_dir)
    return app


def create_app_from_environment() -> FastAPI:
    """Create the browser-mode app from the launcher environment."""
    return create_app(
        local_token=os.getenv('PLATFORM_LOCAL_TOKEN'),
        static_dir=os.getenv('PLATFORM_STATIC_DIR'),
    )
