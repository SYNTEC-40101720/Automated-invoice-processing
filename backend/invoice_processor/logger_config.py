"""日志配置：固定位置 + 轮转

日志文件位置：<程序目录>/logs/invoice.log
- 单文件 1MB，保留 5 个备份
- 级别 INFO
- 格式：%(asctime)s [%(levelname)s] %(message)s
"""
import logging
import logging.handlers
import os
import sys


def _get_program_dir() -> str:
    """定位程序所在目录（兼容 PyInstaller 打包后场景）"""
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包后，sys.executable 是 exe 路径
        return os.path.dirname(sys.executable)
    # 开发模式，sys.argv[0] 是脚本路径
    return os.path.dirname(os.path.abspath(sys.argv[0]))


def setup_logging() -> str:
    """配置全局日志：固定位置 + 轮转

    返回日志文件路径。
    """
    log_dir = os.path.join(_get_program_dir(), 'logs')
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, 'invoice.log')

    handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=1024 * 1024,  # 1MB
        backupCount=5,
        encoding='utf-8',
    )
    handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(message)s'
    ))

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # 避免重复添加 handler（多次调用 setup_logging 时）
    if not any(isinstance(h, logging.handlers.RotatingFileHandler)
               and getattr(h, 'baseFilename', '') == os.path.abspath(log_file)
               for h in root.handlers):
        root.addHandler(handler)

    return log_file
