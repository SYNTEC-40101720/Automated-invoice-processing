"""线程安全的领域事件总线。"""

from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

from ..domain.errors import EventStreamClosed
from ..domain.events import DomainEvent


class EventSubscription:
    """一个有界、可阻塞读取的事件订阅。"""

    def __init__(self, bus: 'EventBus', maxsize: int):
        self._bus = bus
        self._maxsize = max(1, maxsize)
        self._critical_events: deque[DomainEvent] = deque()
        self._latest_progress: DomainEvent | None = None
        self._condition = threading.Condition()
        self._closed = False

    def put(self, event: DomainEvent) -> bool:
        with self._condition:
            if self._closed:
                return False
            if event.type == 'job.progress':
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

    def get(self, timeout: float | None = None) -> DomainEvent:
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._condition:
            while (
                not self._critical_events
                and self._latest_progress is None
                and not self._closed
            ):
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    raise TimeoutError('等待事件超时')
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
    """为应用服务和 API 层提供统一事件发布入口。"""

    def __init__(self, history_size: int = 500):
        self._lock = threading.RLock()
        self._next_event_id = 0
        self._history: deque[DomainEvent] = deque(maxlen=max(1, history_size))
        self._subscriptions: set[EventSubscription] = set()

    def publish(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
        job_id: str | None = None,
    ) -> DomainEvent:
        with self._lock:
            self._next_event_id += 1
            event = DomainEvent(
                event_id=self._next_event_id,
                type=event_type,
                occurred_at=datetime.now(timezone.utc).isoformat(),
                job_id=job_id,
                payload=payload or {},
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

    def history(self, after_event_id: int = 0, limit: int = 200) -> list[DomainEvent]:
        with self._lock:
            events = [
                event for event in self._history if event.event_id > after_event_id
            ]
        return events[-max(1, limit):]
