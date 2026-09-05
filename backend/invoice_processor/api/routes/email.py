"""邮箱收件箱操作接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...config_manager import (
    get_email_auth_code,
    get_email_config,
    get_email_days_back,
    get_email_keywords,
    get_email_senders,
    get_email_username,
    get_inbox_dir,
)
from ...core.email_pull import pull_invoices
from ...domain.errors import ApplicationError
from ..dependencies import require_local_token
from ..schemas import EmailPullResponse

router = APIRouter(
    prefix='/email',
    tags=['email'],
    dependencies=[Depends(require_local_token)],
)


@router.post('/pull', response_model=EmailPullResponse)
def pull_email() -> EmailPullResponse:
    config = get_email_config()
    try:
        result = pull_invoices(
            host=str(config['imap_host']),
            port=int(config['imap_port']),
            username=get_email_username(),
            auth_code=get_email_auth_code(),
            inbox_dir=get_inbox_dir(),
            days_back=get_email_days_back(),
            senders=get_email_senders(),
            keywords=get_email_keywords(),
        )
    except ValueError as exc:
        raise ApplicationError('EMAIL_CONFIGURATION_INCOMPLETE', str(exc)) from exc
    except Exception as exc:
        raise ApplicationError('EMAIL_PULL_FAILED', f'邮箱拉取失败: {exc}') from exc

    return EmailPullResponse(pull=result, job=None)
