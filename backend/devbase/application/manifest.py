"""Declarative tool manifest — the NavCategory pattern, adapted.

Borrowed from Microsoft Calculator's ``NavCategoryStates.CategoryManifest``:
instead of a bare ``kind -> task`` map, each registered tool is a
*descriptor* carrying the metadata a workbench needs to render navigation
and a keyboard layer — title, group, glyph, access key, whether it takes
input — plus the task callable itself. The runtime looks a tool up by
``kind`` and uses ``descriptor.task``; the frontend renders the rail from
``registry.descriptors()``.

A new tool plugs in by registering a descriptor; it never touches the
runtime, the API, or the desktop layer:

    from devbase.application.manifest import ToolDescriptor, ToolRegistry
    from my_tool import my_task

    registry.register(ToolDescriptor(
        kind="my_tool",
        title="我的工具",
        group="tool",
        glyph="play",
        access_key="m",
        task=my_task,
    ))
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .task import Task, TaskNotFoundError


@dataclass(frozen=True, slots=True)
class ToolDescriptor:
    """A single tool's declarative metadata + optional task callable.

    Mirrors ``NavCategoryInitializer``: identity (``kind``), presentation
    (``title``/``subtitle``/``glyph``/``access_key``), grouping (``group``),
    capability flag (``supports_input``), execution model (``mode``), and
    the work itself (``task`` — None for system tools without a task).
    """

    kind: str
    title: str
    group: str
    glyph: str
    task: Task | None = None
    access_key: str | None = None
    supports_input: bool = False
    mode: str = "oneshot"
    subtitle: str | None = None
    # Optional opaque config the task may read at call time (e.g. limits).
    config: dict[str, Any] = field(default_factory=dict, hash=False, compare=False)


class ToolRegistry:
    """Maps ``kind`` -> :class:`ToolDescriptor`, ordered by group then kind.

    Replaces the older bare ``TaskRegistry``. The runtime looks a tool up
    by ``kind``; the frontend renders navigation from :meth:`descriptors`.
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolDescriptor] = {}

    def register(self, descriptor: ToolDescriptor) -> None:
        if not descriptor.kind:
            raise ValueError("tool kind must be non-empty")
        if descriptor.kind in self._tools:
            raise ValueError(f"tool kind already registered: {descriptor.kind!r}")
        self._tools[descriptor.kind] = descriptor

    def get(self, kind: str) -> ToolDescriptor:
        if kind not in self._tools:
            raise TaskNotFoundError(kind)
        return self._tools[kind]

    def has(self, kind: str) -> bool:
        return kind in self._tools

    def kinds(self) -> list[str]:
        return sorted(self._tools)

    def descriptors(self) -> list[ToolDescriptor]:
        """All descriptors, sorted by (group, kind) — stable for rendering."""
        return [self._tools[k] for k in sorted(self._tools, key=lambda k: (self._tools[k].group, k))]

    def groups(self) -> list[str]:
        """Distinct group names in registration order."""
        seen: dict[str, None] = {}
        for d in self._tools.values():
            seen.setdefault(d.group, None)
        return list(seen)


__all__ = ["ToolDescriptor", "ToolRegistry"]
