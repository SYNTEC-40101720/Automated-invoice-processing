"""线程安全的统一事件总线。

融合自发票版订阅通道与 DevBase 版游标重放：
- ``EventSubscription``：有界双通道（progress 只保留最新一条，关键事件
  溢出即关闭订阅强制慢客户端重连），``get(timeout)`` 阻塞读适配 WS 循环；
- ``history``/``snapshot``：全局单调 ``event_id`` 游标重放，重连方带旧
  游标一次性拿回漏掉的事件。

历史不做合并——重放与日志分页依赖连续编号无空洞。
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from devbase.domain.events import RuntimeEvent

from .errors import EventStreamClosed

PROGRESS_TYPE = "job.progress"


@dataclass(frozen=True, slots=True)
class EventSnapshot:
    """游标重放结果：事件元组 + 当前游标（已分配的最大 event_id）。"""

    events: tuple[RuntimeEvent, ...]
    cursor: int


class EventSubscription:
    """一个有界、可阻塞读取的事件订阅。"""

    def __init__(self, bus: "EventBus", maxsize: int):
        self._bus = bus
        self._maxsize = max(1, maxsize)
        self._critical_events: deque[RuntimeEvent] = deque()
        self._latest_progress: RuntimeEvent | None = None
        self._condition = threading.Condition()
        self._closed = False

    def put(self, event: RuntimeEvent) -> bool:
        with self._condition:
            if self._closed:
                return False
            if event.type == PROGRESS_TYPE:
                self._latest_progress = event
                self._condition.notify()
                return True
            if len(self._critical_events) >= self._maxsize:
                # 关键事件不能静默丢弃，也不能反向阻塞业务线程；
                # 慢客户端需重连并从历史恢复。
                self._closed = True
                self._condition.notify_all()
                return False
            self._critical_events.append(event)
            self._condition.notify()
            return True

    def get(self, timeout: float | None = None) -> RuntimeEvent:
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._condition:
            while (
                not self._critical_events
                and self._latest_progress is None
                and not self._closed
            ):
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    raise TimeoutError("等待事件超时")
                self._condition.wait(remaining)
            if self._critical_events:
                event = self._critical_events.popleft()
                self._condition.notify_all()
                return event
            if self._latest_progress is not None:
                event = self._latest_progress
                self._latest_progress = None
                return event
            raise EventStreamClosed()

    def close(self) -> None:
        self._bus.unsubscribe(self)

    def _close_from_bus(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()


class EventBus:
    """为运行时、应用服务和 API 层提供统一事件发布入口。"""

    def __init__(self, history_size: int = 500):
        self._lock = threading.RLock()
        self._next_event_id = 0
        self._history: deque[RuntimeEvent] = deque(maxlen=max(1, history_size))
        self._subscriptions: set[EventSubscription] = set()

    def publish(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
        job_id: str | None = None,
    ) -> RuntimeEvent:
        with self._lock:
            self._next_event_id += 1
            event = RuntimeEvent(
                event_id=self._next_event_id,
                type=event_type,
                job_id=job_id,
                payload=payload or {},
                created_at=datetime.now(timezone.utc),
            )
            self._history.append(event)
            subscriptions = tuple(self._subscriptions)
        for subscription in subscriptions:
            if not subscription.put(event):
                self.unsubscribe(subscription)
        return event

    def subscribe(self, maxsize: int = 256) -> EventSubscription:
        subscription = EventSubscription(self, maxsize)
        with self._lock:
            self._subscriptions.add(subscription)
        return subscription

    def unsubscribe(self, subscription: EventSubscription) -> None:
        with self._lock:
            self._subscriptions.discard(subscription)
        subscription._close_from_bus()

    def history(self, after_event_id: int = 0, limit: int = 200) -> list[RuntimeEvent]:
        with self._lock:
            events = [
                event for event in self._history if event.event_id > after_event_id
            ]
        return events[-max(1, limit):]

    def snapshot(self, after_event_id: int = 0) -> EventSnapshot:
        with self._lock:
            events = tuple(
                event for event in self._history if event.event_id > after_event_id
            )
            return EventSnapshot(events=events, cursor=self._next_event_id)