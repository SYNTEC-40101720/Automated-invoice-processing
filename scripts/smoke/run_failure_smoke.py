"""本地失败路径端到端冒烟：新版本不写确认文件，helper 应回滚。"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT_DIR = Path(__file__).resolve().parent
APP_NAME = 'SYNTEC-电子票据处理系统'


def run(cmd: list[str], *, cwd: Path = ROOT) -> None:
    print(f'▶ {" ".join(cmd)}')
    result = subprocess.run(cmd, cwd=str(cwd))
    if result.returncode != 0:
        raise SystemExit(f'命令失败: {cmd}')


def package(smoke_root: Path) -> None:
    v1_root = smoke_root / 'v1'
    run([
        sys.executable, '-m', 'PyInstaller',
        '--clean', '--noconfirm', '--onedir', '--windowed',
        '--name', APP_NAME,
        '--distpath', str(v1_root),
        '--workpath', str(smoke_root / 'build-smoke'),
        '--specpath', str(smoke_root),
        str(SCRIPT_DIR / 'stub_app_fail.py'),
    ])


def prepare_v2(v1: Path, v2: Path) -> None:
    v2.mkdir(parents=True)
    for child in v1.iterdir():
        if child.is_dir():
            shutil.copytree(child, v2 / child.name)
        else:
            shutil.copy2(child, v2 / child.name)
    (v2 / f'{APP_NAME}.exe.marker').write_text('new-version', encoding='utf-8')


def main() -> int:
    with tempfile.TemporaryDirectory(prefix='syntec-update-failure-') as temp_dir:
        smoke_root = Path(temp_dir)
        v1 = smoke_root / 'v1' / APP_NAME
        v2 = smoke_root / 'v2'
        staging = smoke_root / 'staging'

        package(smoke_root)
        prepare_v2(v1, v2)
        # 写入旧版标记，确认回滚后保留
        old_marker = v1 / 'old-version.txt'
        old_marker.write_text('old', encoding='utf-8')
        time.sleep(2)

        parent = subprocess.Popen(
            [sys.executable, '-c', 'import time; time.sleep(2)'],
        )
        try:
            result = subprocess.run([
                sys.executable, '-m', 'invoice_processor.desktop.update_helper',
                '--source-dir', str(v2),
                '--target-dir', str(v1),
                '--cleanup-dir', str(staging),
                '--pid', str(parent.pid),
            ], cwd=str(ROOT))
        finally:
            if parent.poll() is None:
                parent.terminate()
                parent.wait(timeout=5)

        if result.returncode == 0:
            print('FAIL: helper should have failed')
            return 1

        if not old_marker.exists() or old_marker.read_text(encoding='utf-8') != 'old':
            print('FAIL: old installation not restored')
            return 1

        new_marker = v1 / f'{APP_NAME}.exe.marker'
        if new_marker.exists():
            print('FAIL: new version marker should not be present after rollback')
            return 1

        log = staging / 'update.log'
        if not log.exists():
            print('FAIL: update log should be retained for diagnosis')
            return 1

        log_text = log.read_text(encoding='utf-8')
        if '自动更新失败' not in log_text:
            print('FAIL: update log should contain failure record')
            return 1

        print('SUCCESS: update rolled back and diagnostics preserved')
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
