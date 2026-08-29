"""系统路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ...application.update_checker import check_for_update
from ..dependencies import require_local_token
from ..schemas import HealthResponse, UpdateApplyResponse, UpdateResponse

router = APIRouter(prefix='/system', tags=['system'])


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
