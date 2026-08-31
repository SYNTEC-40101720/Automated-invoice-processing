"""独立更新器的目录替换测试。"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.desktop.update_helper import (
    MAIN_EXECUTABLE_NAME,
    replace_install,
    wait_for_process_exit,
)


def test_replace_install_preserves_user_data(tmp_path):
    target_dir = tmp_path / 'installed'
    source_dir = tmp_path / 'staged'
    backup_dir = tmp_path / 'backup'
    (target_dir / 'logs').mkdir(parents=True)
    (target_dir / '发票收件箱').mkdir()
    (target_dir / MAIN_EXECUTABLE_NAME).write_bytes(b'old')
    (target_dir / 'config.ini').write_text('old-config', encoding='utf-8')
    (target_dir / 'logs' / 'invoice.log').write_text('old-log', encoding='utf-8')
    (target_dir / '发票收件箱' / 'invoice.pdf').write_bytes(b'old-pdf')
    source_dir.mkdir()
    (source_dir / MAIN_EXECUTABLE_NAME).write_bytes(b'new')

    old_dir = replace_install(source_dir, target_dir, backup_dir=backup_dir)

    assert old_dir == backup_dir.resolve()
    assert (target_dir / MAIN_EXECUTABLE_NAME).read_bytes() == b'new'
    assert (target_dir / 'config.ini').read_text(encoding='utf-8') == 'old-config'
    assert (
        target_dir / 'logs' / 'invoice.log'
    ).read_text(encoding='utf-8') == 'old-log'
    assert (target_dir / '发票收件箱' / 'invoice.pdf').read_bytes() == b'old-pdf'
    assert old_dir.is_dir()


def test_replace_install_keeps_old_install_when_initial_move_fails(
    tmp_path, monkeypatch
):
    target_dir = tmp_path / 'installed'
    source_dir = tmp_path / 'staged'
    backup_dir = tmp_path / 'backup'
    (target_dir / 'logs').mkdir(parents=True)
    (target_dir / '发票收件箱').mkdir()
    (target_dir / MAIN_EXECUTABLE_NAME).write_bytes(b'old')
    (target_dir / 'config.ini').write_text('old-config', encoding='utf-8')
    (target_dir / 'logs' / 'invoice.log').write_text('old-log', encoding='utf-8')
    (target_dir / '发票收件箱' / 'invoice.pdf').write_bytes(b'old-pdf')
    source_dir.mkdir()
    (source_dir / MAIN_EXECUTABLE_NAME).write_bytes(b'new')

    original_rename = Path.rename

    def fail_initial_rename(path, destination):
        if path == target_dir.resolve() and destination == backup_dir.resolve():
            raise OSError('cannot move old installation')
        return original_rename(path, destination)

    monkeypatch.setattr(Path, 'rename', fail_initial_rename)

    with pytest.raises(OSError, match='cannot move old installation'):
        replace_install(source_dir, target_dir, backup_dir=backup_dir)

    assert target_dir.is_dir()
    assert (target_dir / MAIN_EXECUTABLE_NAME).read_bytes() == b'old'
    assert (target_dir / 'config.ini').read_text(encoding='utf-8') == 'old-config'
    assert (
        target_dir / 'logs' / 'invoice.log'
    ).read_text(encoding='utf-8') == 'old-log'
    assert (target_dir / '发票收件箱' / 'invoice.pdf').read_bytes() == b'old-pdf'
    assert source_dir.is_dir()
    assert (source_dir / MAIN_EXECUTABLE_NAME).read_bytes() == b'new'


def test_replace_install_restores_old_install_when_new_move_fails(
    tmp_path, monkeypatch
):
    target_dir = tmp_path / 'installed'
    source_dir = tmp_path / 'staged'
    backup_dir = tmp_path / 'backup'
    target_dir.mkdir()
    (target_dir / MAIN_EXECUTABLE_NAME).write_bytes(b'old')
    (target_dir / 'config.ini').write_text('old-config', encoding='utf-8')
    source_dir.mkdir()
    (source_dir / MAIN_EXECUTABLE_NAME).write_bytes(b'new')

    original_rename = Path.rename

    def fail_new_rename(path, destination):
        if path == source_dir.resolve() and destination == target_dir.resolve():
            raise OSError('cannot move new installation')
        return original_rename(path, destination)

    monkeypatch.setattr(Path, 'rename', fail_new_rename)

    with pytest.raises(OSError, match='cannot move new installation'):
        replace_install(source_dir, target_dir, backup_dir=backup_dir)

    assert target_dir.is_dir()
    assert (target_dir / MAIN_EXECUTABLE_NAME).read_bytes() == b'old'
    assert (target_dir / 'config.ini').read_text(encoding='utf-8') == 'old-config'
    assert source_dir.is_dir()
    assert (source_dir / MAIN_EXECUTABLE_NAME).read_bytes() == b'new'
    assert not backup_dir.exists()


def test_wait_for_process_exit_stops_after_process_disappears(monkeypatch):
    states = iter((True, False))
    monkeypatch.setattr(
        'src.desktop.update_helper.PROCESS_POLL_INTERVAL',
        0,
    )

    wait_for_process_exit(
        123,
        timeout=1,
        process_checker=lambda _pid: next(states),
    )


def test_run_update_keeps_log_outside_install_directory(tmp_path, monkeypatch):
    from src.desktop import update_helper

    target_dir = tmp_path / 'installed'
    cleanup_dir = tmp_path / 'staging'
    source_dir = cleanup_dir / 'package'
    (target_dir / 'logs').mkdir(parents=True)
    (target_dir / MAIN_EXECUTABLE_NAME).write_bytes(b'old')
    source_dir.mkdir(parents=True)
    (source_dir / MAIN_EXECUTABLE_NAME).write_bytes(b'new')

    monkeypatch.setattr(update_helper, 'wait_for_process_exit', lambda _pid: None)

    class FakeProcess:
        def poll(self):
            return None

    def start_application(_target_dir, ready_file):
        assert not (target_dir / 'logs' / 'update.log').exists()
        assert (cleanup_dir / 'update.log').is_file()
        ready_file.touch()
        return FakeProcess()

    monkeypatch.setattr(update_helper, '_start_application', start_application)

    update_helper.run_update(source_dir, target_dir, cleanup_dir, pid=123)

    assert (target_dir / MAIN_EXECUTABLE_NAME).read_bytes() == b'new'
    assert not (cleanup_dir / 'old-install').exists()
    assert not cleanup_dir.exists()


def test_run_update_commits_when_ready_file_exists_before_process_poll(
    tmp_path, monkeypatch
):
    from src.desktop import update_helper

    target_dir = tmp_path / 'installed'
    cleanup_dir = tmp_path / 'staging'
    source_dir = cleanup_dir / 'package'
    target_dir.mkdir()
    (target_dir / MAIN_EXECUTABLE_NAME).write_bytes(b'old')
    source_dir.mkdir(parents=True)
    (source_dir / MAIN_EXECUTABLE_NAME).write_bytes(b'new')

    class FakeProcess:
        def poll(self):
            return 0

    def start_application(_target_dir, ready_file):
        ready_file.touch()
        return FakeProcess()

    monkeypatch.setattr(update_helper, 'wait_for_process_exit', lambda _pid: None)
    monkeypatch.setattr(update_helper, '_start_application', start_application)

    update_helper.run_update(source_dir, target_dir, cleanup_dir, pid=123)

    assert (target_dir / MAIN_EXECUTABLE_NAME).read_bytes() == b'new'
    assert not cleanup_dir.exists()


def test_run_update_rolls_back_after_startup_confirmation_timeout(
    tmp_path, monkeypatch
):
    from src.desktop import update_helper

    target_dir = tmp_path / 'installed'
    cleanup_dir = tmp_path / 'staging'
    source_dir = cleanup_dir / 'package'
    target_dir.mkdir()
    (target_dir / MAIN_EXECUTABLE_NAME).write_bytes(b'old')
    (target_dir / 'config.ini').write_text('old-config', encoding='utf-8')
    source_dir.mkdir(parents=True)
    (source_dir / MAIN_EXECUTABLE_NAME).write_bytes(b'new')

    class FakeProcess:
        def __init__(self):
            self.terminated = False
            self.waited = False

        def poll(self):
            return None if not self.terminated else -15

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            self.waited = True
            return -15

    process = FakeProcess()
    monkeypatch.setattr(update_helper, 'wait_for_process_exit', lambda _pid: None)
    monkeypatch.setattr(
        update_helper,
        '_start_application',
        lambda _target_dir, _ready_file: process,
    )
    monkeypatch.setattr(update_helper, 'STARTUP_READY_TIMEOUT', 0)
    monkeypatch.setattr(update_helper, 'STARTUP_READY_POLL_INTERVAL', 0)

    with pytest.raises(RuntimeError, match='启动确认超时'):
        update_helper.run_update(source_dir, target_dir, cleanup_dir, pid=123)

    assert process.terminated is True
    assert process.waited is True
    assert (target_dir / MAIN_EXECUTABLE_NAME).read_bytes() == b'old'
    assert (target_dir / 'config.ini').read_text(encoding='utf-8') == 'old-config'
    assert not (target_dir / 'startup-ready').exists()
    assert (cleanup_dir / 'update.log').is_file()
    assert '自动更新失败' in (cleanup_dir / 'update.log').read_text(encoding='utf-8')


def test_run_update_kills_process_before_rollback_after_wait_timeout(
    tmp_path, monkeypatch
):
    from src.desktop import update_helper

    target_dir = tmp_path / 'installed'
    cleanup_dir = tmp_path / 'staging'
    source_dir = cleanup_dir / 'package'
    target_dir.mkdir()
    (target_dir / MAIN_EXECUTABLE_NAME).write_bytes(b'old')
    source_dir.mkdir(parents=True)
    (source_dir / MAIN_EXECUTABLE_NAME).write_bytes(b'new')
    events = []

    class FakeProcess:
        def __init__(self):
            self.wait_count = 0
            self.running = True

        def poll(self):
            return None if self.running else -9

        def terminate(self):
            events.append('terminate')

        def kill(self):
            events.append('kill')
            self.running = False

        def wait(self, timeout=None):
            self.wait_count += 1
            events.append(f'wait-{self.wait_count}')
            if self.wait_count == 1:
                raise subprocess.TimeoutExpired('fake-process', timeout)
            return -9

    process = FakeProcess()
    monkeypatch.setattr(update_helper, 'wait_for_process_exit', lambda _pid: None)
    monkeypatch.setattr(
        update_helper,
        '_start_application',
        lambda _target_dir, _ready_file: process,
    )
    monkeypatch.setattr(update_helper, 'STARTUP_READY_TIMEOUT', 0)
    monkeypatch.setattr(update_helper, 'STARTUP_READY_POLL_INTERVAL', 0)

    original_rollback = update_helper._rollback_install

    def rollback_and_record(old_dir, target_dir, update_error):
        events.append('rollback')
        return original_rollback(old_dir, target_dir, update_error)

    monkeypatch.setattr(update_helper, '_rollback_install', rollback_and_record)

    with pytest.raises(RuntimeError, match='启动确认超时'):
        update_helper.run_update(source_dir, target_dir, cleanup_dir, pid=123)

    assert process.wait_count == 2
    assert events.index('kill') < events.index('wait-2')
    assert events.index('kill') < events.index('rollback')
    assert (target_dir / MAIN_EXECUTABLE_NAME).read_bytes() == b'old'
    assert not (cleanup_dir / 'old-install').exists()


def test_run_update_rolls_back_when_new_process_exits_early(tmp_path, monkeypatch):
    from src.desktop import update_helper

    target_dir = tmp_path / 'installed'
    cleanup_dir = tmp_path / 'staging'
    source_dir = cleanup_dir / 'package'
    target_dir.mkdir()
    (target_dir / MAIN_EXECUTABLE_NAME).write_bytes(b'old')
    source_dir.mkdir(parents=True)
    (source_dir / MAIN_EXECUTABLE_NAME).write_bytes(b'new')

    class FakeProcess:
        def __init__(self):
            self.waited = False

        def poll(self):
            return 1

        def terminate(self):
            raise AssertionError('已退出的进程不应再次 terminate')

        def wait(self, timeout=None):
            self.waited = True
            return 1

    process = FakeProcess()
    monkeypatch.setattr(update_helper, 'wait_for_process_exit', lambda _pid: None)
    monkeypatch.setattr(
        update_helper,
        '_start_application',
        lambda _target_dir, _ready_file: process,
    )
    monkeypatch.setattr(update_helper, 'STARTUP_READY_POLL_INTERVAL', 0)

    with pytest.raises(RuntimeError, match='启动确认前退出'):
        update_helper.run_update(source_dir, target_dir, cleanup_dir, pid=123)

    assert process.waited is True
    assert (target_dir / MAIN_EXECUTABLE_NAME).read_bytes() == b'old'
    assert (cleanup_dir / 'update.log').is_file()
