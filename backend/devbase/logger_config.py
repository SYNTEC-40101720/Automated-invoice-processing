"""Application logging configuration for desktop/PyInstaller environments.

Ensures the logs directory exists, rotates log files at 1 MB (5 backups), and
is safe to call multiple times without duplicating handlers.

PyInstaller frozen vs. development mode paths are handled transparently: when
running as a frozen bundle (``sys.frozen``), ``logs/`` is resolved relative to
the executable; otherwise it is relative to the project root.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def _resolve_base_dir() -> Path:
    """Resolve the application base directory for log placement."""
    if getattr(sys, "frozen", False):
        # PyInstaller bundled mode: use executable directory
        return Path(sys.executable).resolve().parent
    # Development mode: use project root (parent of backend/)
    return Path(__file__).resolve().parent.parent.parent


def _ensure_logs_dir(base_dir: Path | None = None) -> Path:
    """Ensure the logs/ directory exists and return its path."""
    if base_dir is None:
        base_dir = _resolve_base_dir()
    logs_dir = base_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def _already_configured(
    logger: logging.Logger,
    log_file_path: Path,
) -> bool:
    """Check if the logger already has a RotatingFileHandler for this file."""
    for handler in logger.handlers:
        if (
            isinstance(handler, RotatingFileHandler)
            and Path(handler.baseFilename).resolve()
            == log_file_path.resolve()
        ):
            return True
    return False


def setup_logging(
    log_name: str = "app.log",
    *,
    level: int = logging.INFO,
    base_dir: str | Path | None = None,
    logger_name: str | None = "devbase",
) -> Path:
    """Configure rotating file logging.

    Args:
        log_name: name of the log file inside ``logs/``.
        level: log level (default: ``logging.INFO``).
        base_dir: override the base directory; defaults to the PyInstaller
            or project root.  Useful for tests.
        logger_name: logger to configure; ``None`` configures the root logger.

    Returns:
        The resolved path to the log file.
    """
    if base_dir is not None:
        base_dir = Path(base_dir)
    logs_dir = _ensure_logs_dir(base_dir)
    log_file_path = logs_dir / log_name

    logger = logging.getLogger(logger_name)
    logger.setLevel(level)

    if _already_configured(logger, log_file_path):
        return log_file_path

    handler = RotatingFileHandler(
        log_file_path,
        maxBytes=1024 * 1024,  # 1 MB
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(handler)
    logger.propagate = False
    return log_file_path


__all__ = ["setup_logging"]
