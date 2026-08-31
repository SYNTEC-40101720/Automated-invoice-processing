"""更新确认冒烟：写入 SYNTEC_UPDATE_READY_FILE 后保持运行。"""
from __future__ import annotations

import os
import time
from pathlib import Path


def main() -> int:
    raw = os.environ.get('SYNTEC_UPDATE_READY_FILE')
    if raw:
        Path(raw).touch()
        (Path.cwd() / '.smoke-child.pid').write_text(
            str(os.getpid()),
            encoding='ascii',
        )
    # 保持存活，等待 helper 在确认后终止我们
    time.sleep(5)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
