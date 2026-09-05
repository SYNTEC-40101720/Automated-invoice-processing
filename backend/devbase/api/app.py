import os
import secrets
from collections.abc import Iterable
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from devbase.application.errors import (
    JobAlreadyRunningError,
    JobNotCancellableError,
    NoCurrentJobError,
)
from devbase.application.job_runtime import JobRuntime
from devbase.application.lifecycle import LifecyclePolicy, WindowLifecycle
from devbase.application.task import TaskNotFoundError
from devbase.desktop.update_manager import UpdateManager
from devbase import __version__

from .routes import events, jobs, system, tools, updates


def create_app(
    runtime: JobRuntime | None = None,
    *,
    title: str = "DevBase",
    version: str = __version__,
    local_token: str | None = None,
    static_dir: str | Path | None = None,
    lifecycle_policy: LifecyclePolicy | None = None,
    allowed_origins: Iterable[str] | None = None,
    update_manager: UpdateManager | None = None,
    include_default_routes: bool = True,
    defer_static_mount: bool = False,
) -> FastAPI:
    app = FastAPI(
        title=title,
        version=version,
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/v1/openapi.json",
    )
    resolved_origins: tuple[str, ...]
    if allowed_origins is not None:
        resolved_origins = tuple(o.rstrip("/") for o in allowed_origins)
    else:
        resolved_origins = (
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    app.state.runtime = runtime or JobRuntime()
    app.state.local_token = (
        local_token if local_token is not None else secrets.token_urlsafe(32)
    )
    app.state.allowed_origins = frozenset(resolved_origins)
    install_dir = Path(
        os.getenv(
            "PLATFORM_INSTALL_DIR",
            str(Path(__file__).resolve().parents[3]),
        )
    )
    app.state.update_manager = update_manager or UpdateManager(
        version,
        install_dir=install_dir,
        update_root=os.getenv("PLATFORM_UPDATE_DIR"),
    )
    app.state.window_lifecycle = WindowLifecycle(
        lifecycle_policy or LifecyclePolicy(),
        stop_active_job=_stop_active_job(app.state.runtime),
    )

    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; base-uri 'none'; object-src 'none'; "
            "frame-ancestors 'none'; script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "connect-src 'self' ws: wss:; form-action 'self'",
        )
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    if include_default_routes:
        app.include_router(system.router, prefix="/api/v1")
        app.include_router(jobs.router, prefix="/api/v1")
        app.include_router(events.router, prefix="/api/v1")
        app.include_router(tools.router, prefix="/api/v1")
        app.include_router(updates.router, prefix="/api/v1")

    if static_dir is not None and not defer_static_mount:
        mount_static_frontend(app, static_dir)

    @app.exception_handler(JobAlreadyRunningError)
    async def handle_job_conflict(
        _request: Request,
        _exception: JobAlreadyRunningError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": "a non-terminal job is already running"},
        )

    @app.exception_handler(NoCurrentJobError)
    async def handle_missing_job(
        _request: Request,
        _exception: NoCurrentJobError,
    ) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": "no current job"})

    @app.exception_handler(JobNotCancellableError)
    async def handle_terminal_job(
        _request: Request,
        _exception: JobNotCancellableError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": "the current job is already terminal"},
        )

    @app.exception_handler(TaskNotFoundError)
    async def handle_missing_task(
        _request: Request,
        exception: TaskNotFoundError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"detail": f"task kind not registered: {exception.kind!r}"},
        )

    return app


def mount_static_frontend(app: FastAPI, static_dir: str | Path | None) -> None:
    """Mount a built frontend after a derived app has registered its routes."""
    if static_dir is None:
        return
    static_path = Path(static_dir)
    if static_path.is_dir() and (static_path / "index.html").is_file():
        app.mount(
            "/",
            StaticFiles(directory=static_path, html=True),
            name="frontend",
        )


def create_app_from_environment() -> FastAPI:
    return create_app(
        static_dir=os.getenv("PLATFORM_STATIC_DIR"),
        local_token=os.getenv("PLATFORM_LOCAL_TOKEN"),
    )


def _stop_active_job(runtime: JobRuntime):
    def stop() -> bool:
        try:
            runtime.cancel_current()
        except (NoCurrentJobError, JobNotCancellableError):
            return False
        return True

    return stop


app = create_app()
