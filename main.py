"""电子票据处理系统入口

Material Design 风格界面（Tkinter + sv_ttk）
"""
import logging
from tkinter import Tk

from src.ui.app import InvoiceApp


def main():
    # 初始化日志：GUI 模式下 stderr 不可见，落盘便于问题排查
    logging.basicConfig(
        level=logging.WARNING,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler('invoice_processor.log', encoding='utf-8'),
        ],
    )

    root = Tk()
    # 设置 Windows 逐显示器 DPI 感知（PROCESS_PER_MONITOR_DPI_AWARE = 2）
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
    InvoiceApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()
