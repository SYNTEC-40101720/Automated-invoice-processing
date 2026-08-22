"""邮箱自动轮询调度器

职责：根据 config.ini [email] 的 enabled + poll_minutes，在后台定时拉取发票邮件。
- 不依赖 Qt/WebView，纯线程实现；
- 启动/停止由 desktop launcher 控制；
- 拉取到新文件时，调用 JobService.start_job 自动进入处理队列。
"""
from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING

from ..config_manager import (
    get_email_auth_code,
    get_email_config,
    get_email_days_back,
    get_email_enabled,
    get_email_poll_minutes,
    get_email_username,
    get_inbox_dir,
)
from ..core.email_pull import pull_invoices
from ..domain.job import JobTrigger

if TYPE_CHECKING:
    from ..application.job_service import JobService

logger = logging.getLogger(__name__)

_MIN_POLL_MINUTES = 1
_DEFAULT_POLL_MINUTES = 30


class EmailPoller:
    """后台邮件轮询器"""

    def __init__(self, job_service: 'JobService'):
        self._service = job_service
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    def start(self) -> None:
        """启动轮询线程；若已运行则忽略。"""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._loop,
                name='email-poller',
                daemon=True,
            )
            self._thread.start()
            logger.info('邮箱自动轮询已启动')

    def stop(self, timeout: float = 5.0) -> None:
        """请求停止轮询线程并等待退出。"""
        self._stop_event.set()
        with self._lock:
            thread = self._thread
        if thread:
            thread.join(timeout)
            logger.info('邮箱自动轮询已停止')

    def is_running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def _loop(self) -> None:
        """主循环：按配置间隔拉取邮件。"""
        # 启动后立即执行一次，保证开机即用
        self._tick()

        while not self._stop_event.is_set():
            interval = self._interval_seconds()
            # 等待期间若配置改变，下次循环重新读取
            if self._stop_event.wait(interval):
                return
            if not get_email_enabled():
                continue
            self._tick()

    def _interval_seconds(self) -> float:
        minutes = get_email_poll_minutes()
        if minutes < _MIN_POLL_MINUTES:
            # 未启用或间隔非法时，使用默认间隔避免忙等
            return _DEFAULT_POLL_MINUTES * 60
        return minutes * 60

    def _tick(self) -> None:
        """单次拉取：只有启用且配置完整才执行；失败只记录日志不阻塞。"""
        if not get_email_enabled():
            return

        config = get_email_config()
        username = get_email_username()
        auth_code = get_email_auth_code()
        if not username or not auth_code:
            logger.debug('邮箱未配置账号或授权码，跳过本次轮询')
            return

        try:
            result = pull_invoices(
                host=str(config['imap_host']),
                port=int(config['imap_port']),
                username=username,
                auth_code=auth_code,
                inbox_dir=get_inbox_dir(),
                days_back=get_email_days_back(),
            )
            logger.info(
                '邮箱轮询完成: scanned=%s downloaded=%s errors=%s',
                result.get('total_scanned', 0),
                result.get('downloaded', 0),
                len(result.get('errors', [])),
            )
            if result.get('new_files'):
                try:
                    self._service.start_job(get_inbox_dir(), JobTrigger.EMAIL)
                except Exception as exc:
                    logger.warning('自动拉取后启动处理任务失败: %s', exc)
        except Exception as exc:
            logger.warning('邮箱轮询失败: %s', exc)
