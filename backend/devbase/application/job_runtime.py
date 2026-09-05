"""Single-job in-memory runtime with pluggable tools.

The runtime owns one in-memory job at a time, executed on a background
thread. Tools are looked up by ``kind`` in a :class:`ToolRegistry` — new
tools register a :class:`ToolDescriptor` (title, group, glyph, task) at
startup without touching the runtime, the API, or the desktop layer.

The runtime follows the ports pattern: :class:`TaskContext` implements
:class:`ProgressSink` and is the only thing a task body sees.
User-facing strings flow through a :class:`ResourceProvider` so logic
never hard-codes localization.

Demo tool (``demo_long_task``) is registered by default so the template
works out of the box.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Event, RLock, Thread
from typing import Any
from uuid import uuid4

from devbase.domain.events import EventKind, RuntimeEvent
from devbase.domain.job import JobSnapshot, JobStatus, RuntimeSnapshot
from devbase.domain.resources import ResourceProvider, get_default

from .errors import (
    JobAlreadyRunningError,
    JobNotCancellableError,
    NoCurrentJobError,
)
from .event_bus import InMemoryEventBus
from .manifest import ToolDescriptor, ToolRegistry
from .task import TaskContext, TaskNotFoundError


@dataclass(slots=True)
class _MutableJob:
    job_id: str
    kind: str
    status: JobStatus
    progress: int
    message: str
    created_at: datetime
    updated_at: datetime
    cancellation_requested: Event


class JobRuntime:
    """Owns one in-memory job and its worker thread.

    Pass a :class:`ToolRegistry` so ``start(kind)`` can look up the tool;
    the default registry has only the built-in demo tool. Pass a
    :class:`ResourceProvider` to localize messages; defaults to the
    in-process Chinese table.
    """

    def __init__(
        self,
        event_bus: InMemoryEventBus | None = None,
        *,
        registry: ToolRegistry | None = None,
        resources: ResourceProvider | None = None,
        total_steps: int = 10,
        step_delay: float = 0.2,
    ) -> None:
        if total_steps < 1:
            raise ValueError("total_steps must be positive")
        if step_delay < 0:
            raise ValueError("step_delay must not be negative")
        self._event_bus = event_bus or InMemoryEventBus()
        self._registry = registry or _default_registry(total_steps, step_delay)
        self._resources = resources or get_default()
        self._total_steps = total_steps
        self._step_delay = step_delay
        self._lock = RLock()
        self._active: _MutableJob | None = None

    # ---- public API ----

    def start(
        self,
        kind: str = "demo_long_task",
        *,
        input: dict[str, Any] | None = None,
    ) -> JobSnapshot:
        """Look up ``kind`` in the registry and start it on a background thread."""
        descriptor = self._registry.get(kind)
        if descriptor.task is None:
            raise TaskNotFoundError(
                f"tool {kind!r} is not a runnable task (mode={descriptor.mode!r})"
            )
        task = descriptor.task
        with self._lock:
            if self._active and not self._active.status.is_terminal:
                raise JobAlreadyRunningError("a non-terminal job is already running")

            now = _utc_now()
            job = _MutableJob(
                job_id=str(uuid4()),
                kind=kind,
                status=JobStatus.QUEUED,
                progress=0,
                message=self._resources.string("job.queued", kind=kind),
                created_at=now,
                updated_at=now,
                cancellation_requested=Event(),
            )
            self._active = job
            self._emit_locked(job, EventKind.JOB_CREATED)
            snapshot = self._snapshot_locked(job)

        Thread(
            target=self._run_task,
            args=(job.job_id, task, input or {}),
            name=f"platform-{kind}-{job.job_id[:8]}",
            daemon=True,
        ).start()
        return snapshot

    def start_demo(self) -> JobSnapshot:
        """Backward-compatible shortcut for ``start('demo_long_task')``."""
        return self.start("demo_long_task")

    def cancel_current(self) -> JobSnapshot:
        """Request cancellation: transitions to CANCELLING.

        The worker thread will observe the cancel event and ultimately
        transition to CANCELLED (or SUCCEEDED if it finishes first).
        """
        with self._lock:
            if self._active is None:
                raise NoCurrentJobError("no current job exists")
            if self._active.status.is_terminal:
                raise JobNotCancellableError("the current job is already terminal")

            self._active.cancellation_requested.set()
            self._set_state_locked(
                self._active,
                status=JobStatus.CANCELLING,
                kind=EventKind.JOB_CANCELLING,
                message=self._resources.string("job.cancelling"),
            )
            return self._snapshot_locked(self._active)

    def current_job(self) -> JobSnapshot | None:
        with self._lock:
            if self._active is None:
                return None
            return self._snapshot_locked(self._active)

    def current_snapshot(self, after_sequence: int = 0) -> RuntimeSnapshot:
        with self._lock:
            job = (
                None
                if self._active is None
                else self._snapshot_locked(self._active)
            )
            event_snapshot = self._event_bus.snapshot(after_sequence)
            return RuntimeSnapshot(
                job=job,
                events=event_snapshot.events,
                event_cursor=event_snapshot.cursor,
            )

    def wait_for_events(
        self,
        after_sequence: int,
        timeout: float | None = None,
    ) -> tuple[RuntimeEvent, ...]:
        return self._event_bus.wait_for_events(after_sequence, timeout)

    def registry(self) -> ToolRegistry:
        """Expose the tool registry for the API/frontend nav layer."""
        return self._registry

    # ---- task execution ----

    def _run_task(
        self,
        job_id: str,
        task: object,
        input: dict[str, Any],
    ) -> None:
        try:
            with self._lock:
                job = self._get_active_locked(job_id)
                if job is None or job.status.is_terminal:
                    return
                self._set_state_locked(
                    job,
                    status=JobStatus.RUNNING,
                    kind=EventKind.JOB_STARTED,
                    message=self._resources.string("job.running", kind=job.kind),
                )
                cancel_event = job.cancellation_requested

            def report(progress: float, message: str) -> None:
                with self._lock:
                    job = self._get_active_locked(job_id)
                    if (
                        job is None
                        or job.status.is_terminal
                        or job.cancellation_requested.is_set()
                    ):
                        return
                    self._set_state_locked(
                        job,
                        status=JobStatus.RUNNING,
                        kind=EventKind.PROGRESS,
                        progress=round(max(0.0, min(1.0, progress)) * 100),
                        message=message or job.message,
                    )

            ctx = TaskContext(
                job_id=job_id,
                kind=self._active.kind if self._active else "",
                cancel_event=cancel_event,
                report=report,
            )

            result = task(ctx, **input) if input else task(ctx)  # type: ignore[operator]
            if isinstance(result, dict):
                result_message = result.get("message")
                warnings = result.get("warnings")
            else:
                result_message = None
                warnings = None
            if not result_message:
                result_message = self._resources.string("job.completed")

            with self._lock:
                job = self._get_active_locked(job_id)
                if job is not None and not job.status.is_terminal:
                    if job.cancellation_requested.is_set():
                        # Task returned after cancel was requested → CANCELLED
                        self._set_state_locked(
                            job,
                            status=JobStatus.CANCELLED,
                            kind=EventKind.JOB_CANCELLED,
                            message=self._resources.string("job.cancelled"),
                        )
                    elif warnings:
                        self._set_state_locked(
                            job,
                            status=JobStatus.COMPLETED_WITH_WARNINGS,
                            kind=EventKind.JOB_COMPLETED_WITH_WARNINGS,
                            progress=100,
                            message=result_message,
                        )
                    else:
                        self._set_state_locked(
                            job,
                            status=JobStatus.SUCCEEDED,
                            kind=EventKind.JOB_SUCCEEDED,
                            progress=100,
                            message=result_message,
                        )
        except Exception as exc:
            with self._lock:
                job = self._get_active_locked(job_id)
                if job is not None and not job.status.is_terminal:
                    self._set_state_locked(
                        job,
                        status=JobStatus.FAILED,
                        kind=EventKind.JOB_FAILED,
                        message=self._resources.string("job.failed", exc=exc),
                    )

    # ---- internals ----

    def _get_active_locked(self, job_id: str) -> _MutableJob | None:
        if self._active is None or self._active.job_id != job_id:
            return None
        return self._active

    def _set_state_locked(
        self,
        job: _MutableJob,
        *,
        status: JobStatus,
        kind: EventKind,
        message: str,
        progress: int | None = None,
    ) -> None:
        job.status = status
        job.message = message
        if progress is not None:
            job.progress = progress
        job.updated_at = _utc_now()
        self._emit_locked(job, kind)

    def _emit_locked(self, job: _MutableJob, kind: EventKind) -> None:
        self._event_bus.publish(
            RuntimeEvent(
                sequence=0,
                event_id=str(uuid4()),
                job_id=job.job_id,
                kind=kind,
                status=job.status,
                progress=job.progress,
                message=job.message,
                created_at=job.updated_at,
            )
        )

    @staticmethod
    def _snapshot_locked(job: _MutableJob) -> JobSnapshot:
        return JobSnapshot(
            job_id=job.job_id,
            kind=job.kind,
            status=job.status,
            progress=job.progress,
            message=job.message,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )


def demo_long_task(ctx: TaskContext, *, total_steps: int = 10, step_delay: float = 0.2) -> dict[str, Any]:
    """Built-in demo task: counts to ``total_steps`` unless cancelled.

    Registered as ``demo_long_task``. Real tools register their own task
    and never modify the runtime.
    """
    res = get_default()
    for step in range(1, total_steps + 1):
        if ctx.is_cancelled():
            return {"done": False, "message": res.string("demo.cancelled")}
        ctx.report_progress(step / total_steps, res.string("demo.progress", step=step, total=total_steps))
        time.sleep(step_delay)
    return {"done": True, "message": res.string("demo.completed")}


def _default_registry(total_steps: int, step_delay: float) -> ToolRegistry:
    """Build a registry with the built-in demo tool bound to the runtime's params."""
    registry = ToolRegistry()

    def _demo(ctx: TaskContext) -> dict[str, Any]:
        return demo_long_task(ctx, total_steps=total_steps, step_delay=step_delay)

    registry.register(
        ToolDescriptor(
            kind="demo_long_task",
            title="演示任务",
            group="demo",
            glyph="play",
            access_key="d",
            supports_input=False,
            task=_demo,
        )
    )
    return registry


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
