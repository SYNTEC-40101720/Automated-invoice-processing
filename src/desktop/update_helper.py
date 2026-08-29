"""独立更新器：等待主程序退出后替换安装目录并重启。"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

MAIN_EXECUTABLE_NAME = 'SYNTEC-电子票据处理系统.exe'
PRESERVED_ENTRIES = ('config.ini', 'logs', '发票收件箱')
PROCESS_POLL_INTERVAL = 0.25
PROCESS_WAIT_TIMEOUT = 60.0

logger = logging.getLogger(__name__)


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def _process_exists(pid: int) -> bool:
    try:
        result = subprocess.run(
            [
                'tasklist',
                '/FI',
                f'PID eq {pid}',
                '/FO',
                'CSV',
                '/NH',
            ],
            capture_output=True,
            text=True,
            check=False,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
    except OSError:
        return False
    return f'"{pid}"' in result.stdout


def wait_for_process_exit(
    pid: int,
    *,
    timeout: float = PROCESS_WAIT_TIMEOUT,
    process_checker: Callable[[int], bool] | None = None,
) -> None:
    checker = process_checker or _process_exists
    deadline = time.monotonic() + timeout
    while checker(pid):
        if time.monotonic() >= deadline:
            raise RuntimeError('等待主程序退出超时')
        time.sleep(PROCESS_POLL_INTERVAL)


def _restore_user_data(old_dir: Path, new_dir: Path) -> None:
    for relative_name in PRESERVED_ENTRIES:
        source = old_dir / relative_name
        if not source.exists():
            continue
        target = new_dir / relative_name
        _remove_path(target)
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)


def replace_install(
    source_dir: Path,
    target_dir: Path,
    *,
    backup_dir: Path | None = None,
) -> Path:
    """用已解压的新目录替换旧安装，并返回保留的旧目录。"""
    source_dir = source_dir.resolve()
    target_dir = target_dir.resolve()
    if not source_dir.is_dir():
        raise RuntimeError('新版本目录不存在')
    if not (source_dir / MAIN_EXECUTABLE_NAME).is_file():
        raise RuntimeError('新版本目录缺少主程序')
    if not target_dir.is_dir():
        raise RuntimeError('旧版本安装目录不存在')

    old_dir = backup_dir or target_dir.parent / f'.syntec-update-old-{os.getpid()}'
    old_dir = old_dir.resolve()
    if old_dir.exists():
        _remove_path(old_dir)
    old_dir.parent.mkdir(parents=True, exist_ok=True)

    try:
        target_dir.rename(old_dir)
        source_dir.rename(target_dir)
        _restore_user_data(old_dir, target_dir)
    except Exception:
        if target_dir.exists():
            _remove_path(target_dir)
        if old_dir.exists() and not target_dir.exists():
            old_dir.rename(target_dir)
        raise
    return old_dir


def _start_application(target_dir: Path) -> None:
    executable = target_dir / MAIN_EXECUTABLE_NAME
    subprocess.Popen(
        [str(executable)],
        cwd=str(target_dir),
        close_fds=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
    )


def run_update(
    source_dir: Path,
    target_dir: Path,
    cleanup_dir: Path,
    pid: int,
) -> None:
    cleanup_dir = cleanup_dir.resolve()
    target_dir = target_dir.resolve()
    cleanup_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(cleanup_dir / 'update.log', encoding='utf-8')
    handler.setLevel(logging.INFO)
    handler.setFormatter(
        logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
    )
    previous_logger_level = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    old_dir: Path | None = None
    succeeded = False
    try:
        wait_for_process_exit(pid)
        old_dir = replace_install(
            source_dir,
            target_dir,
            backup_dir=cleanup_dir / 'old-install',
        )
        _start_application(target_dir)
        _remove_path(old_dir)
        succeeded = True
    except Exception:
        logger.exception('自动更新失败')
        if old_dir and old_dir.exists() and target_dir.exists():
            _remove_path(target_dir)
            old_dir.rename(target_dir)
        raise
    finally:
        handler.flush()
        handler.close()
        logger.removeHandler(handler)
        logger.setLevel(previous_logger_level)
        if succeeded:
            shutil.rmtree(cleanup_dir, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, required=True)
    parser.add_argument('--target-dir', type=Path, required=True)
    parser.add_argument('--cleanup-dir', type=Path, required=True)
    parser.add_argument('--pid', type=int, required=True)
    args = parser.parse_args()
    run_update(args.source_dir, args.target_dir, args.cleanup_dir, args.pid)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
