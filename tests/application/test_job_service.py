"""JobService 应用编排测试。

融合二期后 JobService 不再持有 worker 线程：生产路径由 DevBase
runtime 的线程经 ``run_job_sync`` 驱动。本文件直调 ``run_job_sync``
复现同一入口（同步阻塞直到终态），等价于宿主线程驱动。
"""

from __future__ import annotations

import os
import threading
from datetime import datetime

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

    def post_process(self, output_dir, progress_callback=None,
                     daily_manual_totals=None):
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
        # 内容按序号差异化：全局内容去重会把同内容文件判为重复，
        # 既有测试假定每份文件都被处理，因此这里必须各不相同
        (source / f'invoice-{index}.pdf').write_bytes(f'pdf-{index}'.encode())
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


def test_scan_inbox_lists_root_files_and_batch_overview(tmp_path, monkeypatch):
    """收件扫描：待处理清单覆盖根目录散放+批次子目录，批次另给概览"""
    inbox = tmp_path / 'inbox'
    inbox.mkdir()
    (inbox / '散放发票.pdf').write_bytes(b'pdf')
    (inbox / '结账单.pdf').write_bytes(b'pdf')
    batch = inbox / '拉取_20261002_120000'
    batch.mkdir()
    (batch / '附件1.pdf').write_bytes(b'pdf')
    (batch / '附件2.pdf').write_bytes(b'pdf')
    (batch / '说明.txt').write_text('not a pdf')
    archived = inbox / '已处理'
    archived.mkdir()
    (archived / 'old.pdf').write_bytes(b'pdf')
    monkeypatch.setattr(
        'invoice_processor.application.job_service.get_inbox_dir',
        lambda: str(inbox),
    )
    service, _ = make_service(tmp_path)

    result = service.scan_inbox()

    assert result['inbox_dir'] == os.path.realpath(str(inbox))
    # 结账单命中排除关键词，不进入待处理清单；批次文件带一层目录前缀
    assert result['pending_files'] == [
        '散放发票.pdf',
        os.path.join('拉取_20261002_120000', '附件1.pdf'),
        os.path.join('拉取_20261002_120000', '附件2.pdf'),
    ]
    assert result['pending_count'] == 3
    # 已处理 目录不作为批次；批次只统计 PDF 数，不递归展开清单
    assert [(entry['name'], entry['pdf_count']) for entry in result['batches']] == [
        ('拉取_20261002_120000', 2)
    ]
    assert result['batches'][0]['path'] == os.path.join(
        result['inbox_dir'], '拉取_20261002_120000'
    )


def test_scan_inbox_ignores_timestamp_output_directories(tmp_path, monkeypatch):
    """收件根目录下的历史输出目录（时间戳命名）不算待处理也不算批次"""
    inbox = tmp_path / 'inbox'
    inbox.mkdir()
    (inbox / '待处理.pdf').write_bytes(b'pdf')
    output = inbox / '20261026_180553_123456'
    output.mkdir()
    (output / '历史输出.pdf').write_bytes(b'pdf')
    monkeypatch.setattr(
        'invoice_processor.application.job_service.get_inbox_dir',
        lambda: str(inbox),
    )
    service, _ = make_service(tmp_path)

    result = service.scan_inbox()

    assert result['pending_files'] == ['待处理.pdf']
    assert result['pending_count'] == 1
    assert result['batches'] == []


def test_inbox_root_job_processes_batch_files_and_archives_per_directory(
    tmp_path, monkeypatch
):
    """收件根目录整体任务：批次子目录文件一并处理，归档回各自目录"""
    inbox = tmp_path / 'inbox'
    inbox.mkdir()
    (inbox / '散放发票.pdf').write_bytes(b'pdf')
    batch = inbox / '拉取_20261002_120000'
    batch.mkdir()
    (batch / '附件1.pdf').write_bytes(b'pdf')
    (batch / '附件2.pdf').write_bytes(b'pdf')
    monkeypatch.setattr(
        'invoice_processor.application.job_service.get_inbox_dir',
        lambda: str(inbox),
    )
    service, processor = make_service(tmp_path)

    final = service.run_job_sync(str(inbox), JobTrigger.INBOX)

    assert final['status'] == JobStatus.SUCCEEDED.value
    assert final['stats']['total'] == 3
    # 批次文件以相对路径进入处理清单（真实文件服务按 source_dir 拼接定位）
    assert sorted(processor.files) == [
        os.path.join('拉取_20261002_120000', '附件1.pdf'),
        os.path.join('拉取_20261002_120000', '附件2.pdf'),
        '散放发票.pdf',
    ]
    assert final['result']['archived'] == 3
    # 根文件归档到根目录「已处理」，批次文件归档到各自批次目录
    assert (inbox / '已处理' / '散放发票.pdf').is_file()
    assert (batch / '已处理' / '附件1.pdf').is_file()
    assert (batch / '已处理' / '附件2.pdf').is_file()
    assert not (inbox / '散放发票.pdf').exists()
    assert not (batch / '附件1.pdf').exists()


def test_scan_inbox_tolerates_missing_inbox_directory(tmp_path, monkeypatch):
    """收件目录不存在（未配置/已删除）返回空收件箱而不是报错"""
    monkeypatch.setattr(
        'invoice_processor.application.job_service.get_inbox_dir',
        lambda: str(tmp_path / '不存在的收件箱'),
    )
    service, _ = make_service(tmp_path)

    result = service.scan_inbox()

    assert result['pending_count'] == 0
    assert result['pending_files'] == []
    assert result['batches'] == []


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


