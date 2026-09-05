"""Domain ports — the contracts an engine declares it needs.

The *engine* (domain) declares what it needs as abstract ports, the
*host* (application) implements them. This is inversion of control — the
domain never imports FastAPI, threading, or any framework; it only
describes the holes a host must fill.

ProgressSink is the minimal port a one-shot task uses (report a 0..1
progress + message, observe cancellation). TaskContext in the application
layer implements it. It is a typing.Protocol (structural): any object with
the right methods satisfies it — no inheritance required.

When a new tool needs richer host interaction, declare a new port here and
implement it in the application layer; the domain stays framework-free.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ProgressSink(Protocol):
    """Minimal port for a one-shot background task.

    The runtime owns a concrete implementation (TaskContext) and passes
    it in; task bodies only call report_progress and is_cancelled.
    """

    def report_progress(self, progress: float, message: str = "") -> None:
        """Report progress in [0.0, 1.0] and an optional human message."""
        ...

    def is_cancelled(self) -> bool:
        """True if the host requested cancellation."""
        ...


__all__ = ["ProgressSink"]
