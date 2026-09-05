"""将发票流水线接入 DevBase 任务清单。"""

from __future__ import annotations

from typing import Any

from devbase.application.manifest import ToolDescriptor, ToolRegistry
from devbase.application.task import TaskContext

from ..domain.job import JobTrigger
from .job_service import JobService


INVOICE_TOOL_KIND = "invoice_processing"


def run_invoice_pipeline(
    ctx: TaskContext,
    *,
    service: JobService,
    source_dir: str,
    trigger: str = JobTrigger.MANUAL.value,
) -> dict[str, Any]:
    """Run the existing invoice pipeline inside the DevBase worker."""
    result = service.run_job_sync(
        source_dir,
        JobTrigger(trigger),
        job_id=ctx.job_id,
        cancellation_event=ctx.cancellation_event,
        progress_callback=ctx.report_progress,
    )
    status = result["status"]
    if status == "failed":
        raise RuntimeError(result.get("error_message") or result["message"])
    return {
        "done": status != "cancelled",
        "message": result["message"],
        "warnings": status == "completed_with_warnings",
        "job": result,
    }


def build_invoice_registry(service: JobService) -> ToolRegistry:
    """Build the business registry without modifying the DevBase runtime."""
    registry = ToolRegistry()

    def invoice_task(ctx: TaskContext, **input: Any) -> dict[str, Any]:
        source_dir = input.get("source_dir")
        if not isinstance(source_dir, str) or not source_dir.strip():
            raise ValueError("source_dir is required")
        trigger = input.get("trigger", JobTrigger.MANUAL.value)
        if not isinstance(trigger, str):
            raise ValueError("trigger must be a string")
        return run_invoice_pipeline(
            ctx,
            service=service,
            source_dir=source_dir,
            trigger=trigger,
        )

    registry.register(
        ToolDescriptor(
            kind=INVOICE_TOOL_KIND,
            title="发票处理",
            subtitle="扫描、处理、审核并归档电子票据",
            group="invoice",
            glyph="receipt",
            supports_input=True,
            task=invoice_task,
        )
    )
    return registry


__all__ = ["INVOICE_TOOL_KIND", "build_invoice_registry", "run_invoice_pipeline"]