def test_ledger_appended_on_success(tmp_path):
    """成功终态在输出目录上级追加台账行，缺失合计列填 0（openpyxl 可用）"""
    openpyxl = pytest.importorskip('openpyxl')
    service, _ = make_service(tmp_path)
    source = make_source(tmp_path)

    final = service.run_job_sync(str(source))

    assert final['status'] == JobStatus.SUCCEEDED.value
    # 台账与输出目录同级：FakeProcessor 输出 tmp_path/source/output
    ledger = tmp_path / 'source' / '发票打印汇总档案.xlsx'
    assert ledger.is_file()
    ws = openpyxl.load_workbook(ledger).active
    rows = list(ws.iter_rows(values_only=True))
    assert rows[0][:10] == (
        '任务编号', '完成时间', '输出目录', '发票总数', '成功', '失败',
        '跳过重复', '交通费', '私车补贴', '住宿费',
    )
    data = rows[1]
    assert data[0] == final['id']
    assert data[3] == 2 and data[4] == 2 and data[5] == 0
    assert data[7] == 0  # transport 合计缺失时落 0
    assert data[8] == 0 and data[9] == 0 and data[10] == 0
    # 完成时间应为本地日期（当天），证明不再是 UTC（早 8 小时会落在昨天）
    assert data[1].startswith(datetime.now().strftime('%Y-%m-%d'))


def test_ledger_failure_does_not_break_job(tmp_path, monkeypatch, caplog):
    """台账写盘抛错只记 warning，任务仍成功"""
    service, _ = make_service(tmp_path)
    source = make_source(tmp_path)

    import invoice_processor.application.job_service as js

    real_isfile = js.os.path.isfile

    def flaky_isfile(path):
        # 只对台账文件名命中时抛错，避免打断其他 isfile 调用
        if str(path).endswith('发票打印汇总档案.xlsx'):
            raise RuntimeError('disk full')
        return real_isfile(path)

    monkeypatch.setattr(js.os.path, 'isfile', flaky_isfile)

    with caplog.at_level('WARNING'):
        final = service.run_job_sync(str(source))

    assert final['status'] == JobStatus.SUCCEEDED.value
    assert any('归档台账写入失败' in rec.message for rec in caplog.records)


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
        def post_process(self, output_dir, progress_callback=None,
                     daily_manual_totals=None):
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

        def post_process(self, output_dir, progress_callback=None,
                     daily_manual_totals=None):
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
        def post_process(self, output_dir, progress_callback=None,
                     daily_manual_totals=None):
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


def _write_pdf(path, data: bytes):
    path.write_bytes(data)
    return path


def test_job_service_dedup_skips_same_content_pdf_in_same_batch(tmp_path):
    """同批两份同内容 PDF：第二份命中全局索引，跳过处理留在原地"""
    from invoice_processor.core.duplicate_check import (
        DuplicateIndex,
        compute_sha256,
    )

    index = DuplicateIndex(tmp_path / 'logs' / 'duplicate_index.json')
    index.load()
    service, processor = make_service(tmp_path)
    service._duplicate_index = index
    source = make_source(tmp_path, count=1)
    _write_pdf(source / 'invoice-0-copy.pdf', b'pdf-0')

    final = service.run_job_sync(str(source), JobTrigger.INBOX)

    assert final['status'] == JobStatus.SUCCEEDED.value
    assert final['stats']['duplicates'] == 1
    assert final['stats']['success'] == 1
    # 处理清单按文件名排序，'invoice-0-copy.pdf' < 'invoice-0.pdf'：
    # 排序靠前的先处理入索引，另一份命中后跳过
    assert processor.files == ['invoice-0-copy.pdf']
    # 重复的那份既不处理也不归档，留在原地
    assert (source / 'invoice-0.pdf').is_file()
    assert not (source / '已处理' / 'invoice-0.pdf').exists()
    index.save()
    reloaded = DuplicateIndex(tmp_path / 'logs' / 'duplicate_index.json')
    reloaded.load()
    assert reloaded.contains(
        compute_sha256(source / 'invoice-0.pdf')
    )


def test_job_service_dedup_blocks_same_content_across_jobs(tmp_path):
    """跨任务重复：第二个任务命中索引，不再处理同内容文件"""
    from invoice_processor.core.duplicate_check import DuplicateIndex, compute_sha256

    index = DuplicateIndex(tmp_path / 'logs' / 'duplicate_index.json')
    index.load()
    service, processor = make_service(tmp_path)
    service._duplicate_index = index
    source = make_source(tmp_path, count=1)

    first = service.run_job_sync(str(source), JobTrigger.INBOX)
    assert first['stats']['duplicates'] == 0
    assert processor.files == ['invoice-0.pdf']

    # 第二个任务：同一份内容（同名重建）再次提交
    _write_pdf(source / 'invoice-0.pdf', b'pdf-0')
    second = service.run_job_sync(str(source), JobTrigger.INBOX)

    assert second['status'] == JobStatus.SUCCEEDED.value
    assert second['stats']['duplicates'] == 1
    assert second['stats']['success'] == 0
    assert processor.files == ['invoice-0.pdf']  # 没有新增处理
    assert compute_sha256(source / 'invoice-0.pdf') in index._entries


def test_job_service_without_index_keeps_legacy_behavior(tmp_path):
    """未注入 duplicate_index（生产接线前/单测默认）→ 无去重语义"""
    service, processor = make_service(tmp_path)
    source = make_source(tmp_path, count=2)

    final = service.run_job_sync(str(source), JobTrigger.INBOX)

    assert final['stats']['duplicates'] == 0
    assert final['stats']['success'] == 2
    assert processor.files == ['invoice-0.pdf', 'invoice-1.pdf']
