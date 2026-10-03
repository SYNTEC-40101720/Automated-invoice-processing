"""配置管理：INI 文件读写（外部化业务配置）

配置文件位置：<程序目录>/config.ini
- 首次运行时从 template 创建
- 修改后下次启动生效（UI 设置入口实时保存）
"""
import configparser
import logging
import os
import sys
import threading

from devbase.config_manager import ConfigManager

from .secret_store import PREFIX, decrypt, encrypt

logger = logging.getLogger(__name__)
_CONFIG_LOCK = threading.RLock()
_CONFIG_STORES: dict[str, ConfigManager] = {}

# 默认配置（与原 config.py 硬编码值一致，保证向后兼容）
_DEFAULTS = {
    'business': {
        'target_tax_id': '91320594688334374M',
        'max_workers': '8',
    },
    'email': {
        'imap_host': 'imap.qq.com',
        'imap_port': '993',
        'username': '',
        'auth_code': '',
        'inbox_dir': '发票收件箱',
        'days_back': '30',
        'senders': (
            '12306@rails.com.cn,didifapiao@mailgate.xiaojukeji.com,'
            'fapiao@mailgate.hongyibo.com.cn,invoice@invoice01.huazhuhotels.com,'
            'service@invoice.txffp.com'
        ),
        'keywords': '发票,行程单,报销',
    },
    'ai': {
        'enabled': 'false',
        'api_key': '',
        'api_base': 'https://api.deepseek.com',
        'model': 'deepseek-v4-flash',
        'timeout': '60',
    },
}



