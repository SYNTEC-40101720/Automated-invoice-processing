# ═══════════════════════════════════════════════════════════
# 墨韵 (Atelier) 色彩系统
# 美学方向：编辑级精度仪表盘 —— 深墨侧栏 + 暖纸画布 + 朱砂重点
# ═══════════════════════════════════════════════════════════


class Palette:
    """Atelier 墨韵调色板"""

    # ── 深墨表面（侧栏 / 状态栏）──
    INK = '#16161A'                # 主深色 - 近黑微冷
    INK_RAISED = '#1F1F24'         # 凸起深色表面
    INK_BORDER = '#2E2E36'         # 深色边框
    ON_INK = '#FAFAF9'             # 深色上的主文字
    ON_INK_MUTED = '#8B8B95'       # 深色上的次要文字
    ON_INK_SUBTLE = '#52525B'      # 深色上的最弱文字

    # ── 暖纸表面（画布 / 卡片）──
    PAPER = '#F7F3EA'              # 主背景 - 暖米色（宣纸感）
    CARD = '#FFFFFF'               # 卡片白
    CARD_HOVER = '#FDFBF6'         # 卡片 hover
    BORDER = '#E7E0D0'             # 暖色边框
    DIVIDER = '#EFEADD'            # 分隔线

    # ── 文字 ──
    TEXT = '#1A1A1F'               # 主文字
    TEXT_MUTED = '#52525B'         # 次要文字
    TEXT_SUBTLE = '#A1A1AA'        # 辅助文字

    # ── 朱砂重点 (Vermillion) ──
    ACCENT = '#BE3144'             # 主朱砂
    ACCENT_HOVER = '#9F2435'       # 悬停深朱砂
    ACCENT_PRESSED = '#7F1D2A'     # 按下暗朱砂
    ACCENT_SOFT = '#FCE4E6'        # 朱砂淡晕
    ACCENT_LINE = '#E8B4B9'        # 朱砂描边

    # ── 状态色（精炼版）──
    SUCCESS = '#15803D'            # 翠绿
    SUCCESS_SOFT = '#DCFCE7'
    WARNING = '#B45309'            # 琥珀
    WARNING_SOFT = '#FEF3C7'
    ERROR = '#B91C1C'              # 朱红
    ERROR_SOFT = '#FEE2E2'
    INFO = '#1D4ED8'               # 深青
    INFO_SOFT = '#DBEAFE'

    # ── 装饰渐变（顶部装饰条 / 处理中扫光）──
    GRADIENT_START = '#BE3144'     # 朱砂
    GRADIENT_MID = '#D97706'       # 琥珀
    GRADIENT_END = '#0EA5E9'       # 青

    # ── 日志色阶 ──
    LOG_INFO = '#1D4ED8'
    LOG_SUCCESS = '#15803D'
    LOG_WARNING = '#B45309'
    LOG_ERROR = '#B91C1C'
    LOG_TIMESTAMP = '#8B8B95'
    LOG_SEPARATOR = '#D1D5DB'


# 兼容旧引用（如有外部代码引用 MDColors）
MDColors = Palette
