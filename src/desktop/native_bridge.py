"""pywebview 原生能力桥接。"""

from __future__ import annotations

import os
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog


class NativeBridge:
    """只提供文件选择和打开目录，不承载业务编排。"""

    @staticmethod
    def _dialog_root() -> tk.Tk:
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        return root

    def select_directory(self) -> str:
        root = self._dialog_root()
        try:
            return filedialog.askdirectory(title='选择包含 PDF 发票的文件夹') or ''
        finally:
            root.destroy()

    def select_pdf_files(self) -> list[str]:
        root = self._dialog_root()
        try:
            return list(filedialog.askopenfilenames(
                title='选择 PDF 发票',
                filetypes=[('PDF 文件', '*.pdf'), ('所有文件', '*.*')],
            ))
        finally:
            root.destroy()

    def save_log_dialog(self, default_name: str = 'invoice.log') -> str:
        root = self._dialog_root()
        try:
            return filedialog.asksaveasfilename(
                title='导出处理日志',
                initialfile=default_name,
                defaultextension='.txt',
                filetypes=[('文本文件', '*.txt'), ('所有文件', '*.*')],
            ) or ''
        finally:
            root.destroy()

    @staticmethod
    def open_directory(path: str) -> bool:
        target = Path(path).expanduser().resolve()
        if not target.is_dir():
            return False
        if os.name == 'nt':
            os.startfile(str(target))
        else:
            raise OSError('打开目录仅支持 Windows 桌面壳')
        return True

    @staticmethod
    def get_runtime_info() -> dict[str, str | bool]:
        return {'platform': sys.platform, 'webview2': os.name == 'nt', 'version': '7.0.0'}
