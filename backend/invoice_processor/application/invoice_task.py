"""将发票流水线接入 DevBase 任务清单。"""

from __future__ import annotations

import os
from typing import Any

from devbase.application.manifest import ToolDescriptor, ToolRegistry
from devbase.application.task import TaskContext

from ..core.exclusions import is_excluded_filename
from ..domain.errors import (
    InvalidSourceDirectory,
    InvalidTrigger,
    NoPdfFiles,
)
from ..domain.job import JobTrigger
from .job_service import JobService

INVOICE_TOOL_KIND = "invoice_processing"

# DevBase 与发票两侧的触发来源词汇在此集中映射：
# DevBase 的 user 归并为发票的 manual；inbox/email 两侧同词。
# schedule/pipeline 当前没有对应业务语义，显式拒绝而不是臆造映射。
TRIGGER_ALIASES: dict[str, JobTrigger] = {
    "manual": JobTrigger.MANUAL,
    "user": JobTrigger.MANUAL,
    "inbox": JobTrigger.INBOX,
    "email": JobTrigger.EMAIL,
}


def resolve_trigger(value: str) -> JobTrigger:
    """把 DevBase 输入中的 trigger 词汇解析为发票业务枚举。"""
    trigger = TRIGGER_ALIASES.get(str(value).strip().lower())
    if trigger is None:
        raise InvalidTrigger(value)
    return trigger


def validate_start_input(input: dict[str, Any]) -> None:
    """启动前同步预检，保证 422 稳定错误码同步返回给调用方。

    DevBase worker 内的同一校验保留为兜底；此处先执行可避免错误
    在后台线程抛出后前端只能看到任务 FAILED。
    """
    source_dir = input.get("source_dir")
    if not isinstance(source_dir, str) or not source_dir.strip():
        raise InvalidSourceDirectory(str(source_dir))
    normalized = os.path.abspath(os.path.expanduser(source_dir))
    if not os.path.isdir(normalized) or not os.access(normalized, os.R_OK):
        raise InvalidSourceDirectory(normalized)
    pdf_files = [
        filename
        for filename in os.listdir(normalized)
        if filename.lower().endswith(".pdf")
        and not is_excluded_filename(filename)
        and os.path.isfile(os.path.join(normalized, filename))
    ]
    if not pdf_files:
        raise NoPdfFiles(normalized)
    resolve_trigger(str(input.get("trigger", JobTrigger.MANUAL.value)))


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
        resolve_trigger(trigger),
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
            subtitle="文件处理",
            group="invoice",
            glyph="receipt",
            supports_input=True,
            task=invoice_task,
        )
    )
    return registry


__all__ = [
    "INVOICE_TOOL_KIND",
    "TRIGGER_ALIASES",
    "build_invoice_registry",
    "resolve_trigger",
    "run_invoice_pipeline",
    "validate_start_input",
]
