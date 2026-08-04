"""配置管理：INI 文件读写（外部化业务配置）

配置文件位置：<程序目录>/config.ini
- 首次运行时从 template 创建
- 修改后下次启动生效（UI 设置入口实时保存）
"""
import configparser
import logging
import os
import sys

from .secret_store import PREFIX, decrypt, encrypt

logger = logging.getLogger(__name__)

# 默认配置（与原 config.py 硬编码值一致，保证向后兼容）
_DEFAULTS = {
    'business': {
        'target_tax_id': '91320594688334374M',
        'max_workers': '8',
    },
    'email': {
        'enabled': 'false',
        'imap_host': 'imap.qq.com',
        'imap_port': '993',
        'username': '',
        'auth_code': '',
        'inbox_dir': '发票收件箱',
        'days_back': '30',
        'poll_minutes': '0',
    },
    'ai': {
        'enabled': 'false',
        'api_key': '',
        'api_base': 'https://api.deepseek.com',
        'model': 'DeepSeek-V4-Flash',
        'timeout': '60',
    },
}

# 配置模板内容（用于首次生成 config.ini）
_TEMPLATE = """[business]
# 购买方税号（统一社会信用代码，18 位）—— 不一致的发票移入「税号异常」
target_tax_id = 91320594688334374M
# 并发线程数（项目约定：无论文件数多少，固定 8 线程）
max_workers = 8

[email]
# 邮箱自动拉取开关（true/false）
enabled = false
# IMAP 服务器与端口（QQ 邮箱默认 imap.qq.com:993）
imap_host = imap.qq.com
imap_port = 993
# 邮箱账号（发票转发到此邮箱）
username =
# IMAP 授权码（QQ 邮箱设置→账户→开启 IMAP 服务后生成，非登录密码）
# 保存时经 Windows DPAPI 加密（dpapi: 前缀），config.ini 不保留明文
auth_code =
# 本地发票收件箱目录（相对程序目录或绝对路径）
inbox_dir = 发票收件箱
# 只拉取最近 N 天的邮件
days_back = 30
# 自动轮询间隔（分钟，0 = 不自动轮询，仅手动拉取）
poll_minutes = 0

[ai]
# AI 审核开关（true/false）—— 处理完成后自动审核发票与行程
enabled = false
# DeepSeek API Key（https://platform.deepseek.com 申请，sk- 开头）
# 保存时经 Windows DPAPI 加密（dpapi: 前缀），config.ini 不保留明文
api_key =
# API 接口地址（OpenAI 兼容）
api_base = https://api.deepseek.com
# 模型名
model = DeepSeek-V4-Flash
# 请求超时（秒）
timeout = 60
"""


def _get_program_dir() -> str:
    """定位程序所在目录（兼容 PyInstaller 打包后场景）"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(sys.argv[0]))


def get_config_path() -> str:
    """返回 config.ini 的绝对路径"""
    return os.path.join(_get_program_dir(), 'config.ini')


def _ensure_config_exists() -> None:
    """若 config.ini 不存在，从模板创建一份"""
    path = get_config_path()
    if not os.path.exists(path):
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(_TEMPLATE)
            logger.info(f"已生成配置文件: {path}")
        except OSError as e:
            logger.warning(f"无法创建配置文件 {path}: {e}，将使用默认配置")


def load_config() -> configparser.ConfigParser:
    """加载配置（若文件不存在则先创建模板）

    返回 ConfigParser 实例，业务配置位于 [business] 段。
    """
    _ensure_config_exists()
    cfg = configparser.ConfigParser()
    # 先加载默认值，再读取文件覆盖
    cfg.read_dict(_DEFAULTS)
    try:
        cfg.read(get_config_path(), encoding='utf-8')
    except (OSError, configparser.Error) as e:
        logger.warning(f"读取配置失败: {e}，将使用默认配置")
    return cfg


def save_config(cfg: configparser.ConfigParser) -> None:
    """保存配置到 config.ini"""
    path = get_config_path()
    try:
        with open(path, 'w', encoding='utf-8') as f:
            cfg.write(f)
        logger.info(f"配置已保存: {path}")
    except OSError as e:
        logger.error(f"保存配置失败: {e}")
        raise


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
    cfg = load_config()
    if not cfg.has_section('business'):
        cfg.add_section('business')
    cfg.set('business', 'target_tax_id', target_tax_id)
    cfg.set('business', 'max_workers', str(max(2, min(16, max_workers))))
    save_config(cfg)


# ── 邮箱配置（自动拉取发票）──────────────────────────────

def get_email_config() -> dict:
    """读取邮箱拉取配置（缺失字段用默认值）"""
    cfg = load_config()
    return {k: cfg.get('email', k, fallback=v) for k, v in _DEFAULTS['email'].items()}


def get_email_enabled() -> bool:
    """邮箱拉取是否启用"""
    return get_email_config()['enabled'].lower() in ('1', 'true', 'yes', 'on')


def get_email_username() -> str:
    """邮箱账号"""
    return get_email_config()['username'].strip()


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
    return decrypt(raw)


def get_inbox_dir() -> str:
    """本地发票收件箱目录（相对路径基于程序目录解析为绝对路径）"""
    raw = get_email_config()['inbox_dir'].strip() or '发票收件箱'
    if os.path.isabs(raw):
        return raw
    return os.path.join(_get_program_dir(), raw)


def get_email_poll_minutes() -> int:
    """自动轮询间隔（分钟，0 = 不轮询）"""
    try:
        return max(0, int(get_email_config()['poll_minutes']))
    except (ValueError, TypeError):
        return 0


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
    cfg = load_config()
    if not cfg.has_section('email'):
        cfg.add_section('email')
    for k, v in kwargs.items():
        if k in _DEFAULTS['email']:
            if k == 'auth_code' and v and not str(v).startswith(PREFIX):
                v = encrypt(str(v))
            cfg.set('email', k, str(v))
    save_config(cfg)


# ── AI 审核配置 ────────────────────────────────────────

def get_ai_config() -> dict:
    """读取 AI 审核配置（缺失字段用默认值）"""
    cfg = load_config()
    return {k: cfg.get('ai', k, fallback=v) for k, v in _DEFAULTS['ai'].items()}


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
    return decrypt(raw)


def get_ai_api_base() -> str:
    return get_ai_config()['api_base'].strip() or 'https://api.deepseek.com'


def get_ai_model() -> str:
    return get_ai_config()['model'].strip() or 'DeepSeek-V4-Flash'


def get_ai_timeout() -> int:
    try:
        return max(10, int(get_ai_config()['timeout']))
    except (ValueError, TypeError):
        return 60


def set_ai_config(**kwargs) -> None:
    """便捷写入：AI 配置。仅接受 _DEFAULTS['ai'] 中的键。

    api_key 明文写入时自动经 DPAPI 加密，config.ini 不保留明文。
    """
    cfg = load_config()
    if not cfg.has_section('ai'):
        cfg.add_section('ai')
    for k, v in kwargs.items():
        if k in _DEFAULTS['ai']:
            if k == 'api_key' and v and not str(v).startswith(PREFIX):
                v = encrypt(str(v))
            cfg.set('ai', k, str(v))
    save_config(cfg)
