import asyncio
from contextlib import suppress

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from devbase.api.dependencies import validate_websocket_token
from devbase.api.schemas import event_response, snapshot_response

router = APIRouter(tags=["events"])


@router.websocket("/events")
async def events(websocket: WebSocket) -> None:
    if not validate_websocket_token(websocket):
        await websocket.close(code=1008, reason="invalid local API token")
        return
    runtime = websocket.app.state.runtime
    await websocket.accept()
    disconnected = asyncio.Event()
    disconnect_task = asyncio.create_task(
        _watch_disconnect(websocket, disconnected)
    )
    try:
        after_sequence = _read_cursor(websocket)
        initial_snapshot = runtime.current_snapshot(after_sequence)
        await websocket.send_json(
            {
                "type": "health",
                "data": {
                    "status": "ok",
                    "service": "devbase",
                    "active_job_id": (
                        None
                        if initial_snapshot.job is None
                        else initial_snapshot.job.job_id
                    ),
                    "window_close_mode": (
                        websocket.app.state.window_lifecycle.policy.close_mode.value
                    ),
                },
            }
        )
        await websocket.send_json(
            {
                "type": "snapshot",
                "data": snapshot_response(initial_snapshot).model_dump(mode="json"),
            }
        )

        cursor = initial_snapshot.event_cursor
        while True:
            if disconnected.is_set():
                return
            new_events = await asyncio.to_thread(
                runtime.wait_for_events,
                cursor,
                0.5,
            )
            if disconnected.is_set():
                return
            for event in new_events:
                await websocket.send_json(
                    {
                        "type": "event",
                        "data": event_response(event).model_dump(mode="json"),
                    }
                )
                cursor = event.sequence
    except WebSocketDisconnect:
        return
    finally:
        disconnect_task.cancel()
        with suppress(asyncio.CancelledError):
            await disconnect_task


async def _watch_disconnect(
    websocket: WebSocket,
    disconnected: asyncio.Event,
) -> None:
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                disconnected.set()
                return
    except WebSocketDisconnect:
        disconnected.set()


def _read_cursor(websocket: WebSocket) -> int:
    try:
        return max(0, int(websocket.query_params.get("after", "0")))
    except ValueError:
        return 0
