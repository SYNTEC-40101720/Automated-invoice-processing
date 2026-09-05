"""Task protocol, context, and registry — the plugin boundary for new tools.

A tool plugs its own logic into the runtime by registering a ``Task``
callable. It never touches ``JobRuntime`` or the API/desktop layers.

    from devbase.application.task import TaskContext, TaskRegistry

    def my_task(ctx: TaskContext) -> dict:
        for i in range(10):
            if ctx.is_cancelled():
                return {"done": False}
            ctx.report_progress(i / 10, f"step {i}")
            time.sleep(0.1)
        return {"done": True}

    registry.register("my_tool", my_task)

The runtime creates the ``TaskContext`` and passes it in; task bodies only
report domain progress and check cancellation.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Task(Protocol):
    """A cancellable unit of work executed by the runtime.

    Receives a ``TaskContext`` for progress reporting and cancellation
    checks; returns a JSON-serializable result dict.
    """

    def __call__(self, ctx: "TaskContext", **kwargs: Any) -> dict[str, Any]:
        ...


class TaskContext:
    """Passed into a running task so it can report progress and observe cancellation.

    The runtime owns this object; task bodies only call ``is_cancelled()``
    and ``report_progress()``.
    """

    def __init__(
        self,
        job_id: str,
        kind: str,
        cancel_event: threading.Event,
        report: Callable[[float, str], None],
    ) -> None:
        self.job_id = job_id
        self.kind = kind
        self._cancel_event = cancel_event
        self._report = report

    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    @property
    def cancellation_event(self) -> threading.Event:
        """Expose the host-owned event to adapters that need cancellation."""
        return self._cancel_event

    def report_progress(self, progress: float, message: str = "") -> None:
        self._report(progress, message)


class TaskNotFoundError(KeyError):
    """Raised when a requested task kind is not registered."""

    def __init__(self, kind: str) -> None:
        super().__init__(f"task kind not registered: {kind!r}")
        self.kind = kind


class TaskRegistry:
    """Maps ``kind`` strings to ``Task`` callables.

    New tools register their task at startup; the runtime looks one up by
    kind when ``POST /jobs/start`` arrives.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}

    def register(self, kind: str, task: Task) -> None:
        if kind in self._tasks:
            raise ValueError(f"task kind already registered: {kind!r}")
        self._tasks[kind] = task

    def get(self, kind: str) -> Task:
        if kind not in self._tasks:
            raise TaskNotFoundError(kind)
        return self._tasks[kind]

    def kinds(self) -> list[str]:
        return sorted(self._tasks)


__all__ = ["Task", "TaskContext", "TaskRegistry", "TaskNotFoundError"]


