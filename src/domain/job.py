"""处理任务聚合和状态机。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from .errors import InvalidJobTransition


class JobStatus(str, Enum):
    QUEUED = 'queued'
    RUNNING = 'running'
    CANCELLING = 'cancelling'
    SUCCEEDED = 'succeeded'
    COMPLETED_WITH_WARNINGS = 'completed_with_warnings'
    CANCELLED = 'cancelled'
    FAILED = 'failed'

    @property
    def is_terminal(self) -> bool:
        return self in {
            JobStatus.SUCCEEDED,
            JobStatus.COMPLETED_WITH_WARNINGS,
            JobStatus.CANCELLED,
            JobStatus.FAILED,
        }


class JobTrigger(str, Enum):
    MANUAL = 'manual'
    INBOX = 'inbox'
    EMAIL = 'email'


class JobPhase(str, Enum):
    SCAN = 'scan'
    PROCESS = 'process'
    POST_PROCESS = 'post_process'
    LOCAL_AUDIT = 'local_audit'
    AI_AUDIT = 'ai_audit'
    ARCHIVE = 'archive'
    DONE = 'done'


@dataclass
class JobStats:
    total: int = 0
    success: int = 0
    failure: int = 0
    tax_issues: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            'total': self.total,
            'success': self.success,
            'failure': self.failure,
            'tax_issues': self.tax_issues,
        }


_ALLOWED_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
    JobStatus.QUEUED: {JobStatus.RUNNING, JobStatus.CANCELLED, JobStatus.FAILED},
    JobStatus.RUNNING: {
        JobStatus.CANCELLING,
        JobStatus.SUCCEEDED,
        JobStatus.COMPLETED_WITH_WARNINGS,
        JobStatus.CANCELLED,
        JobStatus.FAILED,
    },
    JobStatus.CANCELLING: {
        JobStatus.CANCELLED,
        JobStatus.COMPLETED_WITH_WARNINGS,
        JobStatus.FAILED,
    },
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


@dataclass
class Job:
    """一次目录处理的唯一状态源。由 JobService 在锁内修改。"""

    source_dir: str
    trigger: JobTrigger = JobTrigger.MANUAL
    id: str = field(default_factory=lambda: uuid4().hex)
    output_dir: str | None = None
    status: JobStatus = JobStatus.QUEUED
    phase: JobPhase = JobPhase.SCAN
    progress: float = 0.0
    message: str = '任务已排队'
    stats: JobStats = field(default_factory=JobStats)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    cancel_requested: bool = False
    error_code: str | None = None
    error_message: str | None = None
    result: dict[str, Any] | None = None

    def transition(self, target: JobStatus) -> None:
        if target == self.status:
            return
        if (
            self.status.is_terminal
            or target not in _ALLOWED_TRANSITIONS.get(self.status, set())
        ):
            raise InvalidJobTransition(self.status.value, target.value)
        self.status = target
        if target == JobStatus.RUNNING and self.started_at is None:
            self.started_at = _now()
        if target.is_terminal:
            self.finished_at = _now()

    def request_cancel(self) -> bool:
        """请求协作式停止，返回本次是否首次请求。"""
        if self.status.is_terminal:
            return False
        first_request = not self.cancel_requested
        self.cancel_requested = True
        if self.status == JobStatus.QUEUED:
            self.transition(JobStatus.CANCELLED)
        elif self.status == JobStatus.RUNNING:
            self.transition(JobStatus.CANCELLING)
        return first_request

    def set_progress(self, ratio: float) -> None:
        """设置单调进度，避免错误回调让前端进度倒退。"""
        bounded = max(0.0, min(1.0, float(ratio)))
        self.progress = max(self.progress, bounded)

    def to_dict(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'source_dir': self.source_dir,
            'output_dir': self.output_dir,
            'trigger': self.trigger.value,
            'status': self.status.value,
            'phase': self.phase.value,
            'progress': self.progress,
            'message': self.message,
            'stats': self.stats.to_dict(),
            'started_at': _iso(self.started_at),
            'finished_at': _iso(self.finished_at),
            'cancel_requested': self.cancel_requested,
            'error_code': self.error_code,
            'error_message': self.error_message,
            'result': self.result,
        }
