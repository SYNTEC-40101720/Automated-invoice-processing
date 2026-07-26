"""电子票据处理系统入口

墨韵 (Atelier) 风格界面 (PySide6)
"""
import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from src.logger_config import setup_logging
from src.ui.app import InvoiceApp


def _resource_path(relative: str) -> str:
    """定位资源文件路径（兼容 PyInstaller 打包后场景）"""
    if getattr(sys, 'frozen', False):
        # 打包后：资源在 _MEIPASS 临时目录
        base = sys._MEIPASS  # type: ignore[attr-defined]
    else:
        # 开发模式：相对脚本所在目录
        base = os.path.dirname(os.path.abspath(sys.argv[0]))
    return os.path.join(base, relative)


def main():
    # 初始化日志：固定位置 + 轮转（GUI 模式下 stderr 不可见，落盘便于问题排查）
    setup_logging()

    # ── High‑DPI 适配（必须在 QApplication 创建之前设置）──
    # Qt6 默认启用 AA_EnableHighDpiScaling，无需手动设置。
    # 显式指定缩放因子舍入策略：PassThrough 允许分数缩放（125%/150%/175%），
    # Qt6 内部使用浮点坐标渲染，避免整数舍入造成的模糊或 1px 偏移。
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("SYNTEC 电子票据处理系统")

    # 设置应用图标（任务栏 + 窗口标题栏）
    icon_path = _resource_path('logo.ico')
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    window = InvoiceApp()
    window.show()

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
