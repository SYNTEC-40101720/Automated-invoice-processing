"""桌面启动器更新握手测试。"""

from __future__ import annotations

from invoice_processor.desktop import launcher
from invoice_processor.desktop.update_protocol import (
    UPDATE_READY_ENV_VAR,
    UPDATE_READY_FILENAME,
)


class FakeLoadedEvent:
    def __init__(self):
        self.handler = None

    def __iadd__(self, handler):
        self.handler = handler
        return self


class FakeWindow:
    def __init__(self):
        self.events = type('Events', (), {'loaded': FakeLoadedEvent()})()


def test_loaded_handler_creates_ready_file_for_valid_update_path(tmp_path, monkeypatch):
    ready_dir = tmp_path / '.syntec-update-123'
    ready_dir.mkdir()
    ready_path = ready_dir / UPDATE_READY_FILENAME
    monkeypatch.setenv(UPDATE_READY_ENV_VAR, str(ready_path))
    window = FakeWindow()

    resolved_path = launcher._resolve_startup_ready_file()
    launcher._attach_startup_ready_handler(window, resolved_path)

    assert window.events.loaded.handler is not None
    window.events.loaded.handler()
    assert ready_path.is_file()


def test_loaded_handler_does_not_overwrite_existing_ready_file(tmp_path):
    ready_dir = tmp_path / '.syntec-update-123'
    ready_dir.mkdir()
    ready_path = ready_dir / UPDATE_READY_FILENAME
    ready_path.write_text('diagnostic-content', encoding='utf-8')
    window = FakeWindow()

    launcher._attach_startup_ready_handler(window, ready_path)
    window.events.loaded.handler()

    assert ready_path.read_text(encoding='utf-8') == 'diagnostic-content'


def test_update_ready_path_requires_updater_directory_and_fixed_name(
    tmp_path, monkeypatch
):
    invalid_paths = (
        tmp_path / 'ordinary-directory' / UPDATE_READY_FILENAME,
        tmp_path / '.syntec-update-123' / 'wrong-name',
    )
    for invalid_path in invalid_paths:
        invalid_path.parent.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv(UPDATE_READY_ENV_VAR, str(invalid_path))
        assert launcher._resolve_startup_ready_file() is None
        assert not invalid_path.exists()


def test_update_ready_path_requires_environment_variable(tmp_path, monkeypatch):
    monkeypatch.delenv(UPDATE_READY_ENV_VAR, raising=False)

    assert launcher._resolve_startup_ready_file() is None