from __future__ import annotations

from time import monotonic, sleep

from devbase.application.job_runtime import JobRuntime
from devbase.domain.job import JobStatus
from invoice_processor.application.invoice_task import (
    INVOICE_TOOL_KIND,
    build_invoice_registry,
)


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
    assert current.progress == 100
    assert service.calls == [("C:/invoices", "email")]
