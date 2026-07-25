from datetime import datetime

from tkinter import Canvas, Frame, Label
from tkinter.ttk import Button

from .colors import MDColors


# ═══════════════════════════════════════════════════════════
# Material Design 自定义组件
# ═══════════════════════════════════════════════════════════
class MDCard(Frame):
    """Material Design 卡片容器 - 带阴影效果"""

    def __init__(self, parent, padding=16, elevation=2, corner_radius=12, **kwargs):
        super().__init__(parent, **kwargs)
        self.padding = padding
        self.elevation = elevation
        self.corner_radius = corner_radius
        self.canvas = Canvas(self, highlightthickness=0, bg=MDColors.SURFACE)
        self.canvas.pack(fill='both', expand=True)
        self.inner_frame = Frame(self.canvas)
        # window item 跟随 canvas 尺寸变化，在 _on_configure 中更新
        self._content_window_id = self.canvas.create_window(
            0, 0, window=self.inner_frame, anchor='nw'
        )
        self.bind('<Configure>', self._on_configure)

    def _on_configure(self, event):
        w = event.width
        h = event.height
        r = self.corner_radius
        e = self.elevation
        # 清除旧绘制图形（保留 window item，避免销毁其关联的 widget）
        for item in self.canvas.find_all():
            if item == self._content_window_id:
                continue
            self.canvas.delete(item)
        # 绘制阴影
        shadow_offsets = [(2, 2), (4, 4), (6, 5), (8, 6), (10, 7)]
        shadow_colors = ['#F0F0F0', '#E8E8E8', '#E0E0E0', '#D8D8D8', '#D0D0D0']
        for (dx, dy), color in zip(shadow_offsets[:e], shadow_colors[:e]):
            self.canvas.create_arc(
                dx - r, dy - r, w + dx + r, h + dy + r,
                start=0, extent=360, style='pieslice',
                fill=color, outline=''
            )
        # 绘制卡片主体（圆角矩形）
        self.canvas.create_arc(
            -r, -r, r, r, start=90, extent=90,
            style='pieslice', fill=MDColors.SURFACE, outline=''
        )
        self.canvas.create_arc(
            w - r, -r, w + r, r, start=0, extent=90,
            style='pieslice', fill=MDColors.SURFACE, outline=''
        )
        self.canvas.create_arc(
            -r, h - r, r, h + r, start=180, extent=90,
            style='pieslice', fill=MDColors.SURFACE, outline=''
        )
        self.canvas.create_arc(
            w - r, h - r, w + r, h + r, start=270, extent=90,
            style='pieslice', fill=MDColors.SURFACE, outline=''
        )
        self.canvas.create_rectangle(0, -r, w, h + r, fill=MDColors.SURFACE, outline='')
        self.canvas.create_rectangle(-r, 0, w + r, h, fill=MDColors.SURFACE, outline='')
        # 更新内部窗口尺寸铺满 canvas（带 padding）
        p = self.padding
        self.canvas.coords(self._content_window_id, p, p)
        self.canvas.itemconfigure(
            self._content_window_id,
            width=max(w - 2 * p, 1), height=max(h - 2 * p, 1)
        )
        self.canvas.tag_raise('all')


class MDButton(Button):
    """Material Design 按钮 - 圆角样式与悬停/按下反馈"""

    def __init__(self, parent, text='', command=None, variant='filled',
                 icon=None, style_name=None, width=None, **kwargs):
        self.command_fn = command
        self.variant = variant
        self.icon = icon
        self.parent = parent
        super().__init__(parent, text=text, command=self._on_click, **kwargs)
        self.bind('<Enter>', self._on_enter)
        self.bind('<Leave>', self._on_leave)
        self.bind('<ButtonPress-1>', self._on_press)
        self.bind('<ButtonRelease-1>', self._on_release)

    def _on_click(self):
        if self.command_fn:
            self.command_fn()

    def _on_enter(self, event):
        self.configure(style='Accent.TButton.Hover' if self.variant == 'filled' else 'TButton.Hover')

    def _on_leave(self, event):
        self.configure(style='Accent.TButton' if self.variant == 'filled' else 'TButton')

    def _on_press(self, event):
        if self.variant == 'filled':
            self.configure(style='Accent.TButton.Pressed')

    def _on_release(self, event):
        if self.variant == 'filled':
            self.configure(style='Accent.TButton.Hover')


class MDIconLabel(Label):
    """带 Emoji 图标的标签"""

    def __init__(self, parent, icon='', text='', font_size=10, **kwargs):
        display_text = f"  {text}" if text else icon
        super().__init__(parent, text=display_text, **kwargs)
        self.icon = icon
        self.text_content = text


class LogText:
    """Material Design 风格的日志区域"""

    def __init__(self, parent, height=12):
        self.frame = Frame(parent)
        self.frame.pack(fill='both', expand=True)

        from tkinter.scrolledtext import ScrolledText

        # 日志头部
        header = Frame(self.frame)
        header.pack(fill='x', pady=(0, 4))

        self.icon_label = Label(header, text="  处理日志", font=('Microsoft YaHei UI', 10, 'bold'),
                                 foreground=MDColors.ON_SURFACE)
        self.icon_label.pack(side='left')

        self.count_label = Label(header, text="0 条记录", font=('Microsoft YaHei UI', 9),
                                   foreground=MDColors.ON_SURFACE_VARIANT)
        self.count_label.pack(side='right')

        # 日志文本框
        self.text_widget = ScrolledText(
            self.frame, height=height,
            font=('Cascadia Code', 9),
            relief='flat', borderwidth=0,
            background=MDColors.SURFACE_VARIANT,
            foreground=MDColors.ON_SURFACE,
            insertbackground=MDColors.PRIMARY,
            selectbackground=MDColors.PRIMARY_LIGHT,
            padx=12, pady=8,
            wrap='word'
        )
        self.text_widget.pack(fill='both', expand=True)

        # 配置日志文本标签
        self.text_widget.tag_configure('info', foreground=MDColors.INFO)
        self.text_widget.tag_configure('success', foreground=MDColors.SUCCESS)
        self.text_widget.tag_configure('warning', foreground=MDColors.WARNING)
        self.text_widget.tag_configure('error', foreground=MDColors.ERROR)
        self.text_widget.tag_configure('separator', foreground=MDColors.DIVIDER)
        self.text_widget.tag_configure('timestamp', foreground=MDColors.ON_SURFACE_VARIANT)
        self.text_widget.tag_configure('bold', font=('Cascadia Code', 9, 'bold'))

        self.log_count = 0

    def log(self, message, level='info'):
        """添加带颜色标记的日志"""
        self.log_count += 1
        timestamp = datetime.now().strftime('%H:%M:%S')

        self.text_widget.insert('end', f"[{timestamp}] ", 'timestamp')

        level_prefix = {
            'info': 'INFO',
            'success': 'SUCCESS',
            'warning': 'WARN ',
            'error': 'ERROR'
        }.get(level, 'INFO')

        self.text_widget.insert('end', f"{level_prefix}: ", level)
        self.text_widget.insert('end', f"{message}\n")

        self.text_widget.see('end')
        self.count_label.config(text=f"{self.log_count} 条记录")

    def separator(self):
        """添加分隔线"""
        self.text_widget.insert('end', '─' * 60 + '\n', 'separator')

    def clear(self):
        """清空日志"""
        self.text_widget.delete('1.0', 'end')
        self.log_count = 0
        self.count_label.config(text="0 条记录")

    def pack(self, **kwargs):
        self.frame.pack(**kwargs)
