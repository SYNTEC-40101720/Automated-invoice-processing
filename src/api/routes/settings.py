"""本地配置的脱敏读写接口。"""

from __future__ import annotations

import imaplib

from fastapi import APIRouter, Depends

from ...core.ai_audit import test_connection as test_ai_connection
from ...config_manager import (
    get_ai_api_base,
    get_ai_api_key,
    get_ai_enabled,
    get_ai_model,
    get_ai_timeout,
    get_email_auth_code,
    get_email_config,
    get_email_days_back,
    get_email_enabled,
    get_email_poll_minutes,
    get_email_username,
    get_max_workers,
    get_target_tax_id,
    set_ai_config,
    set_business_config,
    set_email_config,
)
from ...domain.errors import ApplicationError
from ..dependencies import require_local_token
from ..schemas import (
    AiSettings,
    AiSettingsPatch,
    AiTestResponse,
    BusinessSettings,
    BusinessSettingsPatch,
    EmailSettings,
    EmailSettingsPatch,
    EmailTestResponse,
    SettingsResponse,
)

router = APIRouter(
    prefix='/settings',
    tags=['settings'],
    dependencies=[Depends(require_local_token)],
)


def _settings() -> SettingsResponse:
    email = get_email_config()
    return SettingsResponse(
        business=BusinessSettings(
            target_tax_id=get_target_tax_id(),
            max_workers=get_max_workers(),
        ),
        email=EmailSettings(
            enabled=get_email_enabled(),
            imap_host=str(email['imap_host']),
            imap_port=int(email['imap_port']),
            username=get_email_username(),
            inbox_dir=str(email['inbox_dir']),
            days_back=get_email_days_back(),
            poll_minutes=get_email_poll_minutes(),
            auth_code_configured=bool(get_email_auth_code()),
        ),
        ai=AiSettings(
            enabled=get_ai_enabled(),
            api_base=get_ai_api_base(),
            model=get_ai_model(),
            timeout=get_ai_timeout(),
            api_key_configured=bool(get_ai_api_key()),
        ),
    )


@router.get('', response_model=SettingsResponse)
def get_settings() -> SettingsResponse:
    return _settings()


@router.patch('/business', response_model=BusinessSettings)
def patch_business(request: BusinessSettingsPatch) -> BusinessSettings:
    values = request.model_dump(exclude_unset=True)
    set_business_config(
        values.get('target_tax_id', get_target_tax_id()),
        values.get('max_workers', get_max_workers()),
    )
    return _settings().business


@router.patch('/email', response_model=EmailSettings)
def patch_email(request: EmailSettingsPatch) -> EmailSettings:
    values = {
        key: value
        for key, value in request.model_dump(exclude_unset=True).items()
        if value is not None
    }
    if values:
        set_email_config(**values)
    return _settings().email


@router.patch('/ai', response_model=AiSettings)
def patch_ai(request: AiSettingsPatch) -> AiSettings:
    values = {
        key: value
        for key, value in request.model_dump(exclude_unset=True).items()
        if value is not None
    }
    if values:
        set_ai_config(**values)
    return _settings().ai


@router.post('/ai/test', response_model=AiTestResponse)
def test_ai(request: AiSettingsPatch) -> AiTestResponse:
    values = request.model_dump(exclude_unset=True)
    api_base = values.get('api_base', get_ai_api_base())
    model = values.get('model', get_ai_model())
    timeout = values.get('timeout', get_ai_timeout())
    api_key = values.get('api_key')
    if api_key is None:
        api_key = get_ai_api_key()
    if not api_base or not model or not api_key:
        raise ApplicationError(
            'AI_CONFIGURATION_INCOMPLETE',
            '请先配置 AI 接口地址、模型和 API Key',
        )
    try:
        test_ai_connection(
            api_key,
            api_base=api_base,
            model=model,
            timeout=timeout,
        )
    except Exception as exc:
        raise ApplicationError('AI_CONNECTION_FAILED', f'AI 连接失败: {exc}') from exc
    return AiTestResponse(ok=True, message='AI 接口连接成功，配置可用')


@router.post('/email/test', response_model=EmailTestResponse)
def test_email(request: EmailSettingsPatch) -> EmailTestResponse:
    values = request.model_dump(exclude_unset=True)
    current = get_email_config()
    host = values.get('imap_host', current['imap_host'])
    port = values.get('imap_port', int(current['imap_port']))
    username = values.get('username', get_email_username())
    auth_code = values.get('auth_code')
    if auth_code is None:
        auth_code = get_email_auth_code()
    if not username or not auth_code:
        raise ApplicationError(
            'EMAIL_CONFIGURATION_INCOMPLETE',
            '请先配置邮箱账号和 IMAP 授权码',
        )
    mail = None
    try:
        mail = imaplib.IMAP4_SSL(host, port, timeout=10)
        mail.login(username, auth_code)
    except Exception as exc:
        raise ApplicationError('EMAIL_CONNECTION_FAILED', f'邮箱连接失败: {exc}') from exc
    finally:
        if mail is not None:
            try:
                mail.logout()
            except Exception:
                pass
    return EmailTestResponse(ok=True, message='IMAP 登录成功，配置可用')
