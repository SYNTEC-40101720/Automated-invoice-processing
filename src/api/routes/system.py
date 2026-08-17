"""系统路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..dependencies import require_local_token
from ..schemas import HealthResponse

router = APIRouter(prefix='/system', tags=['system'])


@router.get('/health', response_model=HealthResponse, dependencies=[Depends(require_local_token)])
def health(request: Request) -> HealthResponse:
    return HealthResponse(
        status='ok',
        version=request.app.state.version,
        build='web-refactor-preview',
        mode='local',
    )
