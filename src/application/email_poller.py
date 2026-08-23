"""邮箱自动轮询调度。"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from ..config_manager import (
    get_email_auth_code,
    get_email_config,
    get_email_days_back,
    get_email_enabled,
    get_email_poll_minutes,
    get_email_username,
    get_inbox_dir,
)
from ..core.email_pull import DEFAULT_IMAP_TIMEOUT_SECONDS, pull_invoices
from ..domain.errors import ApplicationError
from ..domain.job import JobTrigger

logger = logging.getLogger(__name__)


class EmailPoller:
    """按配置轮询邮箱，并把新附件交给任务服务处理。"""

    def __init__(
        self,
        start_job: Callable[[str, JobTrigger], dict],
        pull: Callable[..., dict] = pull_invoices,
        imap_timeout: float = DEFAULT_IMAP_TIMEOUT_SECONDS,
    ):
        self._start_job = start_job
        self._pull = pull
        self._imap_timeout = imap_timeout
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._thread_lock = threading.Lock()
        self._poll_lock = threading.Lock()

    def start(self) -> None:
        with self._thread_lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                name='email-poller',
                daemon=True,
            )
            self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        self._wake_event.set()
        with self._thread_lock:
            thread = self._thread
        if thread:
            thread.join(timeout)

    def wake(self) -> None:
        """通知轮询线程立即重读配置。"""
        self._wake_event.set()

    def poll_once(self) -> dict:
        """按当前配置执行一次轮询；关闭时返回空结果。"""
        if (
            self._stop_event.is_set()
            or not get_email_enabled()
            or get_email_poll_minutes() <= 0
        ):
            return {
                'downloaded': 0,
                'new_files': [],
                'errors': [],
                'total_scanned': 0,
            }
        if not self._poll_lock.acquire(blocking=False):
            return {
                'downloaded': 0,
                'new_files': [],
                'errors': ['邮箱轮询仍在进行中'],
                'total_scanned': 0,
            }
        try:
            inbox_dir = get_inbox_dir()
            config = get_email_config()
            result = self._pull(
                host=str(config['imap_host']),
                port=int(config['imap_port']),
                username=get_email_username(),
                auth_code=get_email_auth_code(),
                inbox_dir=inbox_dir,
                days_back=get_email_days_back(),
                timeout=self._imap_timeout,
            )
            if result.get('new_files') and not self._stop_event.is_set():
                try:
                    self._start_job(inbox_dir, JobTrigger.EMAIL)
                except ApplicationError as exc:
                    result = {**result, 'job_error': {
                        'code': exc.code,
                        'message': exc.message,
                    }}
            return result
        finally:
            self._poll_lock.release()

    def _run(self) -> None:
        next_poll_at = 0.0
        last_config: tuple[bool, int] | None = None
        while not self._stop_event.is_set():
            try:
                enabled = get_email_enabled()
                interval = get_email_poll_minutes()
                config_signature = (enabled, interval)
                if config_signature != last_config:
                    last_config = config_signature
                    next_poll_at = 0.0

                if not enabled or interval <= 0:
                    self._wait_for_wakeup(30.0)
                    continue

                wait_seconds = next_poll_at - time.monotonic()
                if wait_seconds > 0:
                    self._wait_for_wakeup(min(wait_seconds, 30.0))
                    continue

                try:
                    result = self.poll_once()
                    if result.get('downloaded') or result.get('errors'):
                        logger.info(
                            '邮箱自动轮询完成: 下载 %s，扫描 %s，错误 %s',
                            result.get('downloaded', 0),
                            result.get('total_scanned', 0),
                            len(result.get('errors') or []),
                        )
                    if result.get('job_error'):
                        logger.warning('邮箱附件任务启动失败: %s', result['job_error'])
                except Exception:
                    logger.exception('邮箱自动轮询失败')
                next_poll_at = time.monotonic() + interval * 60
            except Exception:
                logger.exception('读取邮箱轮询配置失败')
                self._wait_for_wakeup(30.0)

    def _wait_for_wakeup(self, timeout: float) -> None:
        self._wake_event.wait(timeout)
        self._wake_event.clear()
