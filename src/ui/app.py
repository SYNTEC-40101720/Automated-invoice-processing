# ═══════════════════════════════════════════════════════════
# SYNTEC 电子票据处理系统 - 主窗口 (PySide6)
# 美学方向：墨韵 Atelier - 编辑级精度仪表盘
# ═══════════════════════════════════════════════════════════
import os
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from PySide6.QtCore import Qt, Signal, QTimer, QFileSystemWatcher
from PySide6.QtGui import QFont, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from .colors import Palette
from .components import (
    AccentBar, LogView, SidebarLogo, StatCard, StatusLight, ToggleSwitch,
)
from .settings_dialog import SettingsDialog
from ..core.processor import InvoiceProcessor
from ..core.email_pull import pull_invoices
from ..core.ai_audit import audit_records, write_audit_report
from ..core.excel_summary import _parse_invoice
from ..core.local_audit import run_local_audit
from ..config_manager import (
    get_ai_api_base, get_ai_api_key, get_ai_enabled, get_ai_model,
    get_email_auth_code, get_email_days_back, get_email_enabled,
    get_email_poll_minutes, get_email_username, get_inbox_dir,
    set_ai_config,
)
from .. import config as _cfg
from ..config import (
    FONT_MONO, FONT_UI, MAX_WORKERS,
    SIZE_DISPLAY, SIZE_H2, SIZE_BODY, SIZE_SMALL, SIZE_TINY,
    WINDOW_GEOMETRY, WINDOW_MIN_SIZE,
)


