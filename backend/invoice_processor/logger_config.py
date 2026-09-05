"""发票日志的 DevBase 兼容入口。"""

from __future__ import annotations

from pathlib import Path

from devbase.logger_config import setup_logging as _setup_logging


def setup_logging(*, base_dir: str | Path | None = None) -> str:
    """Configure the root logger with the invoice-specific filename."""
    return str(
        _setup_logging(
            log_name="invoice.log",
            base_dir=base_dir,
            logger_name=None,
        )
    )


__all__ = ["setup_logging"]
