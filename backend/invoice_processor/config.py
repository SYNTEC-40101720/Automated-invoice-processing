"""项目集中配置。

业务配置（税号、线程数）从 config.ini 读取。
"""

from .config_manager import get_max_workers, get_target_tax_id

# ── 业务配置（从 config.ini 读取，首次运行自动生成默认配置）──
TARGET_TAX_ID = get_target_tax_id()
MAX_WORKERS = get_max_workers()

def reload_business_config() -> tuple[str, int]:
    """重新读取业务配置并更新本模块常量。"""
    global TARGET_TAX_ID, MAX_WORKERS
    TARGET_TAX_ID = get_target_tax_id()
    MAX_WORKERS = get_max_workers()
    return TARGET_TAX_ID, MAX_WORKERS
