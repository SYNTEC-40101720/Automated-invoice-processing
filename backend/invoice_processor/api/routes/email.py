"""邮箱收件箱操作接口。"""

from __future__ import annotations

import threading

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

# 单飞锁：界面双击「拉取」时串行执行，避免并发拉取竞写
# processed_messages.json（后写者覆写前者）与同秒批次目录撞名。
_pull_lock = threading.Lock()


@router.post('/pull', response_model=EmailPullResponse)
def pull_email() -> EmailPullResponse:
    if not _pull_lock.acquire(blocking=False):
        raise ApplicationError(
            'EMAIL_PULL_IN_PROGRESS', '已有一次邮箱拉取正在进行，请稍候'
        )
    try:
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
            raise ApplicationError(
                'EMAIL_CONFIGURATION_INCOMPLETE', str(exc)
            ) from exc
        except Exception as exc:
            raise ApplicationError(
                'EMAIL_PULL_FAILED', f'邮箱拉取失败: {exc}'
            ) from exc
    finally:
        _pull_lock.release()

    return EmailPullResponse(pull=result, job=None)
