"""Resource provider — key-based string lookup.

Borrowed from Microsoft Calculator's ``AppResourceProvider``: user-facing
strings are never hard-coded in logic; they live behind a resource key and
are resolved through a provider. The template ships an in-process Chinese
table; a real deployment can swap in a locale-aware provider without
touching domain/application logic.

    from devbase.domain.resources import ResourceProvider, get_default

    provider = get_default()
    msg = provider.string("job.queued", kind="demo")  # -> "任务已排队: demo"

Format args are passed as keyword arguments and fill ``{name}`` slots, so
the domain never builds localized strings itself.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ResourceProvider(Protocol):
    """Resolves a resource key to a localized/format string."""

    def string(self, key: str, /, **kwargs: object) -> str:
        """Return the string for ``key``, formatting in ``**kwargs``."""
        ...


class InMemoryResourceProvider:
    """A plain dict-backed provider with the template's default Chinese strings.

    Unknown keys fall back to the key itself so logic never crashes on a
    missing string — the key shows through, making gaps obvious.
    """

    _TABLE: dict[str, str] = {
        "job.queued": "任务已排队: {kind}",
        "job.running": "任务运行中: {kind}",
        "job.cancelling": "任务取消中…",
        "job.completed": "任务已完成",
        "job.cancelled": "任务已取消",
        "job.failed": "任务失败: {exc}",
        "demo.progress": "演示任务进度 {step}/{total}",
        "demo.completed": "演示任务已完成",
        "demo.cancelled": "任务已取消",
    }

    def __init__(self, table: dict[str, str] | None = None) -> None:
        self._table = dict(self._TABLE)
        if table is not None:
            self._table.update(table)

    def string(self, key: str, /, **kwargs: object) -> str:
        template = self._table.get(key, key)
        try:
            return template.format(**kwargs) if kwargs else template
        except (KeyError, IndexError):
            return template


_DEFAULT: InMemoryResourceProvider | None = None


def get_default() -> InMemoryResourceProvider:
    """Process-wide default provider (lazily allocated)."""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = InMemoryResourceProvider()
    return _DEFAULT


__all__ = ["ResourceProvider", "InMemoryResourceProvider", "get_default"]
