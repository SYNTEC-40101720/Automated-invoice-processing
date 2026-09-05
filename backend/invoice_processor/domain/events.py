"""跨应用层传递的领域事件。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DomainEvent:
    """事件总线对外暴露的统一事件信封。"""

    event_id: int
    type: str
    occurred_at: str
    job_id: str | None
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            'event_id': self.event_id,
            'type': self.type,
            'occurred_at': self.occurred_at,
            'job_id': self.job_id,
            'payload': self.payload,
        }
