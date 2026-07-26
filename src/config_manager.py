"""配置管理：INI 文件读写（外部化业务配置）

配置文件位置：<程序目录>/config.ini
- 首次运行时从 template 创建
- 修改后下次启动生效（UI 设置入口实时保存）
"""
import configparser
import logging
import os
import sys

logger = logging.getLogger(__name__)

# 默认配置（与原 config.py 硬编码值一致，保证向后兼容）
_DEFAULTS = {
    'business': {
        'target_tax_id': '91320594688334374M',
        'max_workers': '8',
    },
}

# 配置模板内容（用于首次生成 config.ini）
_TEMPLATE = """[business]
# 购买方税号（统一社会信用代码，18 位）—— 不一致的发票移入「税号异常」
target_tax_id = 91320594688334374M
# 并发线程数（项目约定：无论文件数多少，固定 8 线程）
max_workers = 8
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
