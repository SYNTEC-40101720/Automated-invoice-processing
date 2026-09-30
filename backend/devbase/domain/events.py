"""统一事件信封与生命周期类型词表。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class EventKind(StrEnum):
    """任务生命周期事件类型词表。

    业务扩展事件（job.snapshot、job.log_appended 等）不进词表，
    直接以自己的 type 字符串发布；PROGRESS 例外——它就是前端的
    ``job.progress`` 事件，值与业务侧约定一致。
    """

    JOB_CREATED = "job_created"
    JOB_STARTED = "job_started"
    PROGRESS = "job.progress"
    JOB_CANCELLING = "job_cancelling"
    JOB_SUCCEEDED = "job_succeeded"
    JOB_COMPLETED_WITH_WARNINGS = "job_completed_with_warnings"
    JOB_CANCELLED = "job_cancelled"
    JOB_FAILED = "job_failed"


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    """统一事件信封，与前端 WebSocket 帧一一对应。"""

    event_id: int
    type: str
    job_id: str | None
    payload: dict[str, Any]
    created_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "type": self.type,
            "occurred_at": self.created_at.isoformat(),
            "job_id": self.job_id,
            "payload": self.payload,
        }
