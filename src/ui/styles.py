# ═══════════════════════════════════════════════════════════
# 墨韵 (Atelier) 共享样式表
# 主窗口与设置对话框共用同一套 QSS，保证风格统一。
# 为避免与 app.py 循环依赖，本模块只依赖 colors / config。
# ═══════════════════════════════════════════════════════════
from .colors import Palette
from ..config import (
    FONT_MONO, FONT_UI, SIZE_BODY, SIZE_SMALL, SIZE_TINY,
)

QSS = f"""
* {{
    font-family: "{FONT_UI}";
    color: {Palette.TEXT};
}}

QMainWindow, QWidget#Central {{
    background: {Palette.PAPER};
}}

/* ── 设置对话框：暖纸画布，与主页面一致 ── */
QDialog {{
    background: {Palette.PAPER};
}}

/* ── 设置页头部 / 分组 ── */
QFrame#SettingsHeader {{
    background: {Palette.INK};
    border: 1px solid {Palette.INK_BORDER};
}}
QLabel#SettingsEyebrow {{
    color: {Palette.ACCENT_LINE};
    font-family: "{FONT_MONO}";
    font-size: {SIZE_TINY}px;
    font-weight: 600;
    letter-spacing: 1px;
}}
QLabel#SettingsTitle {{
    color: {Palette.ON_INK};
    font-size: 24px;
    font-weight: 700;
}}
QLabel#SettingsSubtitle {{
    color: {Palette.ON_INK_MUTED};
    font-size: {SIZE_SMALL}px;
}}
QLabel#SettingsBadge {{
    color: {Palette.ON_INK};
    background: {Palette.INK_RAISED};
    border: 1px solid {Palette.INK_BORDER};
    padding: 5px 9px;
    font-size: {SIZE_TINY}px;
}}
QFrame#SettingsSectionHeader {{
    background: transparent;
}}
QFrame#SettingsSectionMarker {{
    background: {Palette.ACCENT};
}}
QLabel#SettingsSectionTitle {{
    color: {Palette.TEXT};
    font-size: 17px;
    font-weight: 700;
}}
QCheckBox#FeatureToggle {{
    background: {Palette.ACCENT_SOFT};
    border-left: 3px solid {Palette.ACCENT};
    padding: 10px 12px;
    font-weight: 600;
}}
QScrollArea {{
    background: transparent;
    border: none;
}}
QScrollArea > QWidget > QWidget {{
    background: transparent;
}}
QFormLayout QLabel {{
    color: {Palette.TEXT_MUTED};
    font-size: {SIZE_SMALL}px;
}}

/* ── 侧栏 ── */
QFrame#Sidebar {{
    background: {Palette.INK};
    border: none;
    border-right: 1px solid {Palette.INK_BORDER};
}}

/* ── 卡片 ── */
QFrame#Card {{
    background: {Palette.CARD};
    border: 1px solid {Palette.BORDER};
}}

QFrame#LogCard {{
    background: {Palette.CARD};
    border: 1px solid {Palette.BORDER};
}}

QFrame#LogHeader {{
    background: {Palette.CARD};
    border: none;
    border-bottom: 1px solid {Palette.DIVIDER};
}}

/* ── 路径 / 文本输入框 ── */
QLineEdit#PathEntry {{
    background: {Palette.PAPER};
    border: 1px solid {Palette.BORDER};
    border-radius: 0;
    padding: 11px 14px;
    min-height: 20px;
    color: {Palette.TEXT};
    font-size: {SIZE_BODY}px;
    selection-background-color: {Palette.ACCENT_SOFT};
}}
QLineEdit#PathEntry:focus {{
    border: 1px solid {Palette.ACCENT};
    background: {Palette.CARD};
}}
QLineEdit#PathEntry:disabled {{
    background: {Palette.DIVIDER};
    color: {Palette.TEXT_SUBTLE};
}}
QLineEdit:read-only {{
    color: {Palette.TEXT_MUTED};
}}

/* ── 数字输入框 (SpinBox) ── */
QSpinBox {{
    background: {Palette.PAPER};
    border: 1px solid {Palette.BORDER};
    border-radius: 0;
    padding: 9px 10px;
    min-height: 22px;
    color: {Palette.TEXT};
    font-size: {SIZE_BODY}px;
    selection-background-color: {Palette.ACCENT_SOFT};
}}
QSpinBox:focus {{
    border: 1px solid {Palette.ACCENT};
    background: {Palette.CARD};
}}
QSpinBox::up-button, QSpinBox::down-button {{
    background: {Palette.CARD};
    border: none;
    width: 22px;
    subcontrol-origin: margin;
}}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
    background: {Palette.ACCENT_SOFT};
}}
QSpinBox QLineEdit {{
    background: transparent;
    border: none;
    padding: 0;
}}

/* ── 复选框 ── */
QCheckBox {{
    color: {Palette.TEXT};
    font-size: {SIZE_BODY}px;
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border: 1px solid {Palette.BORDER};
    background: {Palette.CARD};
}}
QCheckBox::indicator:unchecked:hover {{
    border: 1px solid {Palette.ACCENT};
}}
QCheckBox::indicator:checked {{
    border: 1px solid {Palette.ACCENT};
    background: {Palette.ACCENT_SOFT};
}}

/* ── 日志文本框 ── */
QPlainTextEdit#LogText {{
    background: {Palette.PAPER};
    border: none;
    border-top: 1px solid {Palette.DIVIDER};
    color: {Palette.TEXT};
    padding: 12px 16px;
    selection-background-color: {Palette.ACCENT_SOFT};
}}

/* ── 主按钮 (朱砂实心) ── */
QPushButton#PrimaryBtn {{
    background: {Palette.ACCENT};
    color: {Palette.ON_INK};
    border: none;
    padding: 10px 28px;
    font-size: {SIZE_BODY}px;
    font-weight: 600;
    letter-spacing: 1px;
}}
QPushButton#PrimaryBtn:hover {{
    background: {Palette.ACCENT_HOVER};
}}
QPushButton#PrimaryBtn:pressed {{
    background: {Palette.ACCENT_PRESSED};
}}
QPushButton#PrimaryBtn:disabled {{
    background: {Palette.BORDER};
    color: {Palette.TEXT_SUBTLE};
}}

/* ── 次要按钮 (描边) ── */
QPushButton#OutlineBtn {{
    background: {Palette.CARD};
    color: {Palette.ACCENT};
    border: 1px solid {Palette.ACCENT};
    padding: 9px 24px;
    font-size: {SIZE_BODY}px;
    font-weight: 600;
    letter-spacing: 1px;
}}
QPushButton#OutlineBtn:hover {{
    background: {Palette.ACCENT_SOFT};
}}
QPushButton#OutlineBtn:pressed {{
    background: {Palette.ACCENT_LINE};
}}
QPushButton#OutlineBtn:disabled {{
    color: {Palette.TEXT_SUBTLE};
    border-color: {Palette.BORDER};
    background: {Palette.PAPER};
}}

/* ── 危险按钮 ── */
QPushButton#DangerBtn {{
    background: {Palette.CARD};
    color: {Palette.ERROR};
    border: 1px solid {Palette.ERROR};
    padding: 9px 24px;
    font-size: {SIZE_BODY}px;
    font-weight: 600;
    letter-spacing: 1px;
}}
QPushButton#DangerBtn:hover {{
    background: {Palette.ERROR_SOFT};
}}
QPushButton#DangerBtn:disabled {{
    color: {Palette.TEXT_SUBTLE};
    border-color: {Palette.BORDER};
    background: {Palette.PAPER};
}}

/* ── 文字按钮 ── */
QPushButton#TextBtn {{
    background: transparent;
    color: {Palette.TEXT_MUTED};
    border: none;
    padding: 6px 12px;
    font-size: {SIZE_SMALL}px;
}}
QPushButton#TextBtn:hover {{
    color: {Palette.ACCENT};
}}

/* ── 状态栏 ── */
QFrame#StatusBar {{
    background: {Palette.INK};
    border: none;
    border-top: 1px solid {Palette.INK_BORDER};
}}
QLabel#StatusText {{
    color: {Palette.ON_INK_MUTED};
    font-size: {SIZE_SMALL}px;
}}
QLabel#StatusMeta {{
    color: {Palette.ON_INK_SUBTLE};
    font-size: {SIZE_TINY}px;
    font-family: "{FONT_MONO}";
}}

/* ── 滚动条 ── */
QScrollBar:vertical {{
    background: {Palette.PAPER};
    width: 8px;
    border: none;
}}
QScrollBar::handle:vertical {{
    background: {Palette.BORDER};
    border-radius: 0;
    min-height: 32px;
}}
QScrollBar::handle:vertical:hover {{
    background: {Palette.TEXT_SUBTLE};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: none;
}}
"""
