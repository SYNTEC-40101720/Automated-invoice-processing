"""API 异常转换。"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from ..domain.errors import ApplicationError


async def application_error_handler(
    request: Request,
    exc: ApplicationError,
) -> JSONResponse:
    status_code = {
        'JOB_ALREADY_RUNNING': 409,
        'JOB_NOT_FOUND': 404,
        'NO_PDF_FILES': 422,
        'INVALID_SOURCE_DIRECTORY': 422,
        'INVALID_JOB_TRANSITION': 409,
        'EMAIL_CONFIGURATION_INCOMPLETE': 422,
        'EMAIL_CONNECTION_FAILED': 502,
        'EMAIL_PULL_FAILED': 502,
        'AI_CONFIGURATION_INCOMPLETE': 422,
        'AI_CONNECTION_FAILED': 502,
    }.get(exc.code, 400)
    return JSONResponse(
        status_code=status_code,
        content={
            'error': {
                'code': exc.code,
                'message': exc.message,
                'details': exc.details,
            }
        },
    )
