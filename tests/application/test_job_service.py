"""JobService 应用编排测试。"""

from __future__ import annotations

import os
import threading

import pytest

from src.application.event_bus import EventBus
from src.application.invoice_file_service import FileProcessResult
from src.application.job_service import JobService
from src.domain.errors import JobAlreadyRunning, NoPdfFiles
from src.domain.job import JobStatus, JobTrigger


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
    monkeypatch.setattr('src.application.job_service.get_inbox_dir', lambda: str(inbox))
    service, _ = make_service(tmp_path)

    assert service.is_known_directory(str(inbox)) is True
    assert service.is_known_directory(str(tmp_path / 'other')) is False


def test_job_service_runs_pipeline_and_publishes_terminal_snapshot(tmp_path):
    event_bus = EventBus()
    service, processor = make_service(tmp_path, event_bus)
    source = make_source(tmp_path)

    snapshot = service.start_job(str(source))
    final = service.wait_for_job(snapshot['id'], timeout=5)

    assert final['status'] == JobStatus.SUCCEEDED.value
    assert final['progress'] == 1.0
    assert final['stats']['success'] == 2
    assert processor.reset_called is True
    assert processor.clear_called is True
    assert processor.files == ['invoice-0.pdf', 'invoice-1.pdf']
    assert any(event.type == 'job.completed' for event in event_bus.history())


def test_processor_factory_failure_marks_job_failed(tmp_path):
    source = make_source(tmp_path, count=1)

    def failing_factory():
        raise RuntimeError('processor unavailable')

    service = JobService(
        processor_factory=failing_factory,
        max_workers_provider=lambda: 2,
    )
    snapshot = service.start_job(str(source))
    final = service.wait_for_job(snapshot['id'], timeout=5)

    assert final['status'] == JobStatus.FAILED.value
    assert final['error_code'] == 'INTERNAL_ERROR'
    assert 'processor unavailable' in final['error_message']


def test_inbox_job_archives_only_initial_pdf_files(tmp_path):
    service, _ = make_service(tmp_path)
    source = make_source(tmp_path, count=1)
    snapshot = service.start_job(str(source), JobTrigger.INBOX)
    final = service.wait_for_job(snapshot['id'], timeout=5)

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
        service.start_job(str(empty))

    source = make_source(tmp_path)
    first = service.start_job(str(source))
    try:
        assert started.wait(timeout=5)
        with pytest.raises(JobAlreadyRunning):
            service.start_job(str(source))
        service.cancel_job(first['id'])
    finally:
        release.set()
        service.wait_for_job(first['id'], timeout=5)


def test_cancelled_job_does_not_run_post_process(tmp_path):
    class SlowProcessor(FakeProcessor):
        def post_process(self, output_dir, progress_callback=None):
            raise AssertionError('取消后不应执行后处理')

    service, _ = make_service(tmp_path, processor=SlowProcessor())
    source = make_source(tmp_path, count=4)
    snapshot = service.start_job(str(source))
    service.cancel_job(snapshot['id'])
    final = service.wait_for_job(snapshot['id'], timeout=5)
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
    snapshot = service.start_job(str(source), JobTrigger.EMAIL)

    assert post_started.wait(timeout=5)
    service.cancel_job(snapshot['id'])
    release_post.set()
    final = service.wait_for_job(snapshot['id'], timeout=5)

    assert final['status'] == JobStatus.CANCELLED.value
    assert audit_calls == []
    assert (source / 'invoice-0.pdf').is_file()
