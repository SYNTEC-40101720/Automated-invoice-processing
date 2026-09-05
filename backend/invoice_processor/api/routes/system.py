"""系统路由。"""

from __future__ import annotations

import os
import webbrowser
from pathlib import Path

from fastapi import APIRouter, Depends, Request

from ...application.job_service import JobService
from ...application.update_checker import UpdateProgress, check_for_update
from ..dependencies import get_job_service, require_local_token
from ..schemas import (
    HealthResponse,
    OpenDirectoryRequest,
    OpenDirectoryResponse,
    UpdateApplyResponse,
    UpdateProgressResponse,
    UpdateResponse,
)

router = APIRouter(prefix='/system', tags=['system'])


def _open_directory(path: Path) -> bool:
    try:
        if os.name == 'nt':
            startfile = getattr(os, 'startfile', None)
            if startfile is None:
                return False
            startfile(str(path))
            return True
        return bool(webbrowser.open(path.resolve().as_uri()))
    except OSError:
        return False


@router.get(
    '/health',
    response_model=HealthResponse,
    dependencies=[Depends(require_local_token)],
)
def health(request: Request) -> HealthResponse:
    return HealthResponse(
        status='ok',
        version=request.app.state.version,
        build='web-refactor-preview',
        mode='local',
    )


@router.post(
    '/open-directory',
    response_model=OpenDirectoryResponse,
    dependencies=[Depends(require_local_token)],
)
def open_directory(
    request: OpenDirectoryRequest,
    service: JobService = Depends(get_job_service),
) -> OpenDirectoryResponse:
    directory = Path(request.path).expanduser()
    if not directory.is_dir() or not service.is_known_directory(str(directory)):
        return OpenDirectoryResponse(opened=False)
    return OpenDirectoryResponse(opened=_open_directory(directory))


@router.get(
    '/update',
    response_model=UpdateResponse,
    dependencies=[Depends(require_local_token)],
)
def update_check(request: Request) -> UpdateResponse:
    result = check_for_update(request.app.state.version)
    return UpdateResponse(
        current_version=result.current_version,
        checked=result.checked,
        available=result.available,
        latest_version=result.latest_version,
        release_url=result.release_url,
        installable=result.installable,
        asset_name=result.asset_name,
        asset_size=result.asset_size,
    )


@router.post(
    '/update/apply',
    response_model=UpdateApplyResponse,
    dependencies=[Depends(require_local_token)],
)
def update_apply(request: Request) -> UpdateApplyResponse:
    handler = getattr(request.app.state, 'update_apply', None)
    if handler is None:
        return UpdateApplyResponse(
            status='unsupported',
            message='当前运行方式不支持自动安装更新',
        )
    result = handler(request.app.state.version)
    return UpdateApplyResponse(
        status=result.status,
        message=result.message,
        latest_version=result.latest_version,
    )


@router.get(
    '/update/progress',
    response_model=UpdateProgressResponse,
    dependencies=[Depends(require_local_token)],
)
def update_progress(request: Request) -> UpdateProgressResponse:
    handler = getattr(request.app.state, 'update_progress', None)
    progress = handler() if handler is not None else UpdateProgress()
    progress_percent = None
    if progress.total_bytes and progress.total_bytes > 0:
        progress_percent = min(
            100.0,
            round(progress.downloaded_bytes / progress.total_bytes * 100, 1),
        )
    return UpdateProgressResponse(
        status=progress.status,
        downloaded_bytes=progress.downloaded_bytes,
        total_bytes=progress.total_bytes,
        progress_percent=progress_percent,
        latest_version=progress.latest_version,
        message=progress.message,
    )
