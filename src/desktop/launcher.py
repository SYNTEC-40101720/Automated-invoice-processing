"""启动 FastAPI 本地服务并打开 WebView2 窗口。"""

from __future__ import annotations

import logging
import os
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
from .update_manager import DesktopUpdateManager
from .update_protocol import (
    UPDATE_READY_ENV_VAR,
    UPDATE_READY_FILENAME,
    UPDATE_READY_PARENT_PREFIX,
)

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


def _resolve_startup_ready_file() -> Path | None:
    raw_path = os.environ.get(UPDATE_READY_ENV_VAR)
    if not raw_path:
        return None
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        logger.warning('忽略非绝对的更新启动确认路径: %s', raw_path)
        return None
    try:
        ready_file = candidate.resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        logger.exception('解析更新启动确认路径失败: %s', raw_path)
        return None
    if ready_file.name != UPDATE_READY_FILENAME:
        logger.warning('忽略文件名不符合要求的更新启动确认路径: %s', raw_path)
        return None
    parent = ready_file.parent
    if not parent.name.startswith(UPDATE_READY_PARENT_PREFIX) or not parent.is_dir():
        logger.warning('忽略父目录不符合要求的更新启动确认路径: %s', raw_path)
        return None
    return ready_file


def _create_startup_ready_file(ready_file: Path) -> None:
    descriptor = os.open(
        str(ready_file),
        os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        0o600,
    )
    os.close(descriptor)


def _attach_startup_ready_handler(window, ready_file: Path | None) -> None:
    if ready_file is None:
        return

    def confirm_startup(*_args) -> None:
        try:
            _create_startup_ready_file(ready_file)
        except FileExistsError:
            return
        except Exception:
            logger.exception('写入更新启动确认文件失败: %s', ready_file)

    window.events.loaded += confirm_startup


def run_desktop() -> None:
    """启动桌面应用；pywebview 只在真正进入桌面模式时导入。"""
    port = _find_free_port()
    token = secrets.token_urlsafe(32)
    job_service = JobService()
    terminal_statuses = {
        'succeeded',
        'completed_with_warnings',
        'cancelled',
        'failed',
    }

    def can_update() -> bool:
        current_job = job_service.current_job()
        return not current_job or current_job['status'] in terminal_statuses

    update_manager = DesktopUpdateManager(can_update=can_update)
    app = create_app(
        job_service,
        local_token=token,
        allowed_origins={f'http://127.0.0.1:{port}'},
        static_dir=_bundle_root() / 'web' / 'dist',
        update_apply=update_manager.apply,
        update_progress=update_manager.progress,
    )
    job_service.start_background_tasks()
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
        try:
            import webview
        except ImportError as exc:
            raise RuntimeError('缺少 pywebview，请安装桌面运行依赖') from exc

        native_bridge = NativeBridge(job_service.is_known_directory)
        ready_file = _resolve_startup_ready_file()
        window = webview.create_window(
            'SYNTEC · 电子票据工作台',
            f'{base_url}/?token={token}',
            js_api=native_bridge,
            width=1280,
            height=820,
            min_size=(1024, 700),
            resizable=True,
        )
        _attach_startup_ready_handler(window, ready_file)
        update_manager.set_close_callback(window.destroy)
        webview.start(gui='edgechromium', debug=False)
        logger.info('WebView 窗口已关闭')
    finally:
        job_service.shutdown()
        server.should_exit = True
        server_thread.join(timeout=5)
