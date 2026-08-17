"""SYNTEC 电子票据处理系统 Web 桌面入口。"""

from src.desktop.launcher import run_desktop
from src.logger_config import setup_logging


def main() -> None:
    setup_logging()
    run_desktop()


if __name__ == '__main__':
    main()
