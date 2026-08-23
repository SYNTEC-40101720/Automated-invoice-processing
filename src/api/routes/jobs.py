"""处理任务 HTTP 路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from ...application.job_service import JobService
from ..dependencies import get_job_service, require_local_token
from ..schemas import (
    DirectoryScanResponse,
    LogEntry,
    LogListResponse,
    StartJobRequest,
)

router = APIRouter(
    prefix='/jobs',
    tags=['jobs'],
    dependencies=[Depends(require_local_token)],
)


@router.get('/current', response_model=dict | None)
def current_job(service: JobService = Depends(get_job_service)) -> dict | None:
    return service.current_job()


@router.post('/scan', response_model=DirectoryScanResponse)
def scan_directory(
    request: StartJobRequest,
    service: JobService = Depends(get_job_service),
) -> DirectoryScanResponse:
    result = service.scan_directory(request.source_dir)
    return DirectoryScanResponse(**result)


@router.post('', response_model=dict, status_code=status.HTTP_202_ACCEPTED)
def start_job(
    request: StartJobRequest,
    service: JobService = Depends(get_job_service),
) -> dict:
    return service.start_job(request.source_dir, request.trigger)


@router.get('/{job_id}', response_model=dict)
def get_job(job_id: str, service: JobService = Depends(get_job_service)) -> dict:
    return service.get_job(job_id)


@router.post(
    '/{job_id}/cancel', response_model=dict, status_code=status.HTTP_202_ACCEPTED
)
def cancel_job(job_id: str, service: JobService = Depends(get_job_service)) -> dict:
    return service.cancel_job(job_id)


@router.get('/{job_id}/logs', response_model=LogListResponse)
def get_logs(
    job_id: str,
    after_event_id: int = 0,
    limit: int = 200,
    service: JobService = Depends(get_job_service),
) -> LogListResponse:
    service.get_job(job_id)
    events = [
        event for event in service.events.history(after_event_id, limit=1000)
        if event.job_id == job_id and event.type == 'job.log_appended'
    ]
    items = [
        LogEntry(
            event_id=event.event_id,
            occurred_at=event.occurred_at,
            level=str(event.payload.get('level', 'info')),
            message=str(event.payload.get('message', '')),
        )
        for event in events[-max(1, min(limit, 1000)):]
    ]
    next_event_id = items[-1].event_id if items else None
    return LogListResponse(items=items, next_event_id=next_event_id)
