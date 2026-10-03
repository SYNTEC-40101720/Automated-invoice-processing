"""JobService 应用编排测试。

融合二期后 JobService 不再持有 worker 线程：生产路径由 DevBase
runtime 的线程经 ``run_job_sync`` 驱动。本文件直调 ``run_job_sync``
复现同一入口（同步阻塞直到终态），等价于宿主线程驱动。
"""

from __future__ import annotations

import os
import threading

import pytest
from devbase.application.event_bus import EventBus
from invoice_processor.application.invoice_file_service import FileProcessResult
from invoice_processor.application.job_service import JobService
from invoice_processor.domain.errors import JobAlreadyRunning, NoPdfFiles
from invoice_processor.domain.job import JobStatus, JobTrigger


class FakeProcessor:
    def __init__(self):
        self.reset_called = False
        self.clear_called = False
        self.files = []

    def create_output_directory(self, source_dir):
        output_dir = os.path.join(source_dir, 'output')
        os.makedirs(output_dir, exist_ok=True)
        return output_dir

    def reset_dedup(self):
        self.reset_called = True

    def clear_cache(self):
        self.clear_called = True

    def post_process(self, output_dir, progress_callback=None):
        if progress_callback:
            progress_callback(0.0)
            progress_callback(1.0)
        return {
            'amount_map': {'100.00': 'INV-1'},
            'tax_issues': [],
            'merged': os.path.join(output_dir, '合并结果.pdf'),
            'excel': None,
        }


class FakeFileService:
    def __init__(self, processor):
        self.processor = processor

    def process_file(self, filename, source_dir, output_dir, is_cancelled):
        if is_cancelled():
            return FileProcessResult(filename, None, 'warning', '已取消', 'cancelled')
        self.processor.files.append(filename)
        return FileProcessResult(
            filename, None, 'success', f'成功: {filename}', 'success'
        )


class FakeAuditService:
    def __init__(self, processor, log_callback=None):
        self.log_callback = log_callback

    def run(self, output_dir):
        if self.log_callback:
            self.log_callback('本地规则预检：未发现问题', 'success')
        return {'local_findings': [], 'ai_findings': [], 'report': None}


def make_service(tmp_path, event_bus=None, processor=None):
    processor = processor or FakeProcessor()

    def processor_factory():
        return processor

    return JobService(
        event_bus=event_bus,
        processor_factory=processor_factory,
        max_workers_provider=lambda: 2,
        audit_service_factory=FakeAuditService,
        file_service_factory=FakeFileService,
    ), processor


def make_source(tmp_path, count=2):
    source = tmp_path / 'source'
    source.mkdir()
    for index in range(count):
        (source / f'invoice-{index}.pdf').write_bytes(b'pdf')
    return source


def test_known_directory_includes_configured_inbox(tmp_path, monkeypatch):
    inbox = tmp_path / 'inbox'
    inbox.mkdir()
    monkeypatch.setattr(
        'invoice_processor.application.job_service.get_inbox_dir',
        lambda: str(inbox),
    )
    service, _ = make_service(tmp_path)

    assert service.is_known_directory(str(inbox)) is True
    assert service.is_known_directory(str(tmp_path / 'other')) is False


def test_known_directory_includes_inbox_pull_batches(tmp_path, monkeypatch):
    """收件根目录下的拉取批次子目录同样放行（打开目录校验）"""
    inbox = tmp_path / 'inbox'
    batch = inbox / '拉取_20261002_120000'
    batch.mkdir(parents=True)
    monkeypatch.setattr(
        'invoice_processor.application.job_service.get_inbox_dir',
        lambda: str(inbox),
    )
    service, _ = make_service(tmp_path)

    assert service.is_known_directory(str(batch)) is True
    # 深于一层（批次的子目录）不放行
    nested = batch / 'sub'
    nested.mkdir()
    assert service.is_known_directory(str(nested)) is False


def test_job_service_runs_pipeline_and_publishes_terminal_snapshot(tmp_path):
    event_bus = EventBus()
    service, processor = make_service(tmp_path, event_bus)
    source = make_source(tmp_path)

    final = service.run_job_sync(str(source))

    assert final['status'] == JobStatus.SUCCEEDED.value
    assert final['progress'] == 1.0
    assert final['stats']['success'] == 2
    assert processor.reset_called is True
    assert processor.clear_called is True
    assert processor.files == ['invoice-0.pdf', 'invoice-1.pdf']
    assert any(event.type == 'job.completed' for event in event_bus.history())


def test_run_job_sync_runs_pipeline_for_host_runtime(tmp_path):
    service, processor = make_service(tmp_path)
    source = make_source(tmp_path)
    progress = []

    result = service.run_job_sync(
        str(source),
        job_id='runtime-job',
        progress_callback=lambda ratio, message: progress.append((ratio, message)),
    )

    assert result['status'] == JobStatus.SUCCEEDED.value
    assert result['id'] == 'runtime-job'
    assert result['stats']['success'] == 2
    assert progress
    assert progress[-1][0] == 1.0
    assert processor.clear_called is True


