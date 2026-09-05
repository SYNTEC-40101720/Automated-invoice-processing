from fastapi import APIRouter, Depends

from devbase.api.dependencies import get_runtime, require_local_token
from devbase.api.schemas import (
    JobResponse,
    SnapshotResponse,
    StartJobRequest,
    snapshot_response,
)
from devbase.application.job_runtime import JobRuntime
from devbase.application.task import TaskNotFoundError

router = APIRouter(
    prefix="/jobs",
    tags=["jobs"],
    dependencies=[Depends(require_local_token)],
)


@router.get("/current", response_model=SnapshotResponse)
def current_job(runtime: JobRuntime = Depends(get_runtime)) -> SnapshotResponse:
    return snapshot_response(runtime.current_snapshot())


@router.post("/start", response_model=JobResponse, status_code=201)
def start_job(
    body: StartJobRequest | None = None,
    runtime: JobRuntime = Depends(get_runtime),
) -> JobResponse:
    """Start a task by ``kind``.

    Body defaults to ``{"kind": "demo_long_task"}`` when omitted, so a bare
    ``POST /jobs/start`` still works. Unknown kinds raise ``TaskNotFoundError``
    which the app maps to 404.
    """
    request = body or StartJobRequest()
    job = runtime.start(request.kind, input=request.input)
    return JobResponse(
        id=job.job_id,
        kind=job.kind,
        status=job.status,
        progress=job.progress,
        message=job.message,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


@router.post("/cancel", response_model=JobResponse)
def cancel_job(runtime: JobRuntime = Depends(get_runtime)) -> JobResponse:
    job = runtime.cancel_current()
    return JobResponse(
        id=job.job_id,
        kind=job.kind,
        status=job.status,
        progress=job.progress,
        message=job.message,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )
