"""API 依赖注入和本地令牌校验。"""

from __future__ import annotations

from fastapi import Header, HTTPException, Request, WebSocket

from ..application.job_service import JobService


def get_job_service(request: Request) -> JobService:
    return request.app.state.job_service


def require_local_token(
    request: Request,
    x_local_token: str | None = Header(default=None),
) -> None:
    expected = request.app.state.local_token
    if expected and x_local_token != expected:
        raise HTTPException(status_code=401, detail='本地 API 令牌无效')


def validate_websocket_token(websocket: WebSocket) -> bool:
    expected = websocket.app.state.local_token
    if not expected:
        return True
    return websocket.query_params.get('token') == expected
