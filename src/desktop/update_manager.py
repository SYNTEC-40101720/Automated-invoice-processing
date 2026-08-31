"""桌面程序的更新下载、调度和重启编排。"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path

from ..application.update_checker import (
    UPDATE_HELPER_NAME,
    UpdateApplyResult,
    UpdateProgress,
    check_for_update,
    stage_update,
)

logger = logging.getLogger(__name__)


class DesktopUpdateManager:
    """准备更新包并交给独立更新器完成目录替换。"""

    def __init__(
        self,
        *,
        executable: Path | None = None,
        can_update: Callable[[], bool] | None = None,
    ):
        self._executable = (executable or Path(sys.executable)).resolve()
        self._target_dir = self._executable.parent
        self._can_update = can_update
        self._close_window: Callable[[], None] | None = None
        self._lock = threading.RLock()
        self._started = False
        self._progress = UpdateProgress()

    def set_close_callback(self, callback: Callable[[], None]) -> None:
        self._close_window = callback

    def progress(self) -> UpdateProgress:
        with self._lock:
            return self._progress

    def _set_progress(
        self,
        *,
        status: str,
        downloaded_bytes: int = 0,
        total_bytes: int | None = None,
        latest_version: str | None = None,
        message: str = '',
    ) -> None:
        with self._lock:
            self._progress = UpdateProgress(
                status=status,
                downloaded_bytes=downloaded_bytes,
                total_bytes=total_bytes,
                latest_version=latest_version,
                message=message,
            )

    def apply(self, current_version: str) -> UpdateApplyResult:
        with self._lock:
            if self._started:
                return UpdateApplyResult(
                    status='busy',
                    message='更新已经开始准备，请稍候',
                )
            if not getattr(sys, 'frozen', False):
                self._set_progress(
                    status='unsupported',
                    message='开发模式不支持自动安装更新',
                )
                return UpdateApplyResult(
                    status='unsupported',
                    message='开发模式不支持自动安装更新',
                )
            if self._can_update is not None:
                try:
                    if not self._can_update():
                        return UpdateApplyResult(
                            status='busy',
                            message='当前仍有任务运行，请完成或停止任务后再更新',
                        )
                except Exception:
                    logger.exception('检查更新前的任务状态失败')
                    return UpdateApplyResult(
                        status='busy',
                        message='暂时无法确认任务状态，请稍后再试',
                    )

            helper_source = self._target_dir / UPDATE_HELPER_NAME
            if not helper_source.is_file():
                return UpdateApplyResult(
                    status='unsupported',
                    message='当前安装包缺少更新器，请先手动安装一次支持自动更新的版本',
                )

            result = check_for_update(current_version)
            if not result.checked:
                self._set_progress(
                    status='failed',
                    message='无法连接 GitHub，暂时不能下载更新',
                )
                return UpdateApplyResult(
                    status='failed',
                    message='无法连接 GitHub，暂时不能下载更新',
                )
            if not result.available:
                self._set_progress(
                    status='idle',
                    latest_version=result.latest_version,
                    message=f'当前已经是最新版本 v{current_version}',
                )
                return UpdateApplyResult(
                    status='latest',
                    message=f'当前已经是最新版本 v{current_version}',
                    latest_version=result.latest_version,
                )
            if not result.installable:
                self._set_progress(
                    status='unavailable',
                    latest_version=result.latest_version,
                    message='此 Release 没有可安装的 SYNTEC ZIP 文件',
                )
                return UpdateApplyResult(
                    status='unavailable',
                    message='此 Release 没有可安装的 SYNTEC ZIP 文件',
                    latest_version=result.latest_version,
                )

            self._started = True
            self._set_progress(
                status='downloading',
                total_bytes=result.asset_size,
                latest_version=result.latest_version,
                message=f'正在下载 v{result.latest_version}',
            )
            threading.Thread(
                target=self._prepare_update,
                args=(result, helper_source),
                name='prepare-desktop-update',
                daemon=True,
            ).start()

        return UpdateApplyResult(
            status='started',
            message=f'已开始下载 v{result.latest_version}，下载完成后程序将自动重启',
            latest_version=result.latest_version,
        )

    def _prepare_update(self, result, helper_source: Path) -> None:
        staged = None
        downloaded_bytes = 0
        total_bytes = result.asset_size

        def report_progress(downloaded: int, total: int | None) -> None:
            nonlocal downloaded_bytes, total_bytes
            downloaded_bytes = downloaded
            total_bytes = total
            self._set_progress(
                status='downloading',
                downloaded_bytes=downloaded,
                total_bytes=total,
                latest_version=result.latest_version,
                message=f'正在下载 v{result.latest_version}',
            )

        try:
            staged = stage_update(
                result,
                temporary_parent=self._target_dir.parent,
                progress_callback=report_progress,
            )
            self._set_progress(
                status='preparing',
                downloaded_bytes=downloaded_bytes,
                total_bytes=total_bytes,
                latest_version=result.latest_version,
                message='下载完成，正在校验并准备安装包',
            )
            helper_path = self._copy_helper(helper_source)
            self._launch_helper(
                helper_path,
                staged.temporary_dir,
                staged.package_dir,
            )
            self._set_progress(
                status='starting',
                downloaded_bytes=downloaded_bytes,
                total_bytes=total_bytes,
                latest_version=result.latest_version,
                message='安装包已准备，程序即将重启完成更新',
            )
        except Exception as exc:
            logger.info('准备自动更新失败: %s', exc)
            if staged is not None:
                shutil.rmtree(staged.temporary_dir, ignore_errors=True)
            self._set_progress(
                status='failed',
                downloaded_bytes=downloaded_bytes,
                total_bytes=total_bytes,
                latest_version=result.latest_version,
                message='更新下载或校验失败，请稍后重试',
            )
            with self._lock:
                self._started = False
            return

        threading.Thread(
            target=self._close_window_later,
            name='close-window-for-update',
            daemon=True,
        ).start()

    @staticmethod
    def _remove_stale_helpers() -> None:
        temp_root = Path(tempfile.gettempdir())
        for path in temp_root.glob('.syntec-updater-*'):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)

    def _copy_helper(self, helper_source: Path) -> Path:
        self._remove_stale_helpers()
        helper_dir = Path(tempfile.mkdtemp(prefix='.syntec-updater-'))
        helper_path = helper_dir / UPDATE_HELPER_NAME
        try:
            shutil.copy2(helper_source, helper_path)
        except OSError:
            shutil.rmtree(helper_dir, ignore_errors=True)
            raise
        return helper_path

    def _launch_helper(
        self,
        helper_path: Path,
        temporary_dir: Path,
        package_dir: Path,
    ) -> None:
        creationflags = 0
        if os.name == 'nt':
            creationflags = (
                getattr(subprocess, 'DETACHED_PROCESS', 0)
                | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
            )
        subprocess.Popen(
            [
                str(helper_path),
                '--source-dir',
                str(package_dir),
                '--target-dir',
                str(self._target_dir),
                '--cleanup-dir',
                str(temporary_dir),
                '--pid',
                str(os.getpid()),
            ],
            cwd=str(self._target_dir.parent),
            close_fds=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )

    def _close_window_later(self) -> None:
        callback = self._close_window
        if callback is None:
            return
        time.sleep(0.3)
        try:
            callback()
        except Exception:
            logger.exception('关闭桌面窗口以完成更新失败')
