"""WebSocket 事件路由。"""

from __future__ import annotations

import asyncio
import time
from contextlib import suppress

from devbase.application.errors import EventStreamClosed
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..dependencies import validate_websocket_token

router = APIRouter(tags=['events'])

# 空闲心跳帧间隔（秒）：仅用于让客户端确认连接存活，与空转轮询周期解耦。
HEARTBEAT_SECONDS = 30.0


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
    disconnected = asyncio.Event()
    disconnect_task = asyncio.create_task(
        _watch_disconnect(websocket, disconnected)
    )
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
        last_send = time.monotonic()
        while True:
            if disconnected.is_set():
                return
            try:
                event = await asyncio.to_thread(subscription.get, 0.5)
            except TimeoutError:
                # 空转轮询与模板 WS 同节奏（0.5s）：断链由监听任务置位
                # disconnected，本循环最迟一个空转周期内退出并回收订阅。
                if time.monotonic() - last_send >= HEARTBEAT_SECONDS:
                    await websocket.send_json({
                        'event_id': 0,
                        'type': 'system.heartbeat',
                        'occurred_at': '',
                        'job_id': None,
                        'payload': {},
                    })
                    last_send = time.monotonic()
                continue
            except EventStreamClosed:
                return
            if disconnected.is_set():
                return
            if event.event_id <= last_replayed:
                # 订阅建立早于快照，重放并集里已推过的事件丢弃。
                continue
            await websocket.send_json(event.to_dict())
            last_send = time.monotonic()
    except (WebSocketDisconnect, RuntimeError, EventStreamClosed):
        pass
    finally:
        disconnect_task.cancel()
        with suppress(asyncio.CancelledError):
            await disconnect_task
        subscription.close()


async def _watch_disconnect(websocket: WebSocket, disconnected: asyncio.Event) -> None:
    """并发读客户端入站帧，只关心 disconnect——尽早发现死链回收订阅。"""
    try:
        while True:
            message = await websocket.receive()
            if message['type'] == 'websocket.disconnect':
                disconnected.set()
                return
    except (WebSocketDisconnect, RuntimeError):
        disconnected.set()
