"""启动 FastAPI 本地服务并打开 WebView2 窗口。"""

from __future__ import annotations

import logging
import secrets
import socket
import sys
import threading
import time
from pathlib import Path
from urllib.request import Request, urlopen

import uvicorn

from ..api.app import create_app
from ..application.job_service import JobService
from .native_bridge import NativeBridge

logger = logging.getLogger(__name__)


def _bundle_root() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(getattr(sys, '_MEIPASS'))
    return Path(__file__).resolve().parents[2]


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return int(sock.getsockname()[1])


def _wait_until_ready(url: str, token: str, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            request = Request(url, headers={'X-Local-Token': token})
            with urlopen(request, timeout=1) as response:
                if response.status == 200:
                    return
        except Exception as exc:
            last_error = exc
        time.sleep(0.05)
    raise RuntimeError(f'本地服务启动超时: {last_error}')


def run_desktop() -> None:
    """启动桌面应用；pywebview 只在真正进入桌面模式时导入。"""
    try:
        import webview
    except ImportError as exc:
        raise RuntimeError('缺少 pywebview，请安装桌面运行依赖') from exc

    port = _find_free_port()
    token = secrets.token_urlsafe(32)
    job_service = JobService()
    app = create_app(
        job_service,
        local_token=token,
        static_dir=_bundle_root() / 'web' / 'dist',
    )
    config = uvicorn.Config(
        app,
        host='127.0.0.1',
        port=port,
        log_level='warning',
        access_log=False,
        log_config=None,
    )
    server = uvicorn.Server(config)
    server_thread = threading.Thread(target=server.run, name='local-api', daemon=True)
    server_thread.start()
    base_url = f'http://127.0.0.1:{port}'
    try:
        _wait_until_ready(f'{base_url}/api/v1/system/health', token)
        webview.create_window(
            'SYNTEC · 电子票据工作台',
            f'{base_url}/?token={token}',
            js_api=NativeBridge(),
            width=1280,
            height=820,
            min_size=(1024, 700),
            resizable=True,
        )
        webview.start(gui='edgechromium', debug=False)
        logger.info('WebView 窗口已关闭')
    finally:
        job_service.shutdown()
        server.should_exit = True
        server_thread.join(timeout=5)
