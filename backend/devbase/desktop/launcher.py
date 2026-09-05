"""Run the local FastAPI application inside an optional pywebview window."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from threading import Event, Thread
from time import monotonic
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import uvicorn
from fastapi import FastAPI

from devbase.api.app import create_app
from devbase.application.lifecycle import (
    LifecyclePolicy,
    WindowCloseMode,
)
from devbase.desktop.native_bridge import NativeBridge


class DesktopLaunchError(RuntimeError):
    """Raised when the local desktop window cannot be started."""


class DesktopDependencyError(DesktopLaunchError):
    """Raised when the optional desktop dependency is not installed."""


ServerFactory = Callable[[uvicorn.Config], uvicorn.Server]
ReadinessWaiter = Callable[[str, int, Thread, Event, float], bool]


def _load_webview() -> Any:
    try:
        import webview
    except ModuleNotFoundError as error:
        if error.name == "webview":
            raise DesktopDependencyError(
                "桌面模式需要可选依赖 pywebview。请在模板 backend 目录执行："
                'python -m pip install -e ".[test,desktop]"'
            ) from error
        raise
    return webview


def _local_host(host: str) -> str:
    return "127.0.0.1" if host in {"0.0.0.0", "::"} else host


def _format_url_host(host: str) -> str:
    local_host = _local_host(host)
    if ":" in local_host and not local_host.startswith("["):
        return f"[{local_host}]"
    return local_host


def _desktop_url(host: str, port: int, token: str | None = None) -> str:
    url = f"http://{_format_url_host(host)}:{port}/"
    if token:
        url += "?" + urlencode({"token": token})
    return url


def _wait_for_server_ready(
    host: str,
    port: int,
    server_thread: Thread,
    stop_event: Event,
    timeout: float = 10.0,
    token: str | None = None,
) -> bool:
    health_url = (
        f"http://{_format_url_host(host)}:{port}/api/v1/health"
    )
    deadline = monotonic() + timeout

    while not stop_event.is_set():
        if not server_thread.is_alive():
            return False
        remaining = deadline - monotonic()
        if remaining <= 0:
            return False
        try:
            headers = {"X-Local-Token": token} if token else {}
            request = Request(health_url, headers=headers)
            with urlopen(request, timeout=min(0.5, remaining)) as response:
                if response.status == 200:
                    return True
        except (OSError, URLError):
            pass
        stop_event.wait(min(0.1, remaining))
    return False


def _wait_for_job_terminal(
    runtime: Any,
    stop_event: Event,
    timeout: float,
) -> bool:
    deadline = monotonic() + timeout
    while not stop_event.is_set():
        job = runtime.current_job()
        if job is None or job.status.is_terminal:
            return True
        remaining = deadline - monotonic()
        if remaining <= 0:
            return False
        stop_event.wait(min(0.1, remaining))
    return False


def run_desktop(
    static_dir: str | Path,
    host: str = "127.0.0.1",
    port: int = 8000,
    close_mode: WindowCloseMode = WindowCloseMode.STOP_ON_CLOSE,
    *,
    window_title: str = "DevBase",
    window_width: int = 1280,
    window_height: int = 800,
    readiness_timeout: float = 10.0,
    app_factory: Callable[..., FastAPI] = create_app,
    server_factory: ServerFactory | None = None,
    webview_module: Any | None = None,
    readiness_waiter: ReadinessWaiter | None = None,
    native_bridge: NativeBridge | None = None,
) -> None:
    """Run the local API and host its static frontend in a desktop window."""
    normalized_close_mode = WindowCloseMode(close_mode)
    webview = (
        webview_module
        if webview_module is not None
        else _load_webview()
    )
    app = app_factory(
        static_dir=static_dir,
        lifecycle_policy=LifecyclePolicy(normalized_close_mode),
    )
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        reload=False,
    )
    server = (server_factory or uvicorn.Server)(config)
    stop_event = Event()
    server_thread = Thread(
        target=server.run,
        name="devbase-api-server",
        daemon=True,
    )
    close_result = None

    def on_closed(*_args: Any, **_kwargs: Any) -> None:
        nonlocal close_result
        try:
            close_result = app.state.window_lifecycle.handle_window_close()
        finally:
            if close_result is not None and (
                close_result.mode is WindowCloseMode.STOP_ON_CLOSE
            ):
                server.should_exit = True

    server_thread.start()
    try:
        waiter = readiness_waiter or (
            lambda ready_host, ready_port, ready_thread, ready_stop, ready_timeout:
            _wait_for_server_ready(
                ready_host,
                ready_port,
                ready_thread,
                ready_stop,
                ready_timeout,
                token=app.state.local_token,
            )
        )
        if not waiter(
            host,
            port,
            server_thread,
            stop_event,
            readiness_timeout,
        ):
            raise DesktopLaunchError(
                "桌面模式的本地服务未及时就绪，未打开 WebView 窗口。"
            )

        try:
            window = webview.create_window(
                title=window_title,
                url=_desktop_url(host, port, app.state.local_token),
                width=window_width,
                height=window_height,
                js_api=native_bridge or NativeBridge(),
            )
            if window is None:
                raise RuntimeError("pywebview 未创建窗口")
            window.events.closed += on_closed
            webview.start(gui="edgechromium", debug=False)
            if (
                close_result is not None
                and close_result.mode is WindowCloseMode.CONTINUE_ON_CLOSE
            ):
                _wait_for_job_terminal(
                    app.state.runtime,
                    stop_event,
                    readiness_timeout,
                )
        except DesktopLaunchError:
            raise
        except Exception as error:
            raise DesktopLaunchError(
                "无法启动 Windows WebView2 桌面窗口，请确认在 Windows 上运行并"
                f"安装 WebView2 Runtime。原始错误：{error}"
            ) from error
    finally:
        stop_event.set()
        server.should_exit = True
        server_thread.join()