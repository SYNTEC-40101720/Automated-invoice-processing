"""项目集中配置

业务配置（税号、线程数）从 config.ini 读取，UI 配置（字体、窗口尺寸）保留为常量。
向后兼容：外部仍可 `from .config import TARGET_TAX_ID, MAX_WORKERS`。
"""
import os

from .config_manager import get_target_tax_id, get_max_workers

# ── 业务配置（从 config.ini 读取，首次运行自动生成默认配置）──
TARGET_TAX_ID = get_target_tax_id()
MAX_WORKERS = get_max_workers()

# ── UI 配置（常量，不外部化）──
WINDOW_GEOMETRY = (960, 820)
WINDOW_MIN_SIZE = (760, 700)

# 字体族（带 fallback，PySide6 会按顺序匹配已安装字体）
FONT_DISPLAY = 'Bahnschrift'           # 品牌/数字 - 几何浓缩感
FONT_UI = 'Microsoft YaHei UI'         # 中文正文
FONT_MONO = 'Cascadia Code'            # 等宽 / 日志 / 统计数字

# 字号梯度（参考 Microsoft Fluent 2 / Ant Design 字体阶梯，适配中文显示）
# 中文笔画密集，同等 px 下辨识度低于拉丁字母，故比主流设计系统上浮 1px
SIZE_DISPLAY = 24                       # 品牌主标题
SIZE_H1 = 18                            # 页面大标题
SIZE_H2 = 16                            # 卡片标题 / 区块标题
SIZE_BODY = 14                          # 正文 / 按钮 / 输入框
SIZE_SMALL = 13                         # 辅助说明 / 状态栏
SIZE_TINY = 12                          # 最低可读：等宽日志 / 元信息
SIZE_STAT = 34                          # 大号统计数字
SIZE_LOGO = 28                          # 侧栏 SYNTEC 字母


def reload_business_config() -> tuple[str, int]:
    """重新读取业务配置（UI 修改 config.ini 后调用）

    返回 (target_tax_id, max_workers)，并更新本模块常量。
    """
    global TARGET_TAX_ID, MAX_WORKERS
    TARGET_TAX_ID = get_target_tax_id()
    MAX_WORKERS = get_max_workers()
    return TARGET_TAX_ID, MAX_WORKERS
