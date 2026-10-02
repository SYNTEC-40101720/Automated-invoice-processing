"""处理任务 HTTP 路由。"""

from __future__ import annotations

from devbase.application.job_runtime import JobRuntime
from fastapi import APIRouter, Depends, status

from ...application.invoice_task import INVOICE_TOOL_KIND, validate_start_input
from ...application.job_service import JobService
from ..dependencies import get_devbase_runtime, get_job_service, require_local_token
from ..schemas import (
    DirectoryScanResponse,
    JobHistoryEntry,
    JobHistoryResponse,
    JobSnapshotResponse,
    LogEntry,
    LogListResponse,
    RuntimeJobResponse,
    RuntimeJobStartRequest,
    StartJobRequest,
)

router = APIRouter(
    prefix='/jobs',
    tags=['jobs'],
    dependencies=[Depends(require_local_token)],
)


@router.get('/current', response_model=JobSnapshotResponse | None)
def current_job(service: JobService = Depends(get_job_service)) -> dict | None:
    # 响应经 JobSnapshotResponse 序列化：契约显式化（OpenAPI 可见），
    # dict 聚合字段缺漏会在序列化时报错而不是静默传给前端。
    return service.current_job()


@router.get('/history', response_model=JobHistoryResponse)
def job_history(
    limit: int = 20,
    service: JobService = Depends(get_job_service),
) -> JobHistoryResponse:
    """跨启动处理历史（新→旧）；limit 限定 1..50。"""
    bounded = max(1, min(limit, 50))
    items = [
        JobHistoryEntry(**entry)
        for entry in reversed(service.job_history_entries())
    ]
    return JobHistoryResponse(items=items[:bounded])


@router.post('/scan', response_model=DirectoryScanResponse)
def scan_directory(
    request: StartJobRequest,
    service: JobService = Depends(get_job_service),
) -> DirectoryScanResponse:
    result = service.scan_directory(request.source_dir)
    return DirectoryScanResponse(**result)


@router.post(
    '/start',
    response_model=RuntimeJobResponse,
    status_code=status.HTTP_201_CREATED,
)
def start_runtime_job(
    request: RuntimeJobStartRequest,
    runtime: JobRuntime = Depends(get_devbase_runtime),
) -> RuntimeJobResponse:
    # 发票任务先同步预检，保证目录/触发来源错误以 422 稳定错误码返回；
    # worker 内同一校验保留为兜底。
    if request.kind == INVOICE_TOOL_KIND:
        validate_start_input(request.input)
    snapshot = runtime.start(request.kind, input=request.input)
    return RuntimeJobResponse(
        id=snapshot.job_id,
        kind=snapshot.kind,
        status=snapshot.status.value,
        progress=snapshot.progress,
        message=snapshot.message,
        created_at=snapshot.created_at.isoformat(),
        updated_at=snapshot.updated_at.isoformat(),
    )


@router.post('/cancel', response_model=RuntimeJobResponse)
def cancel_runtime_job(
    runtime: JobRuntime = Depends(get_devbase_runtime),
) -> RuntimeJobResponse:
    snapshot = runtime.cancel_current()
    return RuntimeJobResponse(
        id=snapshot.job_id,
        kind=snapshot.kind,
        status=snapshot.status.value,
        progress=snapshot.progress,
        message=snapshot.message,
        created_at=snapshot.created_at.isoformat(),
        updated_at=snapshot.updated_at.isoformat(),
    )


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
            occurred_at=event.created_at.isoformat(),
            level=str(event.payload.get('level', 'info')),
            message=str(event.payload.get('message', '')),
        )
        for event in events[-max(1, min(limit, 1000)):]
    ]
    next_event_id = items[-1].event_id if items else None
    return LogListResponse(items=items, next_event_id=next_event_id)
