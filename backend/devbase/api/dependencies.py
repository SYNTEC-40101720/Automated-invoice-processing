"""API 依赖注入和本地令牌校验。

安全模型：
- 桌面模式下，本地服务监听 127.0.0.1 随机端口，通过 X-Local-Token 鉴权
- 不传 local_token 时，create_app() 自动生成随机 token
- 所有 /api/v1 路由强制校验 token；WebSocket 通过 query 参数校验
- allowed_origins 可选 CORS 白名单（非空时校验 Origin 头）
"""

from __future__ import annotations

from fastapi import Header, HTTPException, Request, WebSocket

from devbase.application.job_runtime import JobRuntime


def get_runtime(request: Request) -> JobRuntime:
    return request.app.state.runtime


def _origin_is_allowed(app, origin: str | None, same_origin: str) -> bool:
    if not origin:
        return True
    normalized = origin.rstrip("/")
    if normalized == same_origin.rstrip("/"):
        return True
    allowed_origins = getattr(app.state, "allowed_origins", frozenset())
    if allowed_origins:
        return normalized in allowed_origins
    return normalized == same_origin.rstrip("/")


def require_local_token(
    request: Request,
    x_local_token: str | None = Header(default=None),
) -> None:
    same_origin = f"{request.url.scheme}://{request.url.netloc}"
    if not _origin_is_allowed(request.app, request.headers.get("origin"), same_origin):
        raise HTTPException(status_code=403, detail="request origin not allowed")
    expected = request.app.state.local_token
    if expected and x_local_token != expected:
        raise HTTPException(status_code=401, detail="invalid local API token")


def validate_websocket_token(websocket: WebSocket) -> bool:
    same_origin = f"http://{websocket.url.netloc}"
    if not _origin_is_allowed(
        websocket.app,
        websocket.headers.get("origin"),
        same_origin,
    ):
        return False
    expected = websocket.app.state.local_token
    if not expected:
        return True
    return websocket.query_params.get("token") == expected
