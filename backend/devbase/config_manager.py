"""Small locked INI configuration manager for local desktop tools."""

from __future__ import annotations

import configparser
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Iterator, Mapping

from .config import DEFAULT_CONFIG


class ConfigLockTimeoutError(TimeoutError):
    """Raised when another process holds the configuration lock too long."""


@contextmanager
def _file_lock(path: Path, timeout: float) -> Iterator[None]:
    lock_path = path.with_name(f"{path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    handle = lock_path.open("a+b")
    try:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        while True:
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (BlockingIOError, OSError) as error:
                if time.monotonic() - started >= timeout:
                    raise ConfigLockTimeoutError(
                        f"could not lock configuration: {path}"
                    ) from error
                time.sleep(0.01)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


class ConfigManager:
    """Read and write a generic, process-safe INI configuration file."""

    def __init__(
        self,
        path: str | Path,
        *,
        defaults: Mapping[str, Mapping[str, str]] | None = None,
        lock_timeout: float = 5.0,
    ) -> None:
        if lock_timeout < 0:
            raise ValueError("lock_timeout must not be negative")
        self.path = Path(path)
        self._defaults = {
            section: dict(options)
            for section, options in (defaults or DEFAULT_CONFIG).items()
        }
        self._lock_timeout = lock_timeout
        self._thread_lock = RLock()
        self._parser = self._new_parser()
        self.reload_config()

    def get(
        self,
        section: str,
        option: str,
        fallback: str | None = None,
    ) -> str | None:
        with self._thread_lock:
            return self._parser.get(section, option, fallback=fallback)

    def set(self, section: str, option: str, value: object) -> None:
        with self._guard():
            parser = self._load_from_disk()
            if not parser.has_section(section):
                parser.add_section(section)
            parser.set(section, option, str(value))
            self._write_parser(parser)
            self._parser = parser

    def reload_config(self) -> "ConfigManager":
        """Reload from disk and create the [app] template when absent."""
        with self._guard():
            parser = self._load_from_disk()
            self._write_parser(parser)
            self._parser = parser
        return self

    def save(self) -> None:
        with self._guard():
            self._write_parser(self._parser)

    def sections(self) -> list[str]:
        with self._thread_lock:
            return self._parser.sections()

    def as_dict(self) -> dict[str, dict[str, str]]:
        with self._thread_lock:
            return {
                section: dict(self._parser.items(section))
                for section in self._parser.sections()
            }

    @property
    def config_path(self) -> Path:
        return self.path

    def _new_parser(self) -> configparser.ConfigParser:
        parser = configparser.ConfigParser(interpolation=None)
        for section, options in self._defaults.items():
            parser[section] = dict(options)
        return parser

    def _load_from_disk(self) -> configparser.ConfigParser:
        parser = self._new_parser()
        if self.path.is_file():
            parser.read(self.path, encoding="utf-8")
        return parser

    def _write_parser(self, parser: configparser.ConfigParser) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                parser.write(temporary)
                temporary.flush()
                os.fsync(temporary.fileno())
                temp_path = temporary.name
            os.replace(temp_path, self.path)
        finally:
            if temp_path is not None and os.path.exists(temp_path):
                os.unlink(temp_path)

    @contextmanager
    def _guard(self) -> Iterator[None]:
        with self._thread_lock:
            with _file_lock(self.path, self._lock_timeout):
                yield


__all__ = ["ConfigLockTimeoutError", "ConfigManager"]
