"""pywebview 原生能力桥接。"""

from __future__ import annotations

import os
import sys
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog

from devbase.desktop.native_bridge import NativeBridge as DevBaseNativeBridge

from ..version import __version__


class NativeBridge(DevBaseNativeBridge):
    """只提供文件选择和打开目录，不承载业务编排。"""

    def __init__(self, directory_checker: Callable[[str], bool] | None = None):
        super().__init__(platform_name=sys.platform)
        self._directory_checker = directory_checker
        self._selected_log_path: Path | None = None

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
            selected = filedialog.asksaveasfilename(
                title='导出处理日志',
                initialfile=default_name,
                defaultextension='.txt',
                filetypes=[('文本文件', '*.txt'), ('所有文件', '*.*')],
            ) or ''
            self._selected_log_path = (
                Path(selected).expanduser().resolve() if selected else None
            )
            return selected
        finally:
            root.destroy()

    def write_log(self, content: str) -> bool:
        target = self._selected_log_path
        self._selected_log_path = None
        if target is None or target.is_dir():
            return False
        try:
            target.write_text(content, encoding='utf-8')
        except OSError:
            return False
        return True

    def open_directory(self, path: str) -> bool:
        checker = None
        if self._directory_checker is not None:
            original = self._directory_checker

            def checker(target) -> bool:  # noqa: F811
                return original(str(target))

        return super().open_directory(path, checker=checker)

    def print_pdf(self, path: str, copies: int = 1) -> bool:
        """用 Windows 默认打印机静默打印 PDF（ShellExecute 'printto'）。

        域控环境无需额外驱动配置；打印机未配置/路径无效返回 False，
        不抛异常（前端据此提示）。
        """
        if os.name != 'nt':
            return False
        target = Path(path).expanduser()
        if not target.is_file():
            return False
        try:
            copies = max(1, int(copies))
        except (TypeError, ValueError):
            copies = 1

        import ctypes  # noqa: PLC0415 - 仅 Windows 打印路径需要

        shell32 = ctypes.windll.shell32  # type: ignore[attr-defined]
        shell32.ShellExecuteW.restype = ctypes.c_void_p

        try:
            for _ in range(copies):
                # lpParameters = "打印机名"；verb='printto' 由关联的 PDF
                # 处理器（Edge/Acrobat）接管静默打印，无需第三方依赖。
                code = shell32.ShellExecuteW(
                    0, 'printto', str(target),
                    f'"{_default_printer_name()}"',
                    '.', 0,
                )
                if code is None or code <= 32:  # SE_ERR_* 均 <=32
                    return False
            return True
        except Exception:
            return False


def _default_printer_name() -> str:
    """读默认打印机名（winspool GetDefaultPrinterW，两段式调用）。"""
    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415

    winspool = ctypes.WinDLL('winspool.drv')
    winspool.GetDefaultPrinterW.restype = wintypes.BOOL
    winspool.GetDefaultPrinterW.argtypes = [wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    size = wintypes.DWORD(0)
    winspool.GetDefaultPrinterW(None, ctypes.byref(size))
    if size.value == 0:
        return ''
    buf = ctypes.create_unicode_buffer(size.value)
    if not winspool.GetDefaultPrinterW(buf, ctypes.byref(size)):
        return ''
    return buf.value

    def get_runtime_info(self) -> dict[str, str | bool]:
        return {
            **super().get_runtime_info(),
            'platform': sys.platform,
            'webview2': os.name == 'nt',
            'version': __version__,
        }
