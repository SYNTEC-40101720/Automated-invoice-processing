"""SYNTEC 电子票据处理系统 Web 桌面入口。"""

import argparse
import os
import sys
import threading
import webbrowser
from pathlib import Path
from time import monotonic
from urllib.error import URLError
from urllib.request import Request, urlopen

BACKEND_DIR = Path(__file__).resolve().parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from invoice_processor.desktop.launcher import run_desktop
from invoice_processor.logger_config import setup_logging


ROOT_DIR = Path(__file__).resolve().parent
FRONTEND_DIST_DIR = ROOT_DIR / 'web' / 'dist'


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='启动 SYNTEC 电子票据本地工作台。',
    )
    parser.add_argument(
        '--host',
        default=os.getenv('PLATFORM_HOST', '127.0.0.1'),
        help='API 监听地址（默认使用 PLATFORM_HOST 或 127.0.0.1）',
    )
    parser.add_argument(
        '--port',
        type=int,
        default=_default_port(),
        help='API 监听端口（默认使用 PLATFORM_PORT 或 8000）',
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--browser', action='store_true', help='使用浏览器调试模式')
    mode.add_argument('--desktop', action='store_true', help='使用桌面窗口模式（默认）')
    parser.add_argument(
        '--reload',
        action='store_true',
        help='启用 Uvicorn reload，仅适用于 --browser',
    )
    parser.add_argument(
        '--no-browser',
        action='store_true',
        help='浏览器模式下不自动打开浏览器',
    )
    return parser


def _default_port() -> int:
    try:
        return int(os.getenv('PLATFORM_PORT', '8000'))
    except ValueError:
        return 8000


def _require_frontend_build() -> Path:
    index_path = FRONTEND_DIST_DIR / 'index.html'
    if not index_path.is_file():
        raise FileNotFoundError(
            f'未找到前端构建入口：{index_path}\n'
            '请先在 web 目录执行 npm install 和 npm run build。'
        )
    return FRONTEND_DIST_DIR


def _wait_for_server_ready(
    host: str,
    port: int,
    stop_event: threading.Event,
    token: str,
    timeout: float = 10.0,
) -> bool:
    health_url = f'http://{host}:{port}/api/v1/system/health'
    deadline = monotonic() + timeout
    while not stop_event.is_set() and monotonic() < deadline:
        try:
            request = Request(health_url, headers={'X-Local-Token': token})
            with urlopen(request, timeout=0.5) as response:
                if response.status == 200:
                    return True
        except (OSError, URLError):
            pass
        stop_event.wait(0.1)
    return False


def main() -> None:
    setup_logging()
    parser = build_parser()
    args = parser.parse_args()
    if args.reload and not args.browser:
        parser.error('--reload 仅用于浏览器调试模式，请同时使用 --browser。')
    try:
        static_dir = _require_frontend_build()
    except FileNotFoundError as error:
        print(error, file=sys.stderr)
        raise SystemExit(1) from error

    if not args.browser:
        run_desktop(
            host=args.host,
            port=args.port,
            static_dir=static_dir,
        )
        return

    import uvicorn

    token = os.getenv('PLATFORM_LOCAL_TOKEN') or os.urandom(24).hex()
    os.environ['PLATFORM_LOCAL_TOKEN'] = token
    os.environ['PLATFORM_STATIC_DIR'] = str(static_dir)
    stop_event = threading.Event()
    browser_thread = None
    if not args.no_browser:
        def open_browser() -> None:
            if _wait_for_server_ready(args.host, args.port, stop_event, token):
                webbrowser.open(
                    f'http://{args.host}:{args.port}/?token={token}'
                )

        browser_thread = threading.Thread(
            target=open_browser,
            name='invoice-browser-opener',
            daemon=True,
        )
        browser_thread.start()
    try:
        uvicorn.run(
            'invoice_processor.api.app:create_app_from_environment',
            factory=True,
            host=args.host,
            port=args.port,
            reload=args.reload,
            app_dir=str(BACKEND_DIR),
        )
    finally:
        stop_event.set()
        if browser_thread is not None:
            browser_thread.join()


if __name__ == '__main__':
    main()
