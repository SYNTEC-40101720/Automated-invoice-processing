"""邮箱收件箱操作接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...application.job_service import JobService
from ..dependencies import get_job_service, require_local_token
from ..schemas import EmailPullResponse

router = APIRouter(
    prefix='/email',
    tags=['email'],
    dependencies=[Depends(require_local_token)],
)


@router.post('/pull', response_model=EmailPullResponse)
def pull_email(
    service: JobService = Depends(get_job_service),
) -> EmailPullResponse:
    result = service.pull_email_inbox()
    return EmailPullResponse(pull=result['pull'], job=result.get('job'))
