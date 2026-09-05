from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCELLING = "cancelling"
    SUCCEEDED = "succeeded"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    CANCELLED = "cancelled"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in {
            JobStatus.SUCCEEDED,
            JobStatus.COMPLETED_WITH_WARNINGS,
            JobStatus.CANCELLED,
            JobStatus.FAILED,
        }

    @property
    def is_active(self) -> bool:
        """True while the job still occupies the single-active slot."""
        return self in {
            JobStatus.QUEUED,
            JobStatus.RUNNING,
            JobStatus.CANCELLING,
        }


class JobPhase(StrEnum):
    """High-level phase of a job's lifecycle.

    Multiple statuses can belong to the same phase, allowing the UI
    and runtime to reason at a coarser level than individual statuses.
    """

    PENDING = "pending"          # QUEUED
    EXECUTING = "executing"      # RUNNING, CANCELLING
    DONE = "done"                # all terminal statuses

    def matches(self, status: JobStatus) -> bool:
        if self is JobPhase.PENDING:
            return status is JobStatus.QUEUED
        if self is JobPhase.EXECUTING:
            return status in (JobStatus.RUNNING, JobStatus.CANCELLING)
        return status.is_terminal


class JobTrigger(StrEnum):
    """What started the job — useful for audit and UI badges.

    ``USER``    – started manually from the UI or API.
    ``SCHEDULE`` – started by a timer or external scheduler.
    ``PIPELINE`` – started by another task in a pipeline.
    """

    USER = "user"
    SCHEDULE = "schedule"
    PIPELINE = "pipeline"


@dataclass(frozen=True, slots=True)
class JobSnapshot:
    job_id: str
    kind: str
    status: JobStatus
    progress: int
    message: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class RuntimeSnapshot:
    job: JobSnapshot | None
    events: tuple["RuntimeEvent", ...]
    event_cursor: int