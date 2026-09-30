"""运行时稳定错误码（可转换为项目错误信封）与流关闭信号。"""

from __future__ import annotations


class DevBaseRuntimeError(RuntimeError):
    """携带稳定错误码的运行时错误，API 层转换为 ``{"error": {...}}`` 信封。"""

    code: str = "INTERNAL_ERROR"
    message: str = "运行时错误"

    def __init__(self, detail: str | None = None) -> None:
        # detail 供日志/排查使用；信封始终输出类级中文 message。
        super().__init__(detail or self.message)
        self.detail = detail


class JobAlreadyRunningError(DevBaseRuntimeError):
    """Raised when a second non-terminal job is requested."""

    code = "JOB_ALREADY_RUNNING"
    message = "已有任务正在处理"


class NoCurrentJobError(DevBaseRuntimeError):
    """Raised when an operation requires a current job but none exists."""

    code = "NO_CURRENT_JOB"
    message = "当前没有正在运行的任务"


class JobNotCancellableError(DevBaseRuntimeError):
    """Raised when the current job has already reached a terminal state."""

    code = "JOB_NOT_CANCELLABLE"
    message = "当前任务已结束，无法停止"


class EventStreamClosed(RuntimeError):
    """事件订阅已关闭（慢客户端溢出或总线主动关闭）。"""