def _get_program_dir() -> str:
    """定位程序所在目录（兼容 PyInstaller 打包后场景）"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(sys.argv[0]))


def get_config_path() -> str:
    """返回 config.ini 的绝对路径"""
    return os.path.join(_get_program_dir(), 'config.ini')


def _get_config_store() -> ConfigManager:
    path = os.path.abspath(get_config_path())
    with _CONFIG_LOCK:
        store = _CONFIG_STORES.get(path)
        if store is None:
            store = ConfigManager(path, defaults=_DEFAULTS)
            _CONFIG_STORES[path] = store
        return store


def _ensure_config_exists() -> None:
    """若 config.ini 不存在，从模板创建一份"""
    config_path = os.path.abspath(get_config_path())
    if not os.path.isfile(config_path):
        _get_config_store().reload_config()


def load_config() -> configparser.ConfigParser:
    """加载配置（若文件不存在则先创建模板）

    返回 ConfigParser 实例，业务配置位于 [business] 段。
    interpolation=None：配置值允许含 %（与 devbase 读写口径一致）；
    utf-8-sig：容忍用户用记事本等编辑器留下的 BOM，防止首段被
    丢弃后整套配置被默认值覆写。
    """
    with _CONFIG_LOCK:
        _ensure_config_exists()
        cfg = configparser.ConfigParser(interpolation=None)
        # 先加载默认值，再读取文件覆盖
        cfg.read_dict(_DEFAULTS)
        try:
            cfg.read(get_config_path(), encoding='utf-8-sig')
        except (OSError, UnicodeDecodeError, configparser.Error) as e:
            # UnicodeDecodeError 属 ValueError：GBK/ANSI 编码的文件在此
            # 兜底，避免应用在 import 阶段（setup_logging 之前）崩溃。
            logger.warning(f"读取配置失败: {e}，将使用默认配置")
        return cfg


def save_config(cfg: configparser.ConfigParser) -> None:
    """保存配置到 config.ini"""
    values = {
        section: {
            option: value
            for option, value in cfg.items(section, raw=True)
        }
        for section in cfg.sections()
    }
    _get_config_store().replace(values)
    logger.info('配置已保存: %s', get_config_path())


def _set_section_values(
    cfg: configparser.ConfigParser,
    section: str,
    values: dict,
    secret_key: str | None = None,
) -> None:
    if not cfg.has_section(section):
        cfg.add_section(section)
    for key, value in values.items():
        if key not in _DEFAULTS[section] or value is None:
            continue
        if key == secret_key and value and not str(value).startswith(PREFIX):
            value = encrypt(str(value))
        cfg.set(section, key, str(value))


def set_all_config(
    *,
    business: dict | None = None,
    email: dict | None = None,
    ai: dict | None = None,
) -> None:
    """一次性保存多段配置，避免前端连续 PATCH 留下半套配置。"""
    with _CONFIG_LOCK:
        cfg = load_config()
        if business:
            business = dict(business)
            if business.get('max_workers') is not None:
                business['max_workers'] = max(
                    2, min(16, int(business['max_workers']))
                )
            _set_section_values(cfg, 'business', business)
        if email:
            email = dict(email)
            for list_key in ('senders', 'keywords'):
                if list_key in email and isinstance(email[list_key], (list, tuple)):
                    email[list_key] = ','.join(
                        str(item).strip()
                        for item in email[list_key]
                        if str(item).strip()
                    )
            _set_section_values(cfg, 'email', email, secret_key='auth_code')
        if ai:
            _set_section_values(cfg, 'ai', ai, secret_key='api_key')
        save_config(cfg)


def get_target_tax_id() -> str:
    """便捷读取：购买方税号"""
    return load_config().get('business', 'target_tax_id',
                             fallback=_DEFAULTS['business']['target_tax_id'])


def get_max_workers() -> int:
    """便捷读取：并发线程数"""
    cfg = load_config()
    try:
        workers = cfg.getint('business', 'max_workers',
                             fallback=int(_DEFAULTS['business']['max_workers']))
        # 限制合理范围 2-16
        return max(2, min(16, workers))
    except (ValueError, configparser.Error):
        return int(_DEFAULTS['business']['max_workers'])


def set_business_config(target_tax_id: str, max_workers: int) -> None:
    """便捷写入：业务配置（税号 + 线程数）"""
    set_all_config(business={
        'target_tax_id': target_tax_id,
        'max_workers': max_workers,
    })


def _safe_get(cfg: configparser.ConfigParser, section: str, key: str,
              fallback: str) -> str:
    """单键容错读取：单键损坏不拖垮整个配置段"""
    try:
        return cfg.get(section, key, fallback=fallback)
    except (configparser.Error, ValueError):
        return fallback


# ── 邮箱配置（自动拉取发票）──────────────────────────────

def get_email_config() -> dict:
    """读取邮箱拉取配置（缺失字段用默认值）"""
    cfg = load_config()
    return {k: _safe_get(cfg, 'email', k, v) for k, v in _DEFAULTS['email'].items()}


def get_email_senders() -> list[str]:
    """发票发件方白名单；配置为空时使用内置默认名单。"""
    return _parse_email_list(get_email_config().get('senders', ''))


def get_email_keywords() -> list[str]:
    """邮件主题关键词白名单。"""
    return _parse_email_list(get_email_config().get('keywords', ''))


def _parse_email_list(raw) -> list[str]:
    senders = []
    seen = set()
    for item in str(raw).replace('\n', ',').split(','):
        value = item.strip()
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            senders.append(value)
    return senders


def get_email_username() -> str:
    """邮箱账号"""
    return get_email_config()['username'].strip()


def _decrypt_or_empty(raw: str) -> str:
    """解密 dpapi: 密文；损坏或跨机器迁移导致解密失败时按未配置处理。

    设置页依赖本函数的返回值渲染 auth_code_configured / api_key_configured，
    抛异常会让 GET/PATCH /settings 整体 500，用户反而无法重填授权码。
    """
    if not raw:
        return ''
    try:
        return decrypt(raw)
    except Exception as exc:
        logger.warning('密文解密失败，按未配置处理: %s', exc)
        return ''


def get_email_auth_code() -> str:
    """IMAP 授权码（dpapi: 密文自动解密；历史明文自动迁移为加密存储）"""
    raw = get_email_config()['auth_code'].strip()
    if raw and not raw.startswith(PREFIX):
        # 历史版本明文 → 加密写回，config.ini 不再保留明文
        try:
            set_email_config(auth_code=raw)
            logger.info('邮箱授权码已迁移为加密存储')
        except (OSError, ValueError):
            logger.warning('邮箱授权码迁移加密失败，仍按明文使用')
    return _decrypt_or_empty(raw)


def get_inbox_dir() -> str:
    """本地发票收件箱目录（相对路径基于程序目录解析为绝对路径）"""
    # expanduser 与 job_service.is_known_directory 的归一化口径一致
    raw = os.path.expanduser(
        get_email_config()['inbox_dir'].strip() or '发票收件箱'
    )
    if os.path.isabs(raw):
        return raw
    return os.path.join(_get_program_dir(), raw)


def get_email_days_back() -> int:
    """只拉取最近 N 天"""
    try:
        return max(1, int(get_email_config()['days_back']))
    except (ValueError, TypeError):
        return 30


def set_email_config(**kwargs) -> None:
    """便捷写入：邮箱配置。仅接受 _DEFAULTS['email'] 中的键。

    auth_code 明文写入时自动经 DPAPI 加密，config.ini 不保留明文。
    """
    set_all_config(email=kwargs)


# ── AI 审核配置 ────────────────────────────────────────

def get_ai_config() -> dict:
    """读取 AI 审核配置（缺失字段用默认值）"""
    cfg = load_config()
    return {k: _safe_get(cfg, 'ai', k, v) for k, v in _DEFAULTS['ai'].items()}


def get_ai_enabled() -> bool:
    """AI 审核是否启用"""
    return get_ai_config()['enabled'].lower() in ('1', 'true', 'yes', 'on')


def get_ai_api_key() -> str:
    """DeepSeek API Key（dpapi: 密文自动解密；历史明文自动迁移为加密存储）"""
    raw = get_ai_config()['api_key'].strip()
    if raw and not raw.startswith(PREFIX):
        # 历史版本明文 → 加密写回，config.ini 不再保留明文
        try:
            set_ai_config(api_key=raw)
            logger.info('AI API Key 已迁移为加密存储')
        except (OSError, ValueError):
            logger.warning('AI API Key 迁移加密失败，仍按明文使用')
    return _decrypt_or_empty(raw)


def get_ai_api_base() -> str:
    return get_ai_config()['api_base'].strip() or 'https://api.deepseek.com'


def get_ai_model() -> str:
    return get_ai_config()['model'].strip() or 'deepseek-v4-flash'


def get_ai_timeout() -> int:
    try:
        return max(10, int(get_ai_config()['timeout']))
    except (ValueError, TypeError):
        return 60


def set_ai_config(**kwargs) -> None:
    """便捷写入：AI 配置。仅接受 _DEFAULTS['ai'] 中的键。

    api_key 明文写入时自动经 DPAPI 加密，config.ini 不保留明文。
    """
    set_all_config(ai=kwargs)
