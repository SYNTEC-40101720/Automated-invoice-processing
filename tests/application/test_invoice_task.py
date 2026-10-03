from __future__ import annotations

from time import monotonic, sleep

import pytest
from devbase.application.job_runtime import JobRuntime
from devbase.domain.job import JobStatus
from invoice_processor.application.invoice_task import (
    INVOICE_TOOL_KIND,
    build_invoice_registry,
    validate_start_input,
)
from invoice_processor.domain.errors import NoPdfFiles


class FakeInvoiceService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def run_job_sync(
        self,
        source_dir,
        trigger,
        *,
        job_id,
        cancellation_event,
        progress_callback,
    ):
        self.calls.append((source_dir, trigger.value))
        progress_callback(1.0, "处理完成")
        return {
            "status": "succeeded",
            "message": "处理完成",
            "error_message": None,
        }


def wait_for_terminal(runtime: JobRuntime) -> None:
    deadline = monotonic() + 2
    while monotonic() < deadline:
        job = runtime.current_job()
        if job is not None and job.status.is_terminal:
            return
        sleep(0.005)
    raise AssertionError("invoice task did not become terminal")


def test_invoice_task_receives_runtime_input() -> None:
    service = FakeInvoiceService()
    runtime = JobRuntime(registry=build_invoice_registry(service))

    started = runtime.start(
        INVOICE_TOOL_KIND,
        input={"source_dir": "C:/invoices", "trigger": "email"},
    )
    wait_for_terminal(runtime)

    current = runtime.current_job()
    assert current is not None
    assert current.job_id == started.job_id
    assert current.status is JobStatus.SUCCEEDED
    assert current.progress == 1.0
    assert service.calls == [("C:/invoices", "email")]


def test_validate_start_input_excludes_settlement_statements(tmp_path) -> None:
    """源目录只有结账单 PDF 时，预检视为无可处理文件（NO_PDF_FILES）"""
    (tmp_path / "华住结账单.pdf").write_bytes(b"%PDF")

    with pytest.raises(NoPdfFiles):
        validate_start_input({"source_dir": str(tmp_path)})


def test_validate_start_input_mixed_with_settlement_statements(tmp_path) -> None:
    """结账单与正常发票混放时预检通过（排除不影响其余 PDF）"""
    (tmp_path / "华住结账单.pdf").write_bytes(b"%PDF")
    (tmp_path / "invoice-a.pdf").write_bytes(b"%PDF")

    validate_start_input({"source_dir": str(tmp_path)})
