"""应用层稳定错误码。"""

from __future__ import annotations

from typing import Any


class ApplicationError(Exception):
    """可安全转换为 API 错误响应的应用异常。"""

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class JobAlreadyRunning(ApplicationError):
    def __init__(self, job_id: str):
        super().__init__(
            'JOB_ALREADY_RUNNING',
            '已有任务正在处理',
            {'job_id': job_id},
        )


class JobNotFound(ApplicationError):
    def __init__(self, job_id: str):
        super().__init__('JOB_NOT_FOUND', f'任务不存在: {job_id}', {'job_id': job_id})


class InvalidSourceDirectory(ApplicationError):
    def __init__(self, source_dir: str):
        super().__init__(
            'INVALID_SOURCE_DIRECTORY',
            f'源目录不存在或不可访问: {source_dir}',
            {'source_dir': source_dir},
        )


class NoPdfFiles(ApplicationError):
    def __init__(self, source_dir: str):
        super().__init__(
            'NO_PDF_FILES',
            f'源目录中未找到 PDF 文件: {source_dir}',
            {'source_dir': source_dir},
        )


class InvalidJobTransition(ApplicationError):
    def __init__(self, current: str, target: str):
        super().__init__(
            'INVALID_JOB_TRANSITION',
            f'不允许任务状态从 {current} 变更为 {target}',
            {'current': current, 'target': target},
        )


class EventStreamClosed(RuntimeError):
    """事件订阅已关闭。"""
