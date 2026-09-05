from dataclasses import dataclass
from enum import StrEnum
from typing import Callable


class WindowCloseMode(StrEnum):
    STOP_ON_CLOSE = "stop_on_close"
    CONTINUE_ON_CLOSE = "continue_on_close"


@dataclass(frozen=True, slots=True)
class LifecyclePolicy:
    """Window policy; the template default is to continue tasks on close."""

    close_mode: WindowCloseMode = WindowCloseMode.CONTINUE_ON_CLOSE


@dataclass(frozen=True, slots=True)
class WindowCloseResult:
    mode: WindowCloseMode
    stop_requested: bool


class WindowLifecycle:
    """Adapter boundary for a future pywebview/native window callback."""

    def __init__(
        self,
        policy: LifecyclePolicy | None = None,
        *,
        stop_active_job: Callable[[], bool] | None = None,
    ) -> None:
        self.policy = policy or LifecyclePolicy()
        self._stop_active_job = stop_active_job

    def handle_window_close(self) -> WindowCloseResult:
        if self.policy.close_mode is WindowCloseMode.CONTINUE_ON_CLOSE:
            return WindowCloseResult(
                mode=self.policy.close_mode,
                stop_requested=False,
            )
        if self._stop_active_job is None:
            return WindowCloseResult(
                mode=self.policy.close_mode,
                stop_requested=False,
            )
        return WindowCloseResult(
            mode=self.policy.close_mode,
            stop_requested=self._stop_active_job(),
        )