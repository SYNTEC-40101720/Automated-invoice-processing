"""WebSocket 事件路由。"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..dependencies import validate_websocket_token

router = APIRouter(tags=['events'])


@router.websocket('/events')
async def events(websocket: WebSocket) -> None:
    if not validate_websocket_token(websocket):
        await websocket.close(code=1008, reason='本地 API 令牌无效')
        return

    await websocket.accept()
    service = websocket.app.state.job_service
    subscription = service.events.subscribe(maxsize=256)
    try:
        await websocket.send_json({
            'event_id': 0,
            'type': 'system.ready',
            'occurred_at': '',
            'job_id': None,
            'payload': {'version': websocket.app.state.version},
        })
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
            await websocket.send_json(event.to_dict())
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        subscription.close()