# ─────────────────────────────────────────────────────
# QSS 样式表（与主窗口、设置对话框共用，定义在 styles.py）
# ─────────────────────────────────────────────────────
from .styles import QSS


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
    sig_pull_done = Signal(object)           # 邮箱拉取结果（worker → 主线程）

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

        # 邮箱发票收件箱：目录监听 + 可选定时轮询
        self.inbox_dir = get_inbox_dir()
        try:
            os.makedirs(self.inbox_dir, exist_ok=True)
        except OSError:
            pass
        self.auto_inbox = False  # 自动模式标记（处理完成后归档源文件）
        self._inbox_known: set | None = None
        self._inbox_debounce = QTimer(self)
        self._inbox_debounce.setSingleShot(True)
        self._inbox_debounce.setInterval(2000)
        self._inbox_debounce.timeout.connect(self._check_inbox_new_files)
        self._watcher = QFileSystemWatcher(self)
        if os.path.isdir(self.inbox_dir):
            self._watcher.addPath(self.inbox_dir)
            self._watcher.directoryChanged.connect(self._on_inbox_changed)

        # 构建界面
        self._build_ui()
        self._connect_signals()
        self._start_clock()
        self._start_email_poll_timer()

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

        # 日志卡片（弹性拉伸撑满剩余空间）
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

        self.open_btn = QPushButton("打开输出文件夹")
        self.open_btn.setObjectName("OutlineBtn")
        self.open_btn.setCursor(Qt.PointingHandCursor)
        self.open_btn.clicked.connect(self._open_output_dir)
        h.addWidget(self.open_btn)

        self.pull_btn = QPushButton("拉取邮箱发票")
        self.pull_btn.setObjectName("OutlineBtn")
        self.pull_btn.setCursor(Qt.PointingHandCursor)
        self.pull_btn.clicked.connect(self._pull_invoices)
        h.addWidget(self.pull_btn)

        h.addStretch()

        # AI 审核滑动开关（主界面直接可见、可开关）
        ai_label = QLabel("AI 审核")
        ai_label.setFont(QFont(FONT_UI, SIZE_SMALL))
        ai_label.setStyleSheet(f"color: {Palette.TEXT_MUTED};")
        h.addWidget(ai_label)
        self.ai_toggle = ToggleSwitch(get_ai_enabled())
        self.ai_toggle.toggled.connect(self._on_ai_toggle)
        h.addWidget(self.ai_toggle)
        h.addSpacing(8)

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
        self.sig_pull_done.connect(self._on_pull_done)

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
        self._set_process_button_state(False)
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
            # 处理中再次点击 = 停止
            self._stop_processing()
            return
        self.is_processing = True
        self._set_process_button_state(True)
        self._on_progress(0.0, "0%")
        self.sig_light.emit(Palette.WARNING, True)
        self.sig_scan.emit(True)
        self._set_status("正在处理中…", "processing")

        # 重置统计
        for k in ('success', 'failure', 'tax_issues'):
            self._on_stat(k, 0)

        threading.Thread(target=self._process_files, daemon=True).start()

    def _set_process_button_state(self, processing: bool):
        """开始/停止按钮二合一：空闲显示「开始处理」，处理中显示红色「停止」"""
        if processing:
            self.process_btn.setText("停止")
            self.process_btn.setObjectName("DangerBtn")
        else:
            self.process_btn.setText("开始处理")
            self.process_btn.setObjectName("PrimaryBtn")
        # 切换 objectName 后重新应用 QSS 样式
        self.process_btn.style().unpolish(self.process_btn)
        self.process_btn.style().polish(self.process_btn)

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
            excel = result.get('excel')

            self.sig_log.emit(f"金额映射: {len(result['amount_map'])} 条", "info")
            self.sig_log.emit("待搜索文件替换完成", "success")

            for issue in tax_issues:
                self.sig_log.emit(issue, "warning")

            self.sig_stat.emit('tax_issues', len(tax_issues))

            if merged:
                self.sig_log.emit("PDF 合并完成", "success")
            else:
                self.sig_log.emit("PDF 合并失败", "error")

            if excel:
                self.sig_log.emit(f"费用汇总已生成: {excel}", "success")
            else:
                self.sig_log.emit("费用汇总生成失败（输出目录中可能无可识别发票）", "warning")

            # ── 审核：本地规则预检（总是执行，确定性兜底）+ AI 语义审核（开关控制）──
            local_findings = run_local_audit(self.output_dir, self.processor)
            if local_findings:
                self.sig_log.emit(f"本地规则预检发现 {len(local_findings)} 个问题：", "warning")
                for item in local_findings[:20]:
                    self.sig_log.emit(
                        f"  [{item.get('type', 'other')}] {item.get('file', '')}："
                        f"{item.get('issue', '')}",
                        "warning",
                    )
                if len(local_findings) > 20:
                    self.sig_log.emit(f"  …其余 {len(local_findings) - 20} 条省略", "info")
            else:
                self.sig_log.emit("本地规则预检：未发现问题", "success")

            ai_findings: list = []
            if get_ai_enabled():
                result = self._run_ai_audit(self.output_dir)
                if result is None:
                    self.sig_log.emit("AI 审核调用失败（请检查 API Key / 网络）", "warning")
                else:
                    ai_findings = result
                    if ai_findings:
                        self.sig_log.emit(f"AI 审核发现 {len(ai_findings)} 个问题：", "warning")
                        for item in ai_findings[:20]:
                            self.sig_log.emit(
                                f"  [{item.get('type', 'other')}] {item.get('file', '')}："
                                f"{item.get('issue', '')}（建议：{item.get('suggestion', '')}）",
                                "warning",
                            )
                        if len(ai_findings) > 20:
                            self.sig_log.emit(f"  …其余 {len(ai_findings) - 20} 条省略", "info")
                    else:
                        self.sig_log.emit("AI 审核：未发现问题", "success")

            # 审核报告回填 Excel「审核报告」工作表
            try:
                combined = (
                    [{'source': '本地规则', **f} for f in local_findings]
                    + [{'source': 'AI 审核', **f} for f in ai_findings]
                )
                report_path = write_audit_report(self.output_dir, combined)
                if report_path:
                    self.sig_log.emit(f"审核报告已写入: {report_path}", "success")
            except Exception as e:
                self.sig_log.emit(f"审核报告写入失败: {e}", "warning")

            # 自动模式：归档已处理的源文件，避免下次重复处理
            if self.auto_inbox and self.output_dir:
                self.auto_inbox = False
                self._archive_inbox_files()

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

    # ───────────────────────────────────────────────────
    # 邮箱自动拉取
    # ───────────────────────────────────────────────────
    def _start_email_poll_timer(self):
        """按 poll_minutes 定时自动拉取邮箱发票（0 = 不轮询）"""
        minutes = get_email_poll_minutes()
        if minutes <= 0:
            return
        self._email_poll_timer = QTimer(self)
        self._email_poll_timer.timeout.connect(self._pull_invoices)
        self._email_poll_timer.start(minutes * 60 * 1000)
        self.sig_log.emit(f"邮箱自动轮询已开启（每 {minutes} 分钟）", "info")

    def _pull_invoices(self):
        """拉取邮箱发票附件到收件箱目录（worker 线程执行）"""
        if self.is_processing:
            self.sig_log.emit("正在处理中，稍后再拉取邮箱发票", "warning")
            return
        if not get_email_enabled():
            self.sig_log.emit(
                "邮箱拉取未启用：请在 config.ini [email] 段填写账号/授权码并设 enabled = true",
                "warning",
            )
            return
        username = get_email_username()
        auth_code = get_email_auth_code()
        if not username or not auth_code:
            self.sig_log.emit("邮箱配置不完整：缺少账号或授权码（config.ini [email]）", "warning")
            return

        self.sig_log.emit("正在拉取邮箱发票…", "info")
        inbox_dir, days_back = self.inbox_dir, get_email_days_back()

        def _run():
            try:
                result = pull_invoices(
                    username=username, auth_code=auth_code,
                    inbox_dir=inbox_dir, days_back=days_back,
                )
            except Exception as e:
                result = {
                    'downloaded': 0, 'new_files': [],
                    'errors': [f'邮箱拉取失败: {e}'], 'total_scanned': 0,
                }
            self.sig_pull_done.emit(result)

        threading.Thread(target=_run, daemon=True).start()

    def _on_pull_done(self, result: dict):
        """主线程处理拉取结果；有新附件则自动开始处理"""
        for err in result.get('errors') or []:
            self.sig_log.emit(err, "warning")
        downloaded = result.get('downloaded', 0)
        scanned = result.get('total_scanned', 0)
        if downloaded:
            self.sig_log.emit(f"邮箱拉取完成：扫描 {scanned} 封，下载 {downloaded} 个附件", "success")
            self._refresh_inbox_known()
            if not self.is_processing:
                self.auto_inbox = True
                self._set_source_directory(self.inbox_dir)
                self.sig_log.emit("检测到新发票，自动开始处理…", "info")
                self._start_processing()
        else:
            self.sig_log.emit(f"邮箱拉取完成：扫描 {scanned} 封，无新发票附件", "info")

    def _on_inbox_changed(self, path: str):
        """收件箱目录变化（去抖后检查是否有新 PDF）"""
        if self.is_processing:
            return
        self._inbox_debounce.start()

    def _check_inbox_new_files(self):
        """检测收件箱顶层新增 PDF；有则自动开始处理"""
        if self.is_processing:
            return
        try:
            current = {
                f for f in os.listdir(self.inbox_dir)
                if f.lower().endswith('.pdf')
                and os.path.isfile(os.path.join(self.inbox_dir, f))
            }
        except OSError:
            return
        if self._inbox_known is None:
            self._inbox_known = current
            return
        new = current - self._inbox_known
        self._inbox_known = current
        if not new:
            return
        shown = '、'.join(sorted(new)[:5]) + ('…' if len(new) > 5 else '')
        self.sig_log.emit(f"检测到 {len(new)} 个新发票文件：{shown}", "info")
        self.auto_inbox = True
        self._set_source_directory(self.inbox_dir)
        self._start_processing()

    def _refresh_inbox_known(self):
        """刷新收件箱顶层 PDF 快照（避免误触发/漏触发）"""
        try:
            self._inbox_known = {
                f for f in os.listdir(self.inbox_dir)
                if f.lower().endswith('.pdf')
                and os.path.isfile(os.path.join(self.inbox_dir, f))
            }
        except OSError:
            pass

    def _archive_inbox_files(self):
        """自动模式：处理完成后把源 PDF 归档到 收件箱/已处理，避免重复处理"""
        try:
            archived_dir = os.path.join(self.inbox_dir, '已处理')
            os.makedirs(archived_dir, exist_ok=True)
            moved = 0
            for f in os.listdir(self.inbox_dir):
                src = os.path.join(self.inbox_dir, f)
                if not (os.path.isfile(src) and f.lower().endswith('.pdf')):
                    continue
                dst = os.path.join(archived_dir, f)
                counter = 1
                while os.path.exists(dst):
                    name, ext = os.path.splitext(f)
                    dst = os.path.join(archived_dir, f'{name}_{counter}{ext}')
                    counter += 1
                shutil.move(src, dst)
                moved += 1
            if moved:
                self.sig_log.emit(f"已将 {moved} 个已处理发票归档到 {archived_dir}", "info")
            self._refresh_inbox_known()
        except OSError as e:
            self.sig_log.emit(f"归档失败: {e}", "warning")

    def _run_ai_audit(self, output_dir: str) -> list | None:
        """收集解析数据并调用 AI 审核；返回问题列表，失败返回 None"""
        records = []
        try:
            for f in sorted(os.listdir(output_dir)):
                if not f.lower().endswith('.pdf') or f == '合并结果.pdf':
                    continue
                if not os.path.isfile(os.path.join(output_dir, f)):
                    continue
                rows = _parse_invoice(output_dir, f, self.processor)
                if rows:
                    records.append({'file': f, 'rows': rows})
        except OSError as e:
            self.sig_log.emit(f"AI 审核数据收集失败: {e}", "warning")
            return None

        if not records:
            self.sig_log.emit("AI 审核：无可用发票数据", "info")
            return []

        self.sig_log.emit(f"AI 审核中…（{len(records)} 个文件）", "info")
        try:
            return audit_records(
                records,
                api_key=get_ai_api_key(),
                api_base=get_ai_api_base(),
                model=get_ai_model(),
            )
        except Exception as e:
            self.sig_log.emit(f"AI 审核调用失败: {e}", "warning")
            return None

    def _show_settings(self):
        """打开设置对话框，保存后刷新 UI 并重载邮箱/AI 配置"""
        dialog = SettingsDialog(self)
        if dialog.exec() == SettingsDialog.Accepted:
            # 配置已保存并 reload，更新 UI 上显示的线程数
            self.sig_log.emit(
                f"配置已更新：税号 {_cfg.TARGET_TAX_ID}，线程数 {_cfg.MAX_WORKERS}",
                "info",
            )
            self.ai_toggle.setChecked(get_ai_enabled())
            self._reload_email_settings()

    def _on_ai_toggle(self, checked: bool):
        """滑动开关：即时保存 AI 审核开关状态"""
        try:
            set_ai_config(enabled='true' if checked else 'false')
        except OSError as e:
            self.sig_log.emit(f"AI 审核配置保存失败: {e}", "error")
            # 保存失败回滚开关状态
            self.ai_toggle.blockSignals(True)
            self.ai_toggle.setChecked(not checked)
            self.ai_toggle.blockSignals(False)
            return
        self.sig_log.emit(
            f"AI 审核已{'开启' if checked else '关闭'}",
            "success" if checked else "info",
        )

    def _reload_email_settings(self):
        """设置保存后重载邮箱配置：收件箱监听目录 + 自动轮询定时器"""
        new_inbox = get_inbox_dir()
        if new_inbox != self.inbox_dir:
            try:
                self._watcher.removePath(self.inbox_dir)
            except Exception:
                pass
            self.inbox_dir = new_inbox
            try:
                os.makedirs(self.inbox_dir, exist_ok=True)
            except OSError:
                pass
            self._watcher.addPath(self.inbox_dir)
            self._refresh_inbox_known()
            self.sig_log.emit(f"发票收件箱目录已更新: {self.inbox_dir}", "info")

        minutes = get_email_poll_minutes()
        if hasattr(self, '_email_poll_timer'):
            self._email_poll_timer.stop()
        if minutes > 0:
            if not hasattr(self, '_email_poll_timer'):
                self._email_poll_timer = QTimer(self)
                self._email_poll_timer.timeout.connect(self._pull_invoices)
            self._email_poll_timer.start(minutes * 60 * 1000)
            self.sig_log.emit(f"邮箱自动轮询已更新（每 {minutes} 分钟）", "info")
        elif hasattr(self, '_email_poll_timer'):
            self.sig_log.emit("邮箱自动轮询已关闭", "info")

        if get_email_enabled():
            self.sig_log.emit("邮箱自动拉取已启用，收件箱监听中", "success")
        else:
            self.sig_log.emit("邮箱自动拉取未启用（设置中勾选后生效）", "warning")

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
