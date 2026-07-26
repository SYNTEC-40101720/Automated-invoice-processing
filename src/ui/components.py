from datetime import datetime

from tkinter import Frame, Label
from tkinter.scrolledtext import ScrolledText

from .colors import MDColors


# ═══════════════════════════════════════════════════════════
# Material Design 自定义组件
# ═══════════════════════════════════════════════════════════

class LogText:
    """Material Design 风格的日志区域"""

    def __init__(self, parent, height=12):
        self.frame = Frame(parent)
        self.frame.pack(fill='both', expand=True)

        # 日志头部
        header = Frame(self.frame)
        header.pack(fill='x', pady=(0, 4))

        self.icon_label = Label(header, text="  处理日志",
                                font=('Microsoft YaHei UI', 10, 'bold'),
                                foreground=MDColors.ON_SURFACE)
        self.icon_label.pack(side='left')

        self.count_label = Label(header, text="0 条记录",
                                 font=('Microsoft YaHei UI', 9),
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
