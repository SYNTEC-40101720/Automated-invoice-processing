"""独立更新器的目录替换测试。"""

from __future__ import annotations

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

    def start_application(_target_dir):
        assert not (target_dir / 'logs' / 'update.log').exists()
        assert (cleanup_dir / 'update.log').is_file()

    monkeypatch.setattr(update_helper, '_start_application', start_application)

    update_helper.run_update(source_dir, target_dir, cleanup_dir, pid=123)

    assert (target_dir / MAIN_EXECUTABLE_NAME).read_bytes() == b'new'
    assert not cleanup_dir.exists()
