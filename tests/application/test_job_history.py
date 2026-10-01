"""跨启动处理历史测试：store 落盘语义 + JobService 终态旁路集成。"""

from __future__ import annotations

import json

from devbase.application.event_bus import EventBus
from invoice_processor.application.job_history import (
    DEFAULT_LIMIT,
    JobHistoryStore,
)
from invoice_processor.application.job_service import JobService
from invoice_processor.domain.job import JobStatus
from test_job_service import (
    FakeAuditService,
    FakeFileService,
    FakeProcessor,
    make_source,
)


def make_history_service(tmp_path):
    store = JobHistoryStore(tmp_path / "job_history.jsonl")
    service = JobService(
        event_bus=EventBus(),
        processor_factory=FakeProcessor,
        max_workers_provider=lambda: 2,
        audit_service_factory=FakeAuditService,
        file_service_factory=FakeFileService,
        job_history_store=store,
    )
    return service, store


def test_append_writes_snapshot_fields_and_dedup(tmp_path):
    store = JobHistoryStore(tmp_path / "history.jsonl")
    snapshot = {
        "id": "job-1",
        "job_id": "job-1",
        "source_dir": "C:/inbox",
        "output_dir": "C:/inbox/output",
        "trigger": "manual",
        "status": "succeeded",
        "stats": {"total": 2, "success": 2, "failure": 0, "tax_issues": 0},
        "started_at": "2026-10-01T00:00:00",
        "finished_at": "2026-10-01T00:01:00",
        "error_code": None,
        "error_message": None,
        "progress": 1.0,
        "message": "处理完成",
        "result": {"merged": "x.pdf"},
    }

    store.append(snapshot)
    store.append(snapshot)  # 同 job_id 幂等

    entries = store.list()
    assert len(entries) == 1
    entry = entries[0]
    assert entry["job_id"] == "job-1"
    assert entry["status"] == "succeeded"
    # 只存挑选字段：result/progress/message 不落盘
    assert "result" not in entry
    assert "progress" not in entry
    # 落盘是 JSON Lines（一行一条，UTF-8）
    lines = (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["job_id"] == "job-1"


def test_append_skips_snapshot_without_job_id(tmp_path):
    store = JobHistoryStore(tmp_path / "history.jsonl")
    store.append({"status": "succeeded"})
    assert store.list() == []
    assert not (tmp_path / "history.jsonl").exists()


def test_list_tolerates_missing_file_and_corrupt_lines(tmp_path):
    store = JobHistoryStore(tmp_path / "history.jsonl")
    assert store.list() == []

    store.append({"job_id": "job-1"})
    # 模拟历史截断：追加一行非法 JSON
    with open(store.path, "a", encoding="utf-8") as file:
        file.write('{"job_id": "broken\n')
    store.append({"job_id": "job-2"})

    entries = store.list()
    assert [entry["job_id"] for entry in entries] == ["job-1", "job-2"]


def test_store_trims_to_limit(tmp_path):
    store = JobHistoryStore(tmp_path / "history.jsonl", limit=3)
    for index in range(6):
        store.append({"job_id": f"job-{index}"})

    entries = store.list()
    assert [entry["job_id"] for entry in entries] == ["job-3", "job-4", "job-5"]


def test_store_limit_floor_is_one(tmp_path):
    store = JobHistoryStore(tmp_path / "history.jsonl", limit=0)
    store.append({"job_id": "job-1"})
    store.append({"job_id": "job-2"})
    assert [entry["job_id"] for entry in store.list()] == ["job-2"]


def test_store_default_limit_is_50(tmp_path):
    assert DEFAULT_LIMIT == 50
    store = JobHistoryStore(tmp_path / "history.jsonl")
    for index in range(52):
        store.append({"job_id": f"job-{index}"})
    entries = store.list()
    assert len(entries) == 50
    assert entries[0]["job_id"] == "job-2"


def test_service_records_terminal_job_across_restart(tmp_path):
    service, store = make_history_service(tmp_path)
    source = make_source(tmp_path, count=2)

    final = service.run_job_sync(str(source))

    assert final["status"] == JobStatus.SUCCEEDED.value
    entries = store.list()
    assert len(entries) == 1
    assert entries[0]["job_id"] == final["id"]
    assert entries[0]["status"] == "succeeded"
    assert entries[0]["stats"]["success"] == 2
    assert entries[0]["output_dir"] == final["output_dir"]

    # 「重启」：新服务实例指向同一历史文件，历史可读回
    restarted, _restored_store = make_history_service(tmp_path)
    assert restarted.job_history_entries()[0]["job_id"] == final["id"]


def test_service_without_store_disables_history(tmp_path):
    service = JobService(
        processor_factory=FakeProcessor,
        max_workers_provider=lambda: 2,
        file_service_factory=FakeFileService,
    )
    source = make_source(tmp_path, count=1)
    final = service.run_job_sync(str(source))

    # 无 store 时终态落不到历史，且接口返回空而非报错
    assert final["status"] in (
        JobStatus.SUCCEEDED.value,
        JobStatus.COMPLETED_WITH_WARNINGS.value,
    )
    assert service.job_history_entries() == []


def test_is_known_directory_matches_history_output_dir(tmp_path):
    service, _store = make_history_service(tmp_path)
    source = make_source(tmp_path, count=1)
    final = service.run_job_sync(str(source))

    assert service.is_known_directory(str(source / "output")) is True

    # 「重启」后内存 handles 已空，历史中的输出目录仍放行（供打开输出目录回溯）
    restarted, _restored_store = make_history_service(tmp_path)
    assert restarted.is_known_directory(final["output_dir"]) is True
    assert restarted.is_known_directory(str(tmp_path / "other")) is False


def test_cancelled_job_lands_in_history_with_cancelled_status(tmp_path):
    # 任意终态（succeeded 之外的 failed/cancelled 同样落历史）：
    # processor 工厂抛错 → INTERNAL_ERROR → FAILED 终态旁路落盘。
    service, store = make_history_service(tmp_path)
    source = make_source(tmp_path, count=1)

    def failing_factory():
        raise RuntimeError("processor unavailable")

    service._processor_factory = failing_factory
    final = service.run_job_sync(str(source), job_id="failed-job")

    assert final["status"] == JobStatus.FAILED.value
    entries = store.list()
    assert [entry["job_id"] for entry in entries] == ["failed-job"]
    assert entries[0]["status"] == "failed"
    assert entries[0]["error_code"] == "INTERNAL_ERROR"
