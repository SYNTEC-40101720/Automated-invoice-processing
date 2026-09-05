from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from devbase.application.lifecycle import WindowCloseMode
from devbase.application.manifest import ToolDescriptor
from devbase.desktop.update_manager import UpdateProgress
from devbase.domain.events import EventKind, RuntimeEvent
from devbase.domain.job import JobSnapshot, JobStatus, RuntimeSnapshot


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str
    active_job_id: str | None
    window_close_mode: WindowCloseMode


class JobResponse(BaseModel):
    id: str
    kind: str
    status: JobStatus
    progress: int
    message: str
    created_at: datetime
    updated_at: datetime


class StartJobRequest(BaseModel):
    """Body for ``POST /jobs/start``.

    ``kind`` defaults to ``demo_long_task`` when omitted, so existing
    callers that post an empty body keep working.
    """

    kind: str = "demo_long_task"
    input: dict[str, Any] = {}


class ToolDescriptorResponse(BaseModel):
    kind: str
    title: str
    subtitle: str | None = None
    group: str
    glyph: str
    access_key: str | None = None
    supports_input: bool = False
    mode: str = "oneshot"


class ToolListResponse(BaseModel):
    tools: list[ToolDescriptorResponse]


class UpdateCheckResponse(BaseModel):
    current: str
    latest: str | None = None
    available: bool = False
    installable: bool = False
    asset_name: str | None = None
    release_url: str | None = None
    error: str | None = None


class UpdateProgressResponse(BaseModel):
    status: str
    percent: int
    message: str
    error: str | None = None
    rollback: bool = False
    ready_file: str | None = None


def tool_descriptor_response(d: ToolDescriptor) -> ToolDescriptorResponse:
    return ToolDescriptorResponse(
        kind=d.kind,
        title=d.title,
        subtitle=d.subtitle,
        group=d.group,
        glyph=d.glyph,
        access_key=d.access_key,
        supports_input=d.supports_input,
        mode=d.mode,
    )


class EventResponse(BaseModel):
    sequence: int
    event_id: str
    job_id: str
    kind: EventKind
    status: JobStatus
    progress: int
    message: str
    created_at: datetime


class SnapshotResponse(BaseModel):
    job: JobResponse | None
    events: list[EventResponse]
    event_cursor: int


def job_response(job: JobSnapshot | None) -> JobResponse | None:
    if job is None:
        return None
    return JobResponse(
        id=job.job_id,
        kind=job.kind,
        status=job.status,
        progress=job.progress,
        message=job.message,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def event_response(event: RuntimeEvent) -> EventResponse:
    return EventResponse(
        sequence=event.sequence,
        event_id=event.event_id,
        job_id=event.job_id,
        kind=event.kind,
        status=event.status,
        progress=event.progress,
        message=event.message,
        created_at=event.created_at,
    )


def snapshot_response(snapshot: RuntimeSnapshot) -> SnapshotResponse:
    return SnapshotResponse(
        job=job_response(snapshot.job),
        events=[event_response(event) for event in snapshot.events],
        event_cursor=snapshot.event_cursor,
    )


def update_progress_response(progress: UpdateProgress) -> UpdateProgressResponse:
    return UpdateProgressResponse(
        status=progress.status,
        percent=progress.percent,
        message=progress.message,
        error=progress.error,
        rollback=progress.rollback,
        ready_file=progress.ready_file,
    )
