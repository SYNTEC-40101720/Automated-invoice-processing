"""电子票据处理系统入口

Material Design 风格界面（Tkinter + sv_ttk）
"""
from tkinter import Tk

from src.ui.app import InvoiceApp


def main():
    root = Tk()
    # 尝试设置 Windows DPI 感知
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    InvoiceApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()
