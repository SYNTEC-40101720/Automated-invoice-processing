"""API 依赖注入和本地令牌校验。"""

from __future__ import annotations

from fastapi import Header, HTTPException, Request, WebSocket

from ..application.job_service import JobService


def get_job_service(request: Request) -> JobService:
    return request.app.state.job_service


def _origin_is_allowed(app, origin: str | None, same_origin: str) -> bool:
    if not origin:
        return True
    normalized = origin.rstrip('/')
    allowed_origins = getattr(app.state, 'allowed_origins', frozenset())
    if allowed_origins:
        return normalized in allowed_origins
    return normalized == same_origin.rstrip('/')


def require_local_token(
    request: Request,
    x_local_token: str | None = Header(default=None),
) -> None:
    same_origin = f'{request.url.scheme}://{request.url.netloc}'
    if not _origin_is_allowed(request.app, request.headers.get('origin'), same_origin):
        raise HTTPException(status_code=403, detail='请求来源不受信任')
    expected = request.app.state.local_token
    if expected and x_local_token != expected:
        raise HTTPException(status_code=401, detail='本地 API 令牌无效')


def validate_websocket_token(websocket: WebSocket) -> bool:
    same_origin = f"http://{websocket.url.netloc}"
    if not _origin_is_allowed(
        websocket.app,
        websocket.headers.get('origin'),
        same_origin,
    ):
        return False
    expected = websocket.app.state.local_token
    if not expected:
        return True
    return websocket.query_params.get('token') == expected
