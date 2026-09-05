from fastapi import APIRouter, Depends, Request

from devbase.api.dependencies import get_runtime, require_local_token
from devbase.api.schemas import HealthResponse
from devbase.application.job_runtime import JobRuntime

router = APIRouter(
    tags=["system"],
    dependencies=[Depends(require_local_token)],
)


@router.get("/health", response_model=HealthResponse)
def health(
    request: Request,
    runtime: JobRuntime = Depends(get_runtime),
) -> HealthResponse:
    job = runtime.current_job()
    return HealthResponse(
        service="devbase",
        active_job_id=None if job is None else job.job_id,
        window_close_mode=request.app.state.window_lifecycle.policy.close_mode,
    )