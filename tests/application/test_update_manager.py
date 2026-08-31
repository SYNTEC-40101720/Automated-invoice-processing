"""桌面更新编排测试。"""

from __future__ import annotations

import shutil
import sys
import threading
from pathlib import Path

from src.application.update_checker import StagedUpdate, UpdateResult
from src.desktop import update_manager
from src.desktop.update_manager import DesktopUpdateManager


def test_apply_downloads_and_launches_standalone_helper(tmp_path, monkeypatch):
    target_dir = tmp_path / 'installed'
    target_dir.mkdir()
    executable = target_dir / 'SYNTEC-电子票据处理系统.exe'
    executable.write_bytes(b'old')
    helper = target_dir / 'SYNTEC-电子票据更新器.exe'
    helper.write_bytes(b'helper')
    staging_dir = tmp_path / 'staging'
    package_dir = staging_dir / 'package'
    package_dir.mkdir(parents=True)
    (package_dir / 'SYNTEC-电子票据处理系统.exe').write_bytes(b'new')
    result = UpdateResult(
        current_version='7.0.4',
        checked=True,
        available=True,
        latest_version='7.0.5',
        asset_name='SYNTEC-电子票据处理系统-v7.0.5.zip',
        asset_url='https://github.com/SYNTEC-40101720/Automated-invoice-processing/releases/download/v7.0.5/SYNTEC.zip',
    )
    launched: list[tuple[list[str], dict]] = []
    launch_finished = threading.Event()
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(update_manager, 'check_for_update', lambda _version: result)
    monkeypatch.setattr(
        update_manager,
        'stage_update',
        lambda *_args, **_kwargs: StagedUpdate(staging_dir, package_dir),
    )
    monkeypatch.setattr(
        update_manager.subprocess,
        'Popen',
        lambda command, **kwargs: (
            launched.append((command, kwargs)),
            launch_finished.set(),
        )[0],
    )

    manager = DesktopUpdateManager(executable=executable, can_update=lambda: True)
    response = manager.apply('7.0.4')

    assert response.status == 'started'
    assert response.latest_version == '7.0.5'
    assert launch_finished.wait(timeout=1)
    assert launched
    assert manager.progress().status == 'starting'
    assert launched[0][0][0].endswith('SYNTEC-电子票据更新器.exe')
    assert '--source-dir' in launched[0][0]
    assert '--target-dir' in launched[0][0]
    assert '--pid' in launched[0][0]
    helper_copy = Path(launched[0][0][0])
    shutil.rmtree(helper_copy.parent, ignore_errors=True)


def test_apply_does_not_interrupt_running_job(tmp_path, monkeypatch):
    target_dir = tmp_path / 'installed'
    target_dir.mkdir()
    executable = target_dir / 'SYNTEC-电子票据处理系统.exe'
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    manager = DesktopUpdateManager(executable=executable, can_update=lambda: False)

    response = manager.apply('7.0.4')

    assert response.status == 'busy'
    assert '任务' in response.message
