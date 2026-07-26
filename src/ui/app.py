# ═══════════════════════════════════════════════════════════
# SYNTEC 电子票据处理系统 - 主窗口 (PySide6)
# 美学方向：墨韵 Atelier - 编辑级精度仪表盘
# ═══════════════════════════════════════════════════════════
import os
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from .colors import Palette
from .components import AccentBar, LogView, SidebarLogo, StatCard, StatusLight
from .settings_dialog import SettingsDialog
from ..core.processor import InvoiceProcessor
from .. import config as _cfg
from ..config import (
    FONT_MONO, FONT_UI, MAX_WORKERS,
    SIZE_DISPLAY, SIZE_H2, SIZE_BODY, SIZE_SMALL, SIZE_TINY,
    WINDOW_GEOMETRY, WINDOW_MIN_SIZE,
)


# ─────────────────────────────────────────────────────
# QSS 样式表
# ─────────────────────────────────────────────────────
QSS = f"""
* {{
    font-family: "{FONT_UI}";
    color: {Palette.TEXT};
}}

QMainWindow, QWidget#Central {{
    background: {Palette.PAPER};
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

/* ── 路径输入框 ── */
QLineEdit#PathEntry {{
    background: {Palette.PAPER};
    border: 1px solid {Palette.BORDER};
    border-radius: 0;
    padding: 10px 14px;
    color: {Palette.TEXT};
    font-size: {SIZE_BODY}px;
    selection-background-color: {Palette.ACCENT_SOFT};
}}
QLineEdit#PathEntry:focus {{
    border: 1px solid {Palette.ACCENT};
    background: {Palette.CARD};
}}
QLineEdit:read-only {{
    color: {Palette.TEXT_MUTED};
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


# ═══════════════════════════════════════════════════════════
# 主窗口
# ═══════════════════════════════════════════════════════════
class InvoiceApp(QMainWindow):
    """SYNTEC 电子票据处理系统 - 主窗口"""

    # ── 跨线程信号（worker 线程 → 主线程 UI 更新）──
    sig_log = Signal(str, str)               # message, level
    sig_progress = Signal(float, str)        # ratio 0~1, percent_text
    sig_stat = Signal(str, int)              # key, value
    sig_status = Signal(str, str)            # text, state
    sig_light = Signal(str, bool)            # color, pulsing
    sig_finished = Signal()
    sig_scan = Signal(bool)                  # scanning on/off
    sig_separator = Signal()                 # 日志分隔线

    def __init__(self):
        super().__init__()
        self.setWindowTitle("SYNTEC · 电子票据处理系统")
        self.resize(*WINDOW_GEOMETRY)
        self.setMinimumSize(*WINDOW_MIN_SIZE)
        self.setAcceptDrops(True)  # 启用拖拽

        # 处理器
        self.processor = InvoiceProcessor(
            log_callback=lambda msg, level: self.sig_log.emit(msg, level)
        )
        self.output_dir: str | None = None
        self.source_dir = os.getcwd()
        self.is_processing = False

        # 构建界面
        self._build_ui()
        self._connect_signals()
        self._start_clock()

        # 初始状态
        self._set_status("就绪 — 请选择文件目录后开始处理", "ready")
        self.sig_light.emit(Palette.SUCCESS, False)

    # ───────────────────────────────────────────────────
    # UI 构建
    # ───────────────────────────────────────────────────
    def _build_ui(self):
        central = QWidget()
        central.setObjectName("Central")
        self.setCentralWidget(central)

        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 侧栏 + 主区
        root.addWidget(self._build_sidebar())
        root.addWidget(self._build_main_area(), stretch=1)

        self.setStyleSheet(QSS)

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(72)

        lay = QVBoxLayout(sidebar)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # 顶部留白
        lay.addSpacing(24)
        # LOGO 居中
        lay.addWidget(SidebarLogo(), alignment=Qt.AlignHCenter)
        lay.addStretch()

        # 底部装饰：线程数指示
        thread_label = QLabel(f"{MAX_WORKERS}\n线程")
        thread_label.setAlignment(Qt.AlignCenter)
        thread_label.setStyleSheet(
            f"color: {Palette.ON_INK_SUBTLE}; font-size: {SIZE_TINY}px;"
            f"font-family: '{FONT_MONO}';"
        )
        thread_label.setWordWrap(True)
        lay.addWidget(thread_label)
        lay.addSpacing(20)

        return sidebar

    def _build_main_area(self) -> QWidget:
        area = QWidget()
        lay = QVBoxLayout(area)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # 顶部装饰条
        self.accent_bar = AccentBar()
        lay.addWidget(self.accent_bar)

        # 内容容器
        content = QWidget()
        content_lay = QVBoxLayout(content)
        content_lay.setContentsMargins(32, 28, 32, 16)
        content_lay.setSpacing(14)

        # 头部
        content_lay.addLayout(self._build_header())

        # 源文件卡片
        content_lay.addWidget(self._build_source_card())

        # 统计面板
        content_lay.addLayout(self._build_stats_panel())

        # 进度卡片
        content_lay.addWidget(self._build_progress_card())

        # 日志卡片（先创建，按钮区会引用它）
        self.log_view = LogView()

        # 操作按钮区
        content_lay.addLayout(self._build_action_bar())

        # 日志卡片（占满剩余空间）
        content_lay.addWidget(self.log_view, stretch=1)

        lay.addWidget(content, stretch=1)

        # 底部状态栏
        lay.addWidget(self._build_status_bar())

        return area

    def _build_header(self) -> QHBoxLayout:
        h = QHBoxLayout()
        h.setSpacing(0)

        title_wrap = QVBoxLayout()
        title_wrap.setSpacing(2)

        brand = QLabel("电子票据处理系统")
        brand.setFont(QFont(FONT_UI, SIZE_DISPLAY, QFont.Bold))
        brand.setStyleSheet(f"color: {Palette.TEXT}; letter-spacing: 2px;")
        title_wrap.addWidget(brand)

        subtitle = QLabel("INVOICE  PROCESSING  SYSTEM")
        sub_font = QFont(FONT_MONO, SIZE_TINY)
        sub_font.setLetterSpacing(QFont.AbsoluteSpacing, 3)
        subtitle.setFont(sub_font)
        subtitle.setStyleSheet(f"color: {Palette.TEXT_SUBTLE};")
        title_wrap.addWidget(subtitle)

        h.addLayout(title_wrap)
        h.addStretch()

        # 右上角时间
        self.clock_label = QLabel()
        self.clock_label.setAlignment(Qt.AlignRight | Qt.AlignBottom)
        self.clock_label.setFont(QFont(FONT_MONO, SIZE_H2))
        self.clock_label.setStyleSheet(f"color: {Palette.TEXT_MUTED};")
        h.addWidget(self.clock_label)

        return h

    def _build_source_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")

        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)

        # 头部行
        header = QHBoxLayout()
        header.setSpacing(0)

        title = QLabel("选择文件目录")
        title.setFont(QFont(FONT_UI, SIZE_H2, QFont.Bold))
        title.setStyleSheet(f"color: {Palette.TEXT};")
        header.addWidget(title)
        header.addStretch()

        self.dir_hint = QLabel("请选择包含 PDF 发票的文件夹")
        self.dir_hint.setFont(QFont(FONT_UI, SIZE_SMALL))
        self.dir_hint.setStyleSheet(f"color: {Palette.TEXT_MUTED};")
        header.addWidget(self.dir_hint)

        lay.addLayout(header)

        # 路径输入 + 浏览按钮
        row = QHBoxLayout()
        row.setSpacing(8)

        self.path_entry = QLineEdit("未选择目录")
        self.path_entry.setObjectName("PathEntry")
        self.path_entry.setReadOnly(True)
        self.path_entry.setFont(QFont(FONT_UI, SIZE_BODY))
        row.addWidget(self.path_entry, stretch=1)

        browse_btn = QPushButton("浏览…")
        browse_btn.setObjectName("OutlineBtn")
        browse_btn.setCursor(Qt.PointingHandCursor)
        browse_btn.clicked.connect(self._select_directory)
        row.addWidget(browse_btn)

        lay.addLayout(row)

        return card

    def _build_stats_panel(self) -> QHBoxLayout:
        h = QHBoxLayout()
        h.setSpacing(12)

        self.stat_cards = {
            'total': StatCard("文件总数", Palette.INFO),
            'success': StatCard("处理成功", Palette.SUCCESS),
            'failure': StatCard("处理失败", Palette.ERROR),
            'tax_issues': StatCard("税号异常", Palette.WARNING),
        }
        for card in self.stat_cards.values():
            h.addWidget(card, stretch=1)

        return h

    def _build_progress_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")

        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 14, 20, 14)
        lay.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("处理进度")
        title.setFont(QFont(FONT_UI, SIZE_H2, QFont.Bold))
        title.setStyleSheet(f"color: {Palette.TEXT};")
        header.addWidget(title)
        header.addStretch()

        self.progress_percent = QLabel("0%")
        self.progress_percent.setFont(QFont(FONT_MONO, SIZE_H2, QFont.Bold))
        self.progress_percent.setStyleSheet(f"color: {Palette.ACCENT};")
        header.addWidget(self.progress_percent)

        lay.addLayout(header)

        # 复用 AccentBar 作为进度条
        self.progress_bar = AccentBar()
        self.progress_bar.setFixedHeight(4)
        lay.addWidget(self.progress_bar)

        return card

    def _build_action_bar(self) -> QHBoxLayout:
        h = QHBoxLayout()
        h.setSpacing(10)

        self.process_btn = QPushButton("开始处理")
        self.process_btn.setObjectName("PrimaryBtn")
        self.process_btn.setCursor(Qt.PointingHandCursor)
        self.process_btn.clicked.connect(self._start_processing)
        h.addWidget(self.process_btn)

        self.stop_btn = QPushButton("停止")
        self.stop_btn.setObjectName("DangerBtn")
        self.stop_btn.setCursor(Qt.PointingHandCursor)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_processing)
        h.addWidget(self.stop_btn)

        self.open_btn = QPushButton("打开输出文件夹")
        self.open_btn.setObjectName("OutlineBtn")
        self.open_btn.setCursor(Qt.PointingHandCursor)
        self.open_btn.clicked.connect(self._open_output_dir)
        h.addWidget(self.open_btn)

        h.addStretch()

        # 设置按钮
        settings_btn = QPushButton("设置")
        settings_btn.setObjectName("TextBtn")
        settings_btn.setCursor(Qt.PointingHandCursor)
        settings_btn.clicked.connect(self._show_settings)
        h.addWidget(settings_btn)

        # 导出日志按钮
        export_btn = QPushButton("导出日志")
        export_btn.setObjectName("TextBtn")
        export_btn.setCursor(Qt.PointingHandCursor)
        export_btn.clicked.connect(self._export_log)
        h.addWidget(export_btn)

        # 清空日志按钮
        clear_btn = QPushButton("清空日志")
        clear_btn.setObjectName("TextBtn")
        clear_btn.setCursor(Qt.PointingHandCursor)
        clear_btn.clicked.connect(self.log_view.clear)
        h.addWidget(clear_btn)

        return h

    def _build_status_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("StatusBar")
        bar.setFixedHeight(34)

        lay = QHBoxLayout(bar)
        lay.setContentsMargins(20, 0, 20, 0)
        lay.setSpacing(8)

        self.status_light = StatusLight()
        lay.addWidget(self.status_light)

        self.status_label = QLabel("就绪")
        self.status_label.setObjectName("StatusText")
        lay.addWidget(self.status_label)

        lay.addStretch()

        meta = QLabel(f"{MAX_WORKERS} threads · UTF-8")
        meta.setObjectName("StatusMeta")
        lay.addWidget(meta)

        return bar

    # ───────────────────────────────────────────────────
    # 信号连接
    # ───────────────────────────────────────────────────
    def _connect_signals(self):
        self.sig_log.connect(self._on_log)
        self.sig_progress.connect(self._on_progress)
        self.sig_stat.connect(self._on_stat)
        self.sig_status.connect(self._on_status)
        self.sig_light.connect(self._on_light)
        self.sig_finished.connect(self._on_finished)
        self.sig_scan.connect(self._on_scan)
        self.sig_separator.connect(self.log_view.separator)

    # ───────────────────────────────────────────────────
    # 时钟
    # ───────────────────────────────────────────────────
    def _start_clock(self):
        self._tick_clock()
        timer = QTimer(self)
        timer.timeout.connect(self._tick_clock)
        timer.start(30000)

    def _tick_clock(self):
        self.clock_label.setText(datetime.now().strftime('%Y-%m-%d  %H:%M'))

    # ───────────────────────────────────────────────────
    # 槽函数（主线程执行）
    # ───────────────────────────────────────────────────
    def _on_log(self, msg: str, level: str):
        self.log_view.log(msg, level)

    def _on_progress(self, ratio: float, percent_text: str):
        self.progress_bar.set_progress(ratio)
        self.progress_percent.setText(percent_text)

    def _on_stat(self, key: str, value: int):
        if key in self.stat_cards:
            self.stat_cards[key].set_value(value)

    def _on_status(self, text: str, state: str):
        color_map = {
            'ready': Palette.ON_INK_MUTED,
            'processing': Palette.ACCENT_LINE,
            'success': Palette.SUCCESS,
            'warning': Palette.WARNING,
            'error': Palette.ERROR,
        }
        color = color_map.get(state, Palette.ON_INK_MUTED)
        self.status_label.setText(text)
        self.status_label.setStyleSheet(
            f"color: {color}; font-size: {SIZE_SMALL}px;"
        )

    def _on_light(self, color: str, pulsing: bool):
        self.status_light.set_color(color)
        if pulsing:
            self.status_light.start_pulsing()
        else:
            self.status_light.stop_pulsing()

    def _on_scan(self, scanning: bool):
        if scanning:
            self.accent_bar.start_scanning()
        else:
            self.accent_bar.stop_scanning()

    def _on_finished(self):
        self.is_processing = False
        self.process_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.sig_scan.emit(False)

    # ───────────────────────────────────────────────────
    # 交互
    # ───────────────────────────────────────────────────
    def _select_directory(self):
        dir_path = QFileDialog.getExistingDirectory(
            self, "选择包含 PDF 发票的文件夹", self.source_dir
        )
        if not dir_path:
            return
        self._set_source_directory(dir_path)

    def _set_source_directory(self, dir_path: str):
        """设置源目录并更新 UI（拖拽和浏览共用）"""
        if not os.path.isdir(dir_path):
            return
        self.source_dir = dir_path
        os.chdir(dir_path)

        try:
            pdf_count = sum(1 for f in os.listdir(dir_path) if f.lower().endswith('.pdf'))
        except OSError:
            pdf_count = 0

        self.path_entry.setText(dir_path)
        self.dir_hint.setText(f"发现 {pdf_count} 个 PDF 文件")
        self.dir_hint.setStyleSheet(f"color: {Palette.ACCENT};")

        self._on_stat('total', pdf_count)
        self.sig_log.emit(f"已选择目录: {dir_path}（包含 {pdf_count} 个 PDF 文件）", "info")
        self._set_status(f"已就绪 — {pdf_count} 个文件待处理", "ready")

    # ───────────────────────────────────────────────────
    # 拖拽
    # ───────────────────────────────────────────────────
    def dragEnterEvent(self, event: QDragEnterEvent):
        """接受文件夹或 PDF 文件的拖入"""
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if any(url.isLocalFile() for url in urls):
                event.acceptProposedAction()
                return
        event.ignore()

    def dropEvent(self, event: QDropEvent):
        """处理拖入：文件夹直接作为源目录，PDF 文件取所在目录"""
        urls = event.mimeData().urls()
        if not urls:
            event.ignore()
            return
        for url in urls:
            local_path = url.toLocalFile()
            if not local_path:
                continue
            if os.path.isdir(local_path):
                self._set_source_directory(local_path)
                event.acceptProposedAction()
                return
            if local_path.lower().endswith('.pdf'):
                parent = os.path.dirname(local_path)
                self._set_source_directory(parent)
                event.acceptProposedAction()
                return
        event.ignore()

    def _set_status(self, text: str, state: str = "ready"):
        self.sig_status.emit(text, state)

    def _start_processing(self):
        if self.is_processing:
            return
        self.is_processing = True
        self.process_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self._on_progress(0.0, "0%")
        self.sig_light.emit(Palette.WARNING, True)
        self.sig_scan.emit(True)
        self._set_status("正在处理中…", "processing")

        # 重置统计
        for k in ('success', 'failure', 'tax_issues'):
            self._on_stat(k, 0)

        threading.Thread(target=self._process_files, daemon=True).start()

    def _stop_processing(self):
        self.is_processing = False
        self.sig_log.emit("用户请求停止处理", "warning")
        self._set_status("正在停止…", "processing")

    def _process_files(self):
        """worker 线程：处理 PDF 文件"""
        try:
            pdf_files = [f for f in os.listdir(self.source_dir) if f.lower().endswith('.pdf')]
            total = len(pdf_files)

            if total == 0:
                self.sig_log.emit("未找到 PDF 文件，请选择包含 PDF 文件的目录", "warning")
                self._set_status("未找到 PDF 文件", "error")
                self.sig_light.emit(Palette.ERROR, False)
                self.sig_finished.emit()
                return

            self.output_dir = self.processor.create_output_directory(self.source_dir)
            # 清空去重记录，避免跨次处理污染
            self.processor.reset_dedup()
            # 运行时读取线程数（用户可能在设置中修改过）
            current_workers = _cfg.MAX_WORKERS
            self.sig_log.emit(f"发现 {total} 个待处理文件", "info")
            self._on_log_separator()
            self.sig_log.emit(f"使用 {current_workers} 线程并发处理", "info")

            success_count = 0
            failure_count = 0
            start_time = datetime.now()

            with ThreadPoolExecutor(max_workers=current_workers) as executor:
                future_to_file = {
                    executor.submit(self._process_single_file, f): f for f in pdf_files
                }

                # 进度节流
                progress_step = max(1, total // 100)

                for i, future in enumerate(as_completed(future_to_file), 1):
                    if not self.is_processing:
                        # 用户请求停止：取消所有未开始的任务
                        for f in future_to_file:
                            f.cancel()
                        self.sig_log.emit("处理已中止（已取消未开始的任务）", "warning")
                        break

                    _, _, log_type, message = future.result()
                    self.sig_log.emit(message, log_type)

                    if log_type == 'success':
                        success_count += 1
                    else:
                        failure_count += 1

                    self.sig_stat.emit('success', success_count)
                    self.sig_stat.emit('failure', failure_count)

                    if i % progress_step == 0 or i == total:
                        # PDF 处理阶段映射到 0% → 70%（按实测占比 67% 估算）
                        ratio = (i / total) * 0.70
                        self.sig_progress.emit(ratio, f"{int(ratio * 100)}%")

            if not self.is_processing:
                self.sig_log.emit("处理已中止，部分文件可能未完成", "warning")
                self._set_status("处理已中止", "warning")
                self.sig_light.emit(Palette.WARNING, False)
                self.sig_finished.emit()
                return

            self._on_log_separator()
            self.sig_log.emit(f"统计: 总 {total} | 成功 {success_count} | 失败 {failure_count}", "info")

            # 后处理（通过回调按子步骤精确报告进度，映射到 70% → 100%）
            self._set_status("执行后处理…", "processing")
            self.sig_log.emit("执行后处理…", "info")

            def _on_post_progress(ratio: float):
                # 后处理内部进度 0.0~1.0 → 整体进度 0.70~1.00
                overall = 0.70 + 0.30 * ratio
                self.sig_progress.emit(overall, f"{int(overall * 100)}%")

            result = self.processor.post_process(
                self.output_dir, progress_callback=_on_post_progress
            )
            tax_issues = result['tax_issues']
            merged = result['merged']

            self.sig_log.emit(f"金额映射: {len(result['amount_map'])} 条", "info")
            self.sig_log.emit("待搜索文件替换完成", "success")

            for issue in tax_issues:
                self.sig_log.emit(issue, "warning")

            self.sig_stat.emit('tax_issues', len(tax_issues))

            if merged:
                self.sig_log.emit("PDF 合并完成", "success")
            else:
                self.sig_log.emit("PDF 合并失败", "error")

            self.processor.clear_cache()

            self.sig_progress.emit(1.0, "100%")
            self._on_log_separator()
            elapsed = (datetime.now() - start_time).total_seconds()
            self.sig_log.emit(
                f"总耗时: {elapsed:.2f} 秒（{current_workers} 线程，{total} 文件）",
                "info",
            )
            self.sig_log.emit("所有处理已完成！", "success")

            final_state = "success" if failure_count == 0 and not tax_issues else "warning"
            self._set_status(
                f"处理完成 — 成功 {success_count}/{total}"
                + (f"，{len(tax_issues)} 个税号异常" if tax_issues else ""),
                final_state,
            )
            self.sig_light.emit(
                Palette.SUCCESS if failure_count == 0 else Palette.WARNING, False
            )

        except Exception as e:
            self.sig_log.emit(f"处理出错: {e}", "error")
            self._set_status(f"处理出错: {e}", "error")
            self.sig_light.emit(Palette.ERROR, False)
        finally:
            self.sig_finished.emit()

    def _on_log_separator(self):
        """从 worker 线程通过信号插入分隔线（线程安全）"""
        self.sig_separator.emit()

    # PDF 解析失败原因的中文描述
    _ERROR_LABELS = {
        'encrypted': 'PDF 已加密',
        'corrupted': 'PDF 文件损坏',
        'empty': 'PDF 无文本内容（可能是扫描件）',
        'unknown': 'PDF 解析失败',
    }

    def _process_single_file(self, filename: str):
        """处理单个 PDF（在 worker 线程内执行）"""
        # 用户请求停止时，未开始的任务提前返回
        if not self.is_processing:
            return filename, None, 'warning', f'已取消: {filename}'
        file_path = os.path.join(self.source_dir, filename)
        text, error_type = self.processor.extract_pdf_text_with_error(file_path)

        if not text:
            reason = self._ERROR_LABELS.get(error_type or 'unknown', 'PDF 解析失败')
            dest = self._move_to_manual_review(file_path, filename)
            return filename, dest, 'error', f'{reason}，已归集到需人工处理: {filename}'

        # 内容哈希去重：相同内容不同文件名的源文件只处理一次
        if self.processor._check_content_duplicate(text, file_path):
            return filename, None, 'warning', f'内容重复已跳过（源文件保留）: {filename}'

        processor_func = self.processor.determine_processor_type(text)

        if processor_func:
            result = processor_func(file_path, self.output_dir)
            if result:
                return filename, result, 'success', f'成功: {os.path.basename(result)}'
            dest = self._move_to_manual_review(file_path, filename)
            return filename, dest, 'warning', f'字段提取失败，已归集到需人工处理: {filename}'

        dest = self._move_to_manual_review(file_path, filename)
        return filename, dest, 'warning', f'类型未识别，已归集到需人工处理: {filename}'

    def _move_to_manual_review(self, file_path: str, filename: str) -> str:
        """将失败文件复制到「需人工处理」子目录"""
        manual_dir = os.path.join(self.output_dir, '需人工处理')
        os.makedirs(manual_dir, exist_ok=True)
        dest_path = os.path.join(manual_dir, filename)
        counter = 1
        while os.path.exists(dest_path):
            name, ext = os.path.splitext(filename)
            dest_path = os.path.join(manual_dir, f'{name}_{counter}{ext}')
            counter += 1
        shutil.copy2(file_path, dest_path)
        return dest_path

    def _open_output_dir(self):
        if not self.output_dir:
            QMessageBox.information(self, "提示", "尚未生成输出目录，请先处理文件")
            return
        if not os.path.exists(self.output_dir):
            QMessageBox.information(self, "提示", "输出目录不存在")
            return
        try:
            os.startfile(self.output_dir)
        except Exception as e:
            QMessageBox.critical(
                self, "错误", f"无法打开目录: {e}\n\n路径: {self.output_dir}"
            )

    def _show_settings(self):
        """打开设置对话框，保存后刷新 UI 显示的线程数"""
        dialog = SettingsDialog(self)
        if dialog.exec() == SettingsDialog.Accepted:
            # 配置已保存并 reload，更新 UI 上显示的线程数
            self.sig_log.emit(
                f"配置已更新：税号 {_cfg.TARGET_TAX_ID}，线程数 {_cfg.MAX_WORKERS}",
                "info",
            )

    def _export_log(self):
        """导出当前日志到文件"""
        default_name = f"发票处理日志_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        default_dir = self.output_dir if self.output_dir else self.source_dir
        default_path = os.path.join(default_dir, default_name)
        path, _ = QFileDialog.getSaveFileName(
            self, "导出日志", default_path, "文本文件 (*.txt);;所有文件 (*.*)"
        )
        if not path:
            return
        try:
            self.log_view.export_to_file(path)
            self.sig_log.emit(f"日志已导出: {path}", "success")
        except OSError as e:
            QMessageBox.critical(self, "导出失败", f"无法写入文件: {e}")

    # ───────────────────────────────────────────────────
    # 关闭事件
    # ───────────────────────────────────────────────────
    def closeEvent(self, event):
        if self.is_processing:
            reply = QMessageBox.question(
                self, "确认退出",
                "正在处理文件，确定要退出吗？\n退出将中止当前任务。",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.No:
                event.ignore()
                return
            self.is_processing = False
        event.accept()
