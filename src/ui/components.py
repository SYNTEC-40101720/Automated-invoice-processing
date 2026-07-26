# ═══════════════════════════════════════════════════════════
# 墨韵 UI 自定义组件 (PySide6)
# ═══════════════════════════════════════════════════════════
import math
from datetime import datetime

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import (
    QBrush, QColor, QFont, QLinearGradient, QPainter, QPaintEvent,
    QPen, QTextCharFormat, QTextCursor,
)
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QVBoxLayout, QWidget,
)

from .colors import Palette
from ..config import (
    FONT_DISPLAY, FONT_MONO, FONT_UI,
    SIZE_H2, SIZE_LOGO, SIZE_SMALL, SIZE_STAT, SIZE_TINY,
)


# ─────────────────────────────────────────────────────
# 侧栏 LOGO —— 竖排 SYNTEC 字母，自绘
# ─────────────────────────────────────────────────────
class SidebarLogo(QWidget):
    """竖排 SYNTEC 品牌字"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(72)
        self.setMinimumHeight(360)

    def sizeHint(self) -> QSize:
        return QSize(72, 360)

    def paintEvent(self, _e: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)

        w = self.width()
        h = self.height()

        # 顶部装饰小方块（朱砂印章感）
        p.setBrush(QColor(Palette.ACCENT))
        p.setPen(Qt.NoPen)
        p.drawRect(QRectF((w - 14) / 2, 24, 14, 14))

        # 竖排字母
        font = QFont(FONT_DISPLAY, SIZE_LOGO, QFont.Bold)
        font.setLetterSpacing(QFont.AbsoluteSpacing, 4)
        p.setFont(font)

        letters = "SYNTEC"
        fm = p.fontMetrics()
        letter_h = fm.ascent()
        gap = 18
        total_h = len(letters) * (letter_h + gap) - gap
        y = (h - total_h) / 2 + fm.ascent()

        p.setPen(QColor(Palette.ON_INK))
        for ch in letters:
            p.drawText(QRectF(0, y - letter_h, w, letter_h + fm.descent()),
                       Qt.AlignHCenter | Qt.AlignTop, ch)
            y += letter_h + gap

        # 底部细线 + 版本
        p.setPen(QPen(QColor(Palette.INK_BORDER), 1))
        p.drawLine(int(w / 4), h - 56, int(3 * w / 4), h - 56)

        p.setFont(QFont(FONT_MONO, SIZE_TINY))
        p.setPen(QColor(Palette.ON_INK_SUBTLE))
        p.drawText(QRectF(0, h - 42, w, 20), Qt.AlignHCenter, "v6.2")

        p.end()


# ─────────────────────────────────────────────────────
# 统计卡片 —— 大号等宽数字 + 左侧色条
# ─────────────────────────────────────────────────────
class StatCard(QFrame):
    """单张统计卡片"""

    def __init__(self, label: str, color: str, parent=None):
        super().__init__(parent)
        self._color = color
        self._value = 0

        self.setObjectName("StatCard")
        self.setFrameShape(QFrame.NoFrame)
        self.setFixedHeight(96)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(2)

        self.value_label = QLabel("0")
        self.value_label.setObjectName("StatValue")
        f = QFont(FONT_MONO, SIZE_STAT, QFont.Bold)
        f.setStyleStrategy(QFont.PreferAntialias)
        self.value_label.setFont(f)
        self.value_label.setStyleSheet(f"color: {color};")
        lay.addWidget(self.value_label)

        self.name_label = QLabel(label)
        self.name_label.setObjectName("StatLabel")
        self.name_label.setFont(QFont(FONT_UI, SIZE_SMALL))
        self.name_label.setStyleSheet(f"color: {Palette.TEXT_MUTED};")
        lay.addWidget(self.name_label)

    def set_value(self, value: int) -> None:
        self._value = value
        self.value_label.setText(str(value))

    def paintEvent(self, _e: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        # 卡片背景
        p.setBrush(QColor(Palette.CARD))
        p.setPen(Qt.NoPen)
        p.drawRect(self.rect())
        # 左侧 3px 色条
        p.setBrush(QColor(self._color))
        p.drawRect(QRectF(0, 0, 3, self.height()))
        # 1px 暖色边框
        p.setPen(QPen(QColor(Palette.BORDER), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1))
        p.end()


# ─────────────────────────────────────────────────────
# 顶部装饰条 —— 朱砂→琥珀→青 渐变 + 处理中扫光
# ─────────────────────────────────────────────────────
class AccentBar(QWidget):
    """顶部装饰渐变条，处理中显示扫光动画"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(3)
        self._progress = 0.0
        self._scan_pos = 0.0
        self._scanning = False

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)

    def set_progress(self, ratio: float) -> None:
        self._progress = max(0.0, min(1.0, ratio))
        self.update()

    def start_scanning(self) -> None:
        self._scanning = True
        if not self._timer.isActive():
            self._timer.start(16)  # ~60fps

    def stop_scanning(self) -> None:
        self._scanning = False
        if self._timer.isActive():
            self._timer.stop()
        self.update()

    def _on_tick(self) -> None:
        self._scan_pos = (self._scan_pos + 0.012) % 1.4
        self.update()

    def paintEvent(self, _e: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w = self.width()
        h = self.height()

        # 底色：暖灰
        p.setBrush(QColor(Palette.BORDER))
        p.setPen(Qt.NoPen)
        p.drawRect(QRectF(0, 0, w, h))

        # 进度填充：渐变
        if self._progress > 0:
            grad = QLinearGradient(0, 0, w * self._progress, 0)
            grad.setColorAt(0.0, QColor(Palette.GRADIENT_START))
            grad.setColorAt(0.6, QColor(Palette.GRADIENT_MID))
            grad.setColorAt(1.0, QColor(Palette.GRADIENT_END))
            p.setBrush(QBrush(grad))
            p.drawRect(QRectF(0, 0, w * self._progress, h))

        # 扫光
        if self._scanning:
            scan_w = w * 0.18
            x = self._scan_pos * w - scan_w
            grad2 = QLinearGradient(x, 0, x + scan_w, 0)
            grad2.setColorAt(0.0, QColor(255, 255, 255, 0))
            grad2.setColorAt(0.5, QColor(255, 255, 255, 180))
            grad2.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.setBrush(QBrush(grad2))
            p.drawRect(QRectF(x, 0, scan_w, h))

        p.end()


# ─────────────────────────────────────────────────────
# 状态指示灯 —— 呼吸动画
# ─────────────────────────────────────────────────────
class StatusLight(QWidget):
    """带呼吸动画的状态指示灯"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(14, 14)
        self._color = QColor(Palette.SUCCESS)
        self._pulse = 0.0
        self._pulse_t = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_pulse)

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def start_pulsing(self) -> None:
        if not self._timer.isActive():
            self._timer.start(50)

    def stop_pulsing(self) -> None:
        if self._timer.isActive():
            self._timer.stop()
        self._pulse = 0.0
        self.update()

    def _on_pulse(self) -> None:
        self._pulse_t += 0.08
        self._pulse = (math.sin(self._pulse_t) + 1) / 2
        self.update()

    def paintEvent(self, _e: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = 4
        cx, cy = 7, 7

        # 外晕（呼吸）
        if self._pulse > 0:
            halo_r = r + 4 * self._pulse
            halo = QColor(self._color)
            halo.setAlpha(int(80 * (1 - self._pulse)))
            p.setBrush(halo)
            p.setPen(Qt.NoPen)
            p.drawEllipse(QRectF(cx - halo_r, cy - halo_r, halo_r * 2, halo_r * 2))

        # 实心圆
        p.setBrush(self._color)
        p.setPen(Qt.NoPen)
        p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
        p.end()


# ─────────────────────────────────────────────────────
# 日志视图 —— 终端风格等宽日志，带级别着色
# ─────────────────────────────────────────────────────
class LogView(QFrame):
    """终端风格日志视图"""

    LEVEL_COLORS = {
        'info': Palette.LOG_INFO,
        'success': Palette.LOG_SUCCESS,
        'warning': Palette.LOG_WARNING,
        'error': Palette.LOG_ERROR,
    }
    LEVEL_PREFIX = {
        'info': 'INFO',
        'success': ' OK ',
        'warning': 'WARN',
        'error': 'FAIL',
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("LogCard")
        self._count = 0

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # 头部
        header = QFrame()
        header.setObjectName("LogHeader")
        header.setFixedHeight(38)
        hlay = QHBoxLayout(header)
        hlay.setContentsMargins(16, 0, 16, 0)
        hlay.setSpacing(0)

        title = QLabel("处理日志")
        title.setFont(QFont(FONT_UI, SIZE_H2, QFont.Bold))
        title.setStyleSheet(f"color: {Palette.TEXT};")
        hlay.addWidget(title)
        hlay.addStretch()

        self.count_label = QLabel("0 条记录")
        self.count_label.setFont(QFont(FONT_MONO, SIZE_TINY))
        self.count_label.setStyleSheet(f"color: {Palette.TEXT_SUBTLE};")
        hlay.addWidget(self.count_label)

        lay.addWidget(header)

        # 日志文本框
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setObjectName("LogText")
        self.text.setFont(QFont(FONT_MONO, SIZE_TINY))
        self.text.setMaximumBlockCount(5000)  # 防止无限增长
        lay.addWidget(self.text)

        self._setup_formats()

    def _setup_formats(self) -> None:
        """配置 QTextCharFormat 用于不同级别"""
        self._fmt_timestamp = QTextCharFormat()
        self._fmt_timestamp.setForeground(QColor(Palette.LOG_TIMESTAMP))

        self._fmt_level = {
            level: QTextCharFormat() for level in self.LEVEL_COLORS
        }
        for level, fmt in self._fmt_level.items():
            fmt.setForeground(QColor(self.LEVEL_COLORS[level]))
            fmt.setFontWeight(QFont.Bold)

        self._fmt_separator = QTextCharFormat()
        self._fmt_separator.setForeground(QColor(Palette.LOG_SEPARATOR))

    def log(self, message: str, level: str = 'info') -> None:
        """追加一条日志"""
        self._count += 1
        ts = datetime.now().strftime('%H:%M:%S')
        prefix = self.LEVEL_PREFIX.get(level, 'INFO')

        cursor = self.text.textCursor()
        cursor.movePosition(QTextCursor.End)

        cursor.insertText(f"[{ts}] ", self._fmt_timestamp)
        cursor.insertText(f"{prefix} ", self._fmt_level.get(level, self._fmt_timestamp))
        cursor.insertText(f"{message}\n")

        self.text.setTextCursor(cursor)
        self.text.ensureCursorVisible()
        self.count_label.setText(f"{self._count} 条记录")

    def separator(self) -> None:
        """插入分隔线"""
        cursor = self.text.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText("─" * 72 + "\n", self._fmt_separator)
        self.text.setTextCursor(cursor)
        self.text.ensureCursorVisible()

    def clear(self) -> None:
        """清空日志"""
        self.text.clear()
        self._count = 0
        self.count_label.setText("0 条记录")

    def export_to_file(self, path: str) -> None:
        """将当前日志导出到文件（纯文本，含时间戳）"""
        with open(path, 'w', encoding='utf-8') as f:
            f.write(self.text.toPlainText())
