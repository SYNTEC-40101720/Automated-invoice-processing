"""SYNTEC 电子票据处理系统 Web 桌面入口。"""

import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from invoice_processor.desktop.launcher import run_desktop
from invoice_processor.logger_config import setup_logging

FRONTEND_DIST_DIR = Path(__file__).resolve().parent / 'web' / 'dist'


def _require_frontend_build() -> Path:
    index_path = FRONTEND_DIST_DIR / 'index.html'
    if not index_path.is_file():
        raise FileNotFoundError(
            f'未找到前端构建入口：{index_path}\n'
            '请先在 web 目录执行 npm install 和 npm run build。'
        )
    return FRONTEND_DIST_DIR


def main() -> None:
    setup_logging()
    static_dir = _require_frontend_build()
    run_desktop(
        host=os.getenv('PLATFORM_HOST', '127.0.0.1'),
        port=int(os.getenv('PLATFORM_PORT', '8000')),
        static_dir=static_dir,
    )


if __name__ == '__main__':
    main()
