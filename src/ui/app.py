import os
import queue
import shutil
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import sv_ttk
from tkinter import Tk, filedialog, messagebox, Canvas, Entry, Frame, Label
from tkinter.ttk import Button, Progressbar, Style

from .colors import MDColors
from .components import LogText
from ..core.processor import InvoiceProcessor
from ..config import WINDOW_GEOMETRY, WINDOW_MIN_SIZE, MAX_WORKERS, FONT_FAMILY, FONT_CODE


# ═══════════════════════════════════════════════════════════
# 应用程序主界面 - Material Design
# ═══════════════════════════════════════════════════════════
class InvoiceApp:
    """发票处理应用程序 - Material Design 风格"""

    def __init__(self, root):
        self.root = root
        self.root.title("SYNTEC - 电子票据处理系统")
        self.root.geometry(WINDOW_GEOMETRY)
        self.root.resizable(True, True)
        self.root.minsize(*WINDOW_MIN_SIZE)

        # 设置窗口背景
        self.root.configure(bg=MDColors.BACKGROUND)

        # 应用主题
        sv_ttk.set_theme("light")

        self.processor = InvoiceProcessor()
        self.output_dir = None
        self.source_dir = os.getcwd()
        self.log_queue = queue.Queue()
        self.is_processing = False
        self._stats = {'total': 0, 'success': 0, 'failure': 0, 'tax_issues': 0}

        # 初始化字体
        self._init_fonts()
        # 配置样式
        self._setup_styles()
        # 构建界面
        self._build_ui()
        # 启动日志轮询
        self._poll_log_queue()

    def _init_fonts(self):
        """初始化字体族"""
        self.font_title = (FONT_FAMILY, 20, 'bold')
        self.font_subtitle = (FONT_FAMILY, 11)
        self.font_body = (FONT_FAMILY, 10)
        self.font_body_bold = (FONT_FAMILY, 10, 'bold')
        self.font_small = (FONT_FAMILY, 9)
        self.font_btn = (FONT_FAMILY, 10)
        self.font_stat_value = (FONT_FAMILY, 22, 'bold')
        self.font_stat_label = (FONT_FAMILY, 9)
        self.font_code = (FONT_CODE, 9)

    def _setup_styles(self):
        """配置 Material Design 样式系统"""
        style = Style()

        # 主色调按钮
        style.configure('Accent.TButton',
                         font=self.font_btn,
                         foreground=MDColors.ON_PRIMARY,
                         background=MDColors.PRIMARY,
                         borderwidth=0,
                         padding=(24, 10))
        style.map('Accent.TButton',
                   background=[('active', MDColors.PRIMARY_DARK)])

        style.configure('Accent.TButton.Hover',
                         background=MDColors.PRIMARY_DARK,
                         foreground=MDColors.ON_PRIMARY,
                         borderwidth=0,
                         padding=(24, 10))

        style.configure('Accent.TButton.Pressed',
                         background=MDColors.PRIMARY_VARIANT,
                         foreground=MDColors.ON_PRIMARY,
                         borderwidth=0,
                         padding=(24, 10))

        # 次要按钮（轮廓风格）
        style.configure('Outline.TButton',
                         font=self.font_btn,
                         foreground=MDColors.PRIMARY,
                         background=MDColors.SURFACE,
                         borderwidth=1,
                         relief='solid',
                         padding=(20, 10))

        style.map('Outline.TButton',
                   background=[('active', MDColors.SURFACE_VARIANT)])

        # 文字按钮
        style.configure('Text.TButton',
                         font=self.font_btn,
                         foreground=MDColors.PRIMARY,
                         background=MDColors.SURFACE,
                         borderwidth=0,
                         padding=(16, 8))

        style.map('Text.TButton',
                   background=[('active', MDColors.SURFACE_VARIANT)])

        # 危险按钮
        style.configure('Danger.TButton',
                         font=self.font_btn,
                         foreground=MDColors.ERROR,
                         background=MDColors.ERROR_LIGHT,
                         borderwidth=0,
                         padding=(20, 10))

        # 输入框
        style.configure('MD.TEntry',
                         font=self.font_body,
                         fieldbackground=MDColors.SURFACE_VARIANT,
                         foreground=MDColors.ON_SURFACE,
                         insertcolor=MDColors.PRIMARY,
                         borderwidth=0,
                         padding=(12, 8))

        # 进度条
        style.configure('MD.Horizontal.TProgressbar',
                         troughcolor=MDColors.SURFACE_VARIANT,
                         background=MDColors.PRIMARY,
                         thickness=6,
                         borderwidth=0)

        # 状态标签
        style.configure('Status.TLabel',
                         font=self.font_body,
                         background=MDColors.SURFACE)

        style.configure('StatusWarning.TLabel',
                         font=self.font_body_bold,
                         foreground=MDColors.WARNING,
                         background=MDColors.SURFACE)

        style.configure('StatusError.TLabel',
                         font=self.font_body_bold,
                         foreground=MDColors.ERROR,
                         background=MDColors.SURFACE)

        style.configure('StatusSuccess.TLabel',
                         font=self.font_body_bold,
                         foreground=MDColors.SUCCESS,
                         background=MDColors.SURFACE)

    def _build_ui(self):
        """构建 Material Design 布局"""
        # ─── 顶部导航栏 ───
        self._build_appbar()

        # ─── 主内容区域 ───
        content = Frame(self.root, bg=MDColors.BACKGROUND)
        content.pack(fill='both', expand=True, padx=24, pady=(8, 0))

        # 左上角装饰（渐变条）
        self.accent_bar = Canvas(content, height=4, bg=MDColors.BACKGROUND,
                                   highlightthickness=0)
        self.accent_bar.pack(fill='x', pady=(0, 16))
        self.root.after(100, lambda: self._draw_gradient_bar())

        # ─── 文件选择卡片 ───
        self._build_source_card(content)

        # ─── 统计面板 ───
        self._build_stats_panel(content)

        # ─── 进度卡片 ───
        self._build_progress_card(content)

        # ─── 操作按钮区 ───
        self._build_action_bar(content)

        # ─── 日志卡片 ───
        self._build_log_card(content)

        # ─── 底部状态栏 ───
        self._build_status_bar()

    def _draw_gradient_bar(self):
        """绘制顶部渐变装饰条"""
        w = self.accent_bar.winfo_width()
        if w <= 1:
            self.root.after(100, self._draw_gradient_bar)
            return
        bar_height = 4
        steps = min(w, 60)
        step_width = w / steps
        for i in range(steps):
            ratio = i / steps
            r = int(0x3F + (0x00 - 0x3F) * ratio)
            g = int(0x51 + (0x96 - 0x51) * ratio)
            b = int(0xB5 + (0x88 - 0xB5) * ratio)
            color = f'#{r:02x}{g:02x}{b:02x}'
            x1 = i * step_width
            x2 = (i + 1) * step_width
            self.accent_bar.create_rectangle(
                x1, 0, x2, bar_height, fill=color, outline=''
            )

    def _build_appbar(self):
        """构建顶部应用栏"""
        appbar = Frame(self.root, bg=MDColors.PRIMARY, height=56)
        appbar.pack(fill='x')
        appbar.pack_propagate(False)

        # 左侧标题
        title_frame = Frame(appbar, bg=MDColors.PRIMARY)
        title_frame.pack(side='left', padx=20, pady=12)

        Label(title_frame, text="SYNTEC",
              font=('Segoe UI Variable', 16, 'bold'),
              foreground=MDColors.ON_PRIMARY,
              background=MDColors.PRIMARY).pack(side='left')

        Label(title_frame, text="  电子票据处理系统",
              font=(FONT_FAMILY, 12),
              foreground=MDColors.ON_PRIMARY,
              background=MDColors.PRIMARY).pack(side='left', padx=(8, 0))

        # 右侧版本号
        Label(appbar, text="v6.0",
              font=('Segoe UI', 9),
              foreground=MDColors.PRIMARY_LIGHT,
              background=MDColors.PRIMARY).pack(side='right', padx=20)

    def _build_source_card(self, content):
        """构建源文件选择卡片"""
        card_frame = Frame(content, bg=MDColors.BACKGROUND)
        card_frame.pack(fill='x', pady=(0, 12))

        card_inner = Frame(card_frame, bg=MDColors.SURFACE, padx=20, pady=16)
        card_inner.pack(fill='x')

        # 卡片标题行
        header = Frame(card_inner, bg=MDColors.SURFACE)
        header.pack(fill='x', pady=(0, 12))

        Label(header, text="  选择文件目录",
              font=self.font_body_bold,
              foreground=MDColors.ON_SURFACE,
              background=MDColors.SURFACE).pack(side='left')

        self.dir_hint_label = Label(header, text="请选择包含PDF发票的文件夹",
                                     font=self.font_small,
                                     foreground=MDColors.ON_SURFACE_VARIANT,
                                     background=MDColors.SURFACE)
        self.dir_hint_label.pack(side='right')

        # 路径输入框
        entry_frame = Frame(card_inner, bg=MDColors.SURFACE_VARIANT)
        entry_frame.pack(fill='x')

        self.dir_entry = Entry(entry_frame, font=self.font_body,
                                bg=MDColors.SURFACE_VARIANT,
                                fg=MDColors.ON_SURFACE,
                                insertbackground=MDColors.PRIMARY,
                                relief='flat',
                                readonlybackground=MDColors.SURFACE_VARIANT,
                                disabledbackground=MDColors.SURFACE_VARIANT,
                                disabledforeground=MDColors.ON_SURFACE_VARIANT)
        self.dir_entry.pack(side='left', fill='x', expand=True, ipady=8, padx=(12, 8), pady=8)
        self.dir_entry.insert(0, "未选择目录")
        self.dir_entry.config(state='readonly')

        browse_btn = Button(entry_frame, text="浏览...",
                            command=self._select_directory,
                            style='Outline.TButton')
        browse_btn.pack(side='right', padx=4, pady=6)

    def _build_stats_panel(self, content):
        """构建统计面板（4个指标卡片）"""
        stats_outer = Frame(content, bg=MDColors.BACKGROUND)
        stats_outer.pack(fill='x', pady=(0, 12))

        stats_container = Frame(stats_outer, bg=MDColors.BACKGROUND)
        stats_container.pack(fill='x')

        self.stat_cards = {}
        stat_configs = [
            ('total', '文件总数', '0', MDColors.PRIMARY),
            ('success', '处理成功', '0', MDColors.SUCCESS),
            ('failure', '处理失败', '0', MDColors.ERROR),
            ('tax_issues', '税号异常', '0', MDColors.WARNING),
        ]

        for i, (key, label, default, color) in enumerate(stat_configs):
            card = Frame(stats_container, bg=MDColors.SURFACE, padx=12, pady=12)
            card.pack(side='left', fill='both', expand=True, padx=(0, 8))

            # 左侧色条
            indicator = Frame(card, bg=color, width=4)
            indicator.pack(side='left', fill='y', padx=(0, 10))

            text_frame = Frame(card, bg=MDColors.SURFACE)
            text_frame.pack(side='left', fill='both', expand=True)

            value_label = Label(text_frame, text=default,
                                font=self.font_stat_value,
                                foreground=color,
                                background=MDColors.SURFACE)
            value_label.pack(anchor='w')

            name_label = Label(text_frame, text=label,
                               font=self.font_stat_label,
                               foreground=MDColors.ON_SURFACE_VARIANT,
                               background=MDColors.SURFACE)
            name_label.pack(anchor='w')

            self.stat_cards[key] = value_label

        # 移除最后一个的右边距
        # (tkinter 不支持 last-child，间距很小可以接受)

    def _build_progress_card(self, content):
        """构建进度卡片"""
        card_inner = Frame(content, bg=MDColors.SURFACE, padx=20, pady=14)
        card_inner.pack(fill='x', pady=(0, 12))

        progress_header = Frame(card_inner, bg=MDColors.SURFACE)
        progress_header.pack(fill='x', pady=(0, 8))

        Label(progress_header, text="  处理进度",
              font=self.font_body_bold,
              foreground=MDColors.ON_SURFACE,
              background=MDColors.SURFACE).pack(side='left')

        self.progress_percent = Label(progress_header, text="0%",
                                      font=self.font_body_bold,
                                      foreground=MDColors.PRIMARY,
                                      background=MDColors.SURFACE)
        self.progress_percent.pack(side='right')

        self.progress = Progressbar(card_inner, mode='determinate',
                                     style='MD.Horizontal.TProgressbar')
        self.progress.pack(fill='x')

    def _build_action_bar(self, content):
        """构建操作按钮区域"""
        action_frame = Frame(content, bg=MDColors.BACKGROUND)
        action_frame.pack(fill='x', pady=(0, 12))

        self.process_btn = Button(action_frame, text="  开始处理",
                                   command=self._start_processing,
                                   style='Accent.TButton')
        self.process_btn.pack(side='left', padx=(0, 12))

        self.stop_btn = Button(action_frame, text="  停止",
                               command=self._stop_processing,
                               style='Danger.TButton',
                               state='disabled')
        self.stop_btn.pack(side='left', padx=(0, 12))

        self.open_btn = Button(action_frame, text="  打开输出文件夹",
                               command=self._open_output_dir,
                               style='Outline.TButton')
        self.open_btn.pack(side='left')

        # 右侧时间
        self.time_label = Label(action_frame, text=datetime.now().strftime('%Y-%m-%d %H:%M'),
                                font=self.font_small,
                                foreground=MDColors.ON_SURFACE_VARIANT,
                                background=MDColors.BACKGROUND)
        self.time_label.pack(side='right')
        self._tick_clock()

    def _build_log_card(self, content):
        """构建日志卡片"""
        card_inner = Frame(content, bg=MDColors.SURFACE, padx=16, pady=12)
        card_inner.pack(fill='both', expand=True, pady=(0, 8))

        self.log_widget = LogText(card_inner, height=10)
        self.log_widget.pack(fill='both', expand=True)

        # 底部操作
        log_footer = Frame(card_inner, bg=MDColors.SURFACE)
        log_footer.pack(fill='x', pady=(8, 0))

        Button(log_footer, text="清空日志", command=self._clear_log,
               style='Text.TButton').pack(side='left')

        # 税号状态
        self.tax_status_label = Label(log_footer, text="  未检测到异常税号",
                                       font=self.font_body_bold,
                                       foreground=MDColors.SUCCESS,
                                       background=MDColors.SURFACE)
        self.tax_status_label.pack(side='right')

    def _build_status_bar(self):
        """构建底部状态栏"""
        statusbar = Frame(self.root, bg=MDColors.SURFACE_VARIANT, height=32)
        statusbar.pack(fill='x', side='bottom')
        statusbar.pack_propagate(False)

        self.status_label = Label(statusbar, text="就绪 - 请选择文件目录后开始处理",
                                   font=self.font_small,
                                   foreground=MDColors.ON_SURFACE_VARIANT,
                                   background=MDColors.SURFACE_VARIANT,
                                   padx=16)
        self.status_label.pack(side='left', pady=6)

        # 状态指示灯
        self.status_indicator = Canvas(statusbar, width=8, height=8,
                                        bg=MDColors.SURFACE_VARIANT,
                                        highlightthickness=0)
        self.status_indicator.pack(side='left', padx=(8, 0), pady=12)
        self._draw_status_light(MDColors.SUCCESS)

    def _draw_status_light(self, color):
        """绘制状态指示灯"""
        self.status_indicator.delete('all')
        r = 4
        self.status_indicator.create_oval(0, 0, 2 * r, 2 * r, fill=color, outline='')

    def _tick_clock(self):
        """更新时钟"""
        self.time_label.config(text=datetime.now().strftime('%Y-%m-%d %H:%M'))
        self.root.after(30000, self._tick_clock)

    def _update_stat(self, key, value):
        """更新统计数字"""
        if key in self.stat_cards:
            self.stat_cards[key].config(text=str(value))

    def _clear_log(self):
        """清空日志"""
        self.log_widget.clear()

    # ─── 交互方法 ───
    def _select_directory(self):
        """选择目录"""
        dir_path = filedialog.askdirectory(title='选择包含PDF发票的文件夹', initialdir=self.source_dir)
        if dir_path:
            self.source_dir = dir_path
            os.chdir(dir_path)

            # 计算文件数
            pdf_count = len([f for f in os.listdir(dir_path) if f.lower().endswith('.pdf')])

            self.dir_entry.config(state='normal')
            self.dir_entry.delete(0, 'end')
            self.dir_entry.insert(0, dir_path)
            self.dir_entry.config(state='readonly')

            self.dir_hint_label.config(
                text=f"发现 {pdf_count} 个PDF文件",
                foreground=MDColors.PRIMARY
            )

            self._update_stat('total', pdf_count)
            self._log(f"已选择目录: {dir_path}（包含 {pdf_count} 个PDF文件）")
            self._set_status(f"已就绪 - {pdf_count} 个文件待处理", 'ready')

    def _start_processing(self):
        """开始处理"""
        if self.is_processing:
            return
        self.is_processing = True
        self.process_btn.config(state='disabled')
        self.stop_btn.config(state='normal')
        self.progress['value'] = 0
        self._draw_status_light(MDColors.WARNING)
        self._set_status("正在处理中...", 'processing')

        # 重置统计
        self._stats = {'total': 0, 'success': 0, 'failure': 0, 'tax_issues': 0}
        self._update_stat('success', 0)
        self._update_stat('failure', 0)
        self._update_stat('tax_issues', 0)

        thread = threading.Thread(target=self._process_files, daemon=True)
        thread.start()

    def _stop_processing(self):
        """停止处理（标记停止）"""
        self.is_processing = False
        self._log("用户请求停止处理")
        self._set_status("正在停止...", 'processing')

    def _process_single_file(self, filename):
        """处理单个PDF文件"""
        file_path = os.path.join(self.source_dir, filename)
        text = self.processor.extract_pdf_text(file_path)

        if not text:
            dest = self._move_to_manual_review(file_path, filename)
            return filename, dest, 'error', f'解析失败，已归集到需人工处理: {filename}'

        processor_func = self.processor.determine_processor_type(text)

        if processor_func:
            result = processor_func(file_path, self.output_dir)
            if result:
                return filename, result, 'success', f'成功: {os.path.basename(result)}'
            else:
                dest = self._move_to_manual_review(file_path, filename)
                return filename, dest, 'warning', f'字段提取失败，已归集到需人工处理: {filename}'
        else:
            dest = self._move_to_manual_review(file_path, filename)
            return filename, dest, 'warning', f'类型未识别，已归集到需人工处理: {filename}'

    def _move_to_manual_review(self, file_path, filename):
        """将失败文件复制到 需人工处理/ 子目录，保留原文件名（重名追加序号）"""
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

    def _process_files(self):
        """处理文件（子线程）"""
        try:
            pdf_files = [f for f in os.listdir(self.source_dir) if f.lower().endswith('.pdf')]
            total_files = len(pdf_files)

            if total_files == 0:
                self._log('未找到PDF文件，请选择包含PDF文件的目录', 'warning')
                self.is_processing = False
                self.root.after(0, lambda: self.process_btn.config(state='normal'))
                self.root.after(0, lambda: self.stop_btn.config(state='disabled'))
                self.root.after(0, lambda: self._set_status("未找到PDF文件", 'error'))
                return

            self.output_dir = self.processor.create_output_directory(self.source_dir)
            self._log(f'发现 {total_files} 个待处理文件')
            self.log_widget.separator()

            success_count = 0
            failure_count = 0

            max_workers = MAX_WORKERS
            self._log(f'使用 {max_workers} 线程并发处理')

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_file = {executor.submit(self._process_single_file, f): f
                                  for f in pdf_files}

                # UI 节流：进度条按文件数分桶更新，避免大批量文件时事件队列积压
                progress_step = max(1, total_files // 100)

                for i, future in enumerate(as_completed(future_to_file), 1):
                    if not self.is_processing:
                        self._log("处理已中止", 'warning')
                        break

                    filename, result, log_type, message = future.result()

                    self._log(message, log_type)

                    if log_type == 'success':
                        success_count += 1
                    else:
                        failure_count += 1

                    # 成功/失败计数每文件更新（开销小，用户关注实时数字）
                    self.root.after(0, lambda s=success_count: self._update_stat('success', s))
                    self.root.after(0, lambda f=failure_count: self._update_stat('failure', f))

                    # 进度条节流：仅按分桶或最后一个文件时更新
                    if i % progress_step == 0 or i == total_files:
                        progress = (i / total_files) * 90
                        self.root.after(0, lambda p=progress: self.progress.config(value=p))
                        self.root.after(0, lambda p=progress: self.progress_percent.config(
                            text=f"{int(p)}%"))

            if not self.is_processing:
                self._log("处理已中止，部分文件可能未完成", 'warning')
                self._set_status("处理已中止", 'warning')
                return

            self._stats['success'] = success_count
            self._stats['failure'] = failure_count

            self.log_widget.separator()
            self._log(f'统计: 总{total_files} | 成功 {success_count} | 失败 {failure_count}', 'info')

            # 后处理阶段（单次调用合并金额映射+替换+税号检查+PDF合并）
            self.root.after(0, lambda: self._set_status("执行后处理...", 'processing'))
            self._log('执行后处理...', 'info')

            result = self.processor.post_process(self.output_dir)
            tax_issues = result['tax_issues']
            merged = result['merged']

            self._log(f'金额映射: {len(result["amount_map"])} 条')
            self._log('待搜索文件替换完成', 'success')

            for issue in tax_issues:
                self._log(issue, 'warning')

            self.root.after(0, lambda: self._update_stat('tax_issues', len(tax_issues)))
            self.root.after(0, lambda: self.tax_status_label.config(
                text=f"  发现 {len(tax_issues)} 个异常税号" if tax_issues else "  未检测到异常税号",
                foreground=MDColors.WARNING if tax_issues else MDColors.SUCCESS
            ))

            if merged:
                self._log(f'PDF合并完成', 'success')
            else:
                self._log('PDF合并失败', 'error')

            self.processor.clear_cache()

            self.root.after(0, lambda: self.progress.config(value=100))
            self.root.after(0, lambda: self.progress_percent.config(text="100%"))
            self.log_widget.separator()
            self._log('所有处理已完成！', 'success')
            self.root.after(0, lambda: self._set_status(
                f"处理完成 - 成功 {success_count}/{total_files}" +
                (f"，{len(tax_issues)} 个税号异常" if tax_issues else ""),
                'success' if failure_count == 0 and not tax_issues else 'warning'
            ))
            self.root.after(0, lambda: self._draw_status_light(
                MDColors.SUCCESS if failure_count == 0 else MDColors.WARNING))

        except Exception as e:
            self._log(f"处理出错: {e}", 'error')
            self.root.after(0, lambda: self._set_status(f"处理出错: {e}", 'error'))
            self.root.after(0, lambda: self._draw_status_light(MDColors.ERROR))
        finally:
            self.is_processing = False
            self.root.after(0, lambda: self.process_btn.config(state='normal'))
            self.root.after(0, lambda: self.stop_btn.config(state='disabled'))

    def _log(self, message, level='info'):
        """发送日志消息"""
        self.log_queue.put((message, level))

    def _poll_log_queue(self):
        """轮询日志队列"""
        try:
            while True:
                message, level = self.log_queue.get_nowait()
                self.log_widget.log(message, level)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_log_queue)

    def _set_status(self, text, state='ready'):
        """设置底部状态栏"""
        status_map = {
            'ready': MDColors.ON_SURFACE_VARIANT,
            'processing': MDColors.PRIMARY,
            'success': MDColors.SUCCESS,
            'warning': MDColors.WARNING,
            'error': MDColors.ERROR,
        }
        color = status_map.get(state, MDColors.ON_SURFACE_VARIANT)
        self.status_label.config(text=text, foreground=color)

    def _open_output_dir(self):
        """打开输出目录"""
        if self.output_dir:
            try:
                if os.path.exists(self.output_dir):
                    os.startfile(self.output_dir)
                else:
                    messagebox.showinfo("提示", "输出目录不存在")
            except Exception as e:
                messagebox.showerror("错误", f"无法打开目录: {e}\n\n路径: {self.output_dir}")
        else:
            messagebox.showinfo("提示", "尚未生成输出目录，请先处理文件")
