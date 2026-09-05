from collections import deque
from dataclasses import dataclass
from threading import Condition, RLock
from time import monotonic

from devbase.domain.events import EventKind, RuntimeEvent


@dataclass(frozen=True, slots=True)
class EventSnapshot:
    events: tuple[RuntimeEvent, ...]
    cursor: int


class InMemoryEventBus:
    """Thread-safe event history with adjacent progress-event coalescing.

    The replay history is bounded. Progress events may be replaced by a newer
    progress event for the same job, while the current snapshot remains the
    source of truth after a reconnect.
    """

    def __init__(self, history_size: int = 512) -> None:
        if history_size < 1:
            raise ValueError("history_size must be positive")
        self._condition = Condition(RLock())
        self._events: deque[RuntimeEvent] = deque(maxlen=history_size)
        self._next_sequence = 0

    def publish(self, event: RuntimeEvent) -> RuntimeEvent:
        with self._condition:
            self._next_sequence += 1
            committed = RuntimeEvent(
                sequence=self._next_sequence,
                event_id=event.event_id,
                job_id=event.job_id,
                kind=event.kind,
                status=event.status,
                progress=event.progress,
                message=event.message,
                created_at=event.created_at,
            )
            if (
                committed.kind is EventKind.PROGRESS
                and self._events
                and self._events[-1].kind is EventKind.PROGRESS
                and self._events[-1].job_id == committed.job_id
            ):
                self._events[-1] = committed
            else:
                self._events.append(committed)
            self._condition.notify_all()
            return committed

    def snapshot(self, after_sequence: int = 0) -> EventSnapshot:
        with self._condition:
            events = tuple(
                event
                for event in self._events
                if event.sequence > after_sequence
            )
            return EventSnapshot(events=events, cursor=self._next_sequence)

    def wait_for_events(
        self,
        after_sequence: int,
        timeout: float | None = None,
    ) -> tuple[RuntimeEvent, ...]:
        deadline = None if timeout is None else monotonic() + timeout
        with self._condition:
            while True:
                events = tuple(
                    event
                    for event in self._events
                    if event.sequence > after_sequence
                )
                if events:
                    return events
                if deadline is None:
                    self._condition.wait()
                    continue
                remaining = deadline - monotonic()
                if remaining <= 0:
                    return ()
                self._condition.wait(remaining)
