"""launcher 关窗等待逻辑测试：shutdown 后任务终态收敛再退出。

运行方式: pytest tests/application/test_launcher_wait.py -v
"""
from __future__ import annotations

import threading
import time

from invoice_processor.desktop.launcher import _wait_job_terminal
from test_job_service import FakeProcessor, make_service, make_source


class BlockingPostProcessProcessor(FakeProcessor):
    """post_process 挂起直到 release，模拟 Excel 写入进行中关窗"""

    def __init__(self):
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def post_process(self, output_dir, progress_callback=None):
        self.started.set()
        self.release.wait(timeout=5)
        return super().post_process(output_dir, progress_callback)


def _run_job_async(service, source):
    worker = threading.Thread(target=lambda: service.run_job_sync(str(source)))
    worker.start()
    return worker


def test_wait_job_terminal_returns_immediately_when_idle(tmp_path):
    """无运行任务时立即返回"""
    service, _ = make_service(tmp_path)
    _wait_job_terminal(service, timeout=1.0)


def test_wait_job_terminal_blocks_until_running_job_finishes(tmp_path):
    """关窗时任务仍在 post_process → 等待其完成后才返回"""
    processor = BlockingPostProcessProcessor()
    service, _ = make_service(tmp_path, processor=processor)
    source = make_source(tmp_path)
    worker = _run_job_async(service, source)

    finished = threading.Event()

    def wait_thread():
        _wait_job_terminal(service, timeout=10.0)
        finished.set()

    try:
        assert processor.started.wait(timeout=5)
        waiter = threading.Thread(target=wait_thread)
        waiter.start()

        # 任务尚未终态：等待者不应提前返回
        assert not finished.wait(timeout=0.5)
        # 释放 post_process → 任务到达终态 → 等待者返回
        processor.release.set()
        assert finished.wait(timeout=5)
    finally:
        processor.release.set()
        worker.join(timeout=5)
        waiter.join(timeout=5)


def test_wait_job_terminal_times_out_on_stuck_job(tmp_path):
    """任务卡死不收敛 → 达到 timeout 后照常返回（不引入关不掉的新问题）"""
    processor = BlockingPostProcessProcessor()
    service, _ = make_service(tmp_path, processor=processor)
    source = make_source(tmp_path)
    worker = _run_job_async(service, source)

    try:
        assert processor.started.wait(timeout=5)
        begin = time.monotonic()
        _wait_job_terminal(service, timeout=0.3)
        elapsed = time.monotonic() - begin
        # 超时后返回而不是永久阻塞（宽松上界，防 CI 抖动误报）
        assert elapsed < 5
    finally:
        processor.release.set()
        worker.join(timeout=5)
