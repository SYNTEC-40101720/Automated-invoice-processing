"""WebSocket 事件路由。"""

from __future__ import annotations

import asyncio

from devbase.application.errors import EventStreamClosed
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..dependencies import validate_websocket_token

router = APIRouter(tags=['events'])


def _read_cursor(websocket: WebSocket) -> int | None:
    """读取显式传入的 after 游标；缺席时返回 None（不重放）。

    游标缺席保持旧行为——只发 ready + 快照；否则新连接会重放整段
    历史（含旧任务日志，前端 appendEvent 对日志无条件追加）。
    """
    raw = websocket.query_params.get('after')
    if raw is None:
        return None
    try:
        return max(0, int(raw))
    except ValueError:
        return None


@router.websocket('/events')
async def events(websocket: WebSocket) -> None:
    if not validate_websocket_token(websocket):
        await websocket.close(code=1008, reason='本地 API 令牌无效')
        return

    await websocket.accept()
    service = websocket.app.state.job_service
    # 先订阅再取快照：重放 ∪ 实时并集无间隙，实时侧按 last_replayed 去重。
    subscription = service.events.subscribe(maxsize=256)
    try:
        await websocket.send_json({
            'event_id': 0,
            'type': 'system.ready',
            'occurred_at': '',
            'job_id': None,
            'payload': {'version': websocket.app.state.version},
        })
        last_replayed = 0
        after = _read_cursor(websocket)
        if after is not None:
            event_snapshot = service.events.snapshot(after)
            for event in event_snapshot.events:
                await websocket.send_json(event.to_dict())
                last_replayed = event.event_id
        snapshot = service.current_job()
        if snapshot:
            await websocket.send_json({
                'event_id': 0,
                'type': 'job.snapshot',
                'occurred_at': '',
                'job_id': snapshot['id'],
                'payload': snapshot,
            })
        while True:
            try:
                event = await asyncio.to_thread(subscription.get, 30.0)
            except TimeoutError:
                await websocket.send_json({
                    'event_id': 0,
                    'type': 'system.heartbeat',
                    'occurred_at': '',
                    'job_id': None,
                    'payload': {},
                })
                continue
            if event.event_id <= last_replayed:
                # 订阅建立早于快照，重放并集里已推过的事件丢弃。
                continue
            await websocket.send_json(event.to_dict())
    except (WebSocketDisconnect, RuntimeError, EventStreamClosed):
        pass
    finally:
        subscription.close()
