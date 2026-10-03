"""邮箱收件箱操作接口。"""

from __future__ import annotations

import threading

from devbase.application.errors import DevBaseRuntimeError
from devbase.application.job_runtime import JobRuntime
from fastapi import APIRouter, Depends

from ...application.invoice_task import INVOICE_TOOL_KIND, validate_start_input
from ...config_manager import (
    get_email_auth_code,
    get_email_auto_process,
    get_email_config,
    get_email_days_back,
    get_email_keywords,
    get_email_senders,
    get_email_username,
    get_inbox_dir,
)
from ...core.email_pull import pull_invoices
from ...domain.errors import ApplicationError
from ..dependencies import get_devbase_runtime, require_local_token
from ..schemas import EmailPullResponse

router = APIRouter(
    prefix='/email',
    tags=['email'],
    dependencies=[Depends(require_local_token)],
)

# 单飞锁：界面双击「拉取」时串行执行，避免并发拉取竞写
# processed_messages.json（后写者覆写前者）与同秒批次目录撞名。
# 自动启动任务也在临界区内完成（runtime.start 只建线程不阻塞）。
_pull_lock = threading.Lock()


def _maybe_start_auto_job(result: dict, runtime: JobRuntime) -> dict | None:
    """开启自动处理且拉到新附件时，以 email 触发处理本次批次目录。

    启动失败不失败整个拉取响应：附件保留在批次目录，经 job_error
    反馈原因，用户可稍后在处理页手动开始。
    """
    if not result.get('new_files') or not get_email_auto_process():
        return None
    source_dir = result.get('session_dir')
    if not source_dir:
        result['job_error'] = {
            'code': 'AUTO_PROCESS_SESSION_DIR_MISSING',
            'message': '未能确定本次拉取批次目录，自动处理未启动',
        }
        return None
    try:
        validate_start_input({'source_dir': source_dir, 'trigger': 'email'})
        snapshot = runtime.start(
            INVOICE_TOOL_KIND,
            input={'source_dir': source_dir, 'trigger': 'email'},
        )
    except (ApplicationError, DevBaseRuntimeError) as exc:
        code = getattr(exc, 'code', 'AUTO_PROCESS_FAILED')
        message = str(exc.message) if hasattr(exc, 'message') else str(exc)
        result['job_error'] = {'code': code, 'message': message}
        return None
    return {
        'id': snapshot.job_id,
        'kind': snapshot.kind,
        'status': snapshot.status.value,
        'progress': snapshot.progress,
        'message': snapshot.message,
        'created_at': snapshot.created_at.isoformat(),
        'updated_at': snapshot.updated_at.isoformat(),
    }


@router.post('/pull', response_model=EmailPullResponse)
def pull_email(
    runtime: JobRuntime = Depends(get_devbase_runtime),
) -> EmailPullResponse:
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
        job = _maybe_start_auto_job(result, runtime)
    finally:
        _pull_lock.release()

    return EmailPullResponse(pull=result, job=job)
