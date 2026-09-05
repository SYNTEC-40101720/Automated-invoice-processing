"""Generic native functions exposed to the pywebview frontend."""

from __future__ import annotations

import os
import platform as platform_module
import sys
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Any

from devbase import __version__


DirectoryPicker = Callable[[str], str | None]
DirectoryOpener = Callable[[Path], None]
PathChecker = Callable[[Path], bool]


def _default_directory_picker(title: str) -> str | None:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    try:
        return filedialog.askdirectory(title=title) or None
    finally:
        root.destroy()


def _default_directory_opener(path: Path) -> None:
    if os.name == "nt":
        os.startfile(str(path))
        return
    webbrowser.open(path.resolve().as_uri())


class NativeBridge:
    """Small, business-neutral API exposed as ``window.pywebview.api``."""

    def __init__(
        self,
        *,
        directory_picker: DirectoryPicker | None = None,
        directory_opener: DirectoryOpener | None = None,
        platform_name: str | None = None,
    ) -> None:
        self._directory_picker = directory_picker or _default_directory_picker
        self._directory_opener = directory_opener or _default_directory_opener
        self._platform_name = platform_name or sys.platform

    def select_directory(self, title: str = "选择文件夹") -> str | None:
        """Open the native folder picker and return the selected path."""
        return self._directory_picker(title)

    def open_directory(
        self,
        path: str,
        checker: PathChecker | None = None,
    ) -> bool:
        """Open an existing directory after optional validation."""
        directory = Path(path).expanduser()
        if not directory.is_dir():
            return False
        if checker is not None and not checker(directory):
            return False
        self._directory_opener(directory)
        return True

    def get_runtime_info(self) -> dict[str, Any]:
        """Return JSON-serializable information for the status/settings UI."""
        executable = Path(sys.executable).resolve()
        return {
            "app_version": __version__,
            "platform": self._platform_name,
            "platform_release": platform_module.release(),
            "python_version": platform_module.python_version(),
            "executable": str(executable),
            "frozen": bool(getattr(sys, "frozen", False)),
            "app_dir": str(executable.parent),
        }


__all__ = ["NativeBridge"]