def test_processor_factory_failure_marks_job_failed(tmp_path):
    source = make_source(tmp_path, count=1)

    def failing_factory():
        raise RuntimeError('processor unavailable')

    service = JobService(
        processor_factory=failing_factory,
        max_workers_provider=lambda: 2,
    )
    final = service.run_job_sync(str(source))

    assert final['status'] == JobStatus.FAILED.value
    assert final['error_code'] == 'INTERNAL_ERROR'
    assert 'processor unavailable' in final['error_message']


def test_inbox_job_archives_only_initial_pdf_files(tmp_path):
    service, _ = make_service(tmp_path)
    source = make_source(tmp_path, count=1)
    final = service.run_job_sync(str(source), JobTrigger.INBOX)

    assert final['status'] == JobStatus.SUCCEEDED.value
    assert final['result']['archived'] == 1
    assert (source / '已处理' / 'invoice-0.pdf').is_file()


def test_start_job_rejects_empty_source_and_running_conflict(tmp_path):
    empty = tmp_path / 'empty'
    empty.mkdir()

    started = threading.Event()
    release = threading.Event()

    class BlockingProcessor(FakeProcessor):
        def post_process(self, output_dir, progress_callback=None):
            started.set()
            release.wait(timeout=5)
            return super().post_process(output_dir, progress_callback)

    service, _ = make_service(tmp_path, processor=BlockingProcessor())
    with pytest.raises(NoPdfFiles):
        service.run_job_sync(str(empty))

    source = make_source(tmp_path)
    worker = threading.Thread(
        target=lambda: service.run_job_sync(str(source)), daemon=True,
    )
    worker.start()
    try:
        assert started.wait(timeout=5)
        with pytest.raises(JobAlreadyRunning):
            service.run_job_sync(str(source))
        current = service.current_job()
        service.cancel_job(current['id'])
    finally:
        release.set()
        worker.join(timeout=5)


def test_cancelled_job_does_not_run_post_process(tmp_path):
    class SlowProcessor(FakeProcessor):
        # reset_dedup 在处理线程池启动前执行：到达即发信号，随后挂起，
        # 保证取消发生在文件处理阶段内、后处理开始前。
        def reset_dedup(self):
            in_process.set()
            resume.wait(timeout=5)
            super().reset_dedup()

        def post_process(self, output_dir, progress_callback=None):
            raise AssertionError('取消后不应执行后处理')

    in_process = threading.Event()
    resume = threading.Event()
    service, _ = make_service(tmp_path, processor=SlowProcessor())
    source = make_source(tmp_path, count=4)
    worker = threading.Thread(
        target=lambda: service.run_job_sync(str(source)), daemon=True,
    )
    worker.start()
    # 等待进入文件处理阶段（reset_dedup 已到达）后再取消，取消后放行
    assert in_process.wait(timeout=5), '任务未进入处理阶段'
    current = service.current_job()
    service.cancel_job(current['id'])
    resume.set()
    worker.join(timeout=5)
    final = service.get_job(current['id'])
    assert final['status'] == JobStatus.CANCELLED.value


def test_cancel_during_post_process_skips_audit_and_archive(tmp_path):
    post_started = threading.Event()
    release_post = threading.Event()
    audit_calls = []

    class BlockingProcessor(FakeProcessor):
        def post_process(self, output_dir, progress_callback=None):
            post_started.set()
            release_post.wait(timeout=5)
            return super().post_process(output_dir, progress_callback)

    processor = BlockingProcessor()
    service = JobService(
        processor_factory=lambda: processor,
        max_workers_provider=lambda: 2,
        audit_service_factory=lambda *args, **kwargs: (
            audit_calls.append(True) or FakeAuditService(*args, **kwargs)
        ),
        file_service_factory=FakeFileService,
    )
    source = make_source(tmp_path, count=1)
    worker = threading.Thread(
        target=lambda: service.run_job_sync(str(source), JobTrigger.EMAIL),
        daemon=True,
    )
    worker.start()

    assert post_started.wait(timeout=5)
    current = service.current_job()
    service.cancel_job(current['id'])
    release_post.set()
    worker.join(timeout=5)
    final = service.get_job(current['id'])

    assert final['status'] == JobStatus.CANCELLED.value
    assert audit_calls == []
    assert (source / 'invoice-0.pdf').is_file()


def test_job_service_excludes_settlement_statements_from_scan_and_archive(tmp_path):
    """结账单 PDF 不计入扫描/处理，inbox 归档也不移动它"""
    service, processor = make_service(tmp_path)
    source = make_source(tmp_path, count=1)
    (source / '华住结账单.pdf').write_bytes(b'%PDF')

    scanned = service.scan_directory(str(source))
    assert scanned['pdf_count'] == 1

    final = service.run_job_sync(str(source), JobTrigger.INBOX)

    assert final['status'] == JobStatus.SUCCEEDED.value
    assert final['stats']['total'] == 1
    assert processor.files == ['invoice-0.pdf']
    # 归档只移动处理清单内的文件；结账单留在源目录原位
    assert (source / '华住结账单.pdf').is_file()
    assert not (source / '已处理' / '华住结账单.pdf').exists()
