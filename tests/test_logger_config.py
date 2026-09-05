import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from invoice_processor.logger_config import setup_logging


def test_invoice_logger_uses_devbase_rotation(tmp_path: Path) -> None:
    log_path = Path(setup_logging(base_dir=tmp_path))
    root = logging.getLogger()
    handlers = [
        handler
        for handler in root.handlers
        if isinstance(handler, RotatingFileHandler)
        and Path(handler.baseFilename).resolve() == log_path.resolve()
    ]

    assert log_path.name == "invoice.log"
    assert len(handlers) == 1
    assert handlers[0].maxBytes == 1024 * 1024
    assert handlers[0].backupCount == 5

    logging.getLogger("invoice-test").info("invoice log entry")
    handlers[0].flush()
    assert "invoice log entry" in log_path.read_text(encoding="utf-8")

    for handler in handlers:
        root.removeHandler(handler)
        handler.close()
