"""系统路由。"""

from __future__ import annotations

import os
import webbrowser
from pathlib import Path

from fastapi import APIRouter, Depends, Request

from ...application.job_service import JobService
from ...application.update_checker import check_for_update
from ..dependencies import get_job_service, require_local_token
from ..schemas import (
    HealthResponse,
    OpenDirectoryRequest,
    OpenDirectoryResponse,
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
    )
