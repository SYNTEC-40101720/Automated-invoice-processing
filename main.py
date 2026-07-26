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
    # 注: 不使用 ctypes 调用 Windows API（SYNTEC 域控环境禁止）。
    # Tkinter 在 Python 3.8+ 已默认启用系统 DPI 感知，由 sv_ttk 主题保证显示清晰。
    InvoiceApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()
