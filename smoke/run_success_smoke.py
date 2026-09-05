"""本地成功路径端到端冒烟：stub 主程序写入确认文件。"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
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
        str(ROOT / 'smoke' / 'stub_app.py'),
    ])


def prepare_v2(v1: Path, v2: Path) -> None:
    v2.mkdir(parents=True)
    for child in v1.iterdir():
        if child.is_dir():
            shutil.copytree(child, v2 / child.name)
        else:
            shutil.copy2(child, v2 / child.name)
    (v2 / f'{APP_NAME}.exe.marker').write_text('new-version', encoding='utf-8')


def stop_started_application(v1: Path) -> None:
    pid_file = v1 / '.smoke-child.pid'
    if not pid_file.exists():
        return
    pid = int(pid_file.read_text(encoding='ascii'))
    subprocess.run(
        ['taskkill', '/PID', str(pid), '/T', '/F'],
        capture_output=True,
        check=False,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix='syntec-update-success-') as temp_dir:
        smoke_root = Path(temp_dir)
        v1 = smoke_root / 'v1' / APP_NAME
        v2 = smoke_root / 'v2'
        staging = smoke_root / 'staging'

        package(smoke_root)
        prepare_v2(v1, v2)
        # 等待 Windows 扫描/文件锁释放
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
        stop_started_application(v1)

        if result.returncode != 0:
            print('FAIL: helper exited with', result.returncode)
            if (staging / 'update.log').exists():
                print((staging / 'update.log').read_text(encoding='utf-8'))
            return 1

        marker = v1 / f'{APP_NAME}.exe.marker'
        if marker.exists():
            print('SUCCESS: new version marker present')
        else:
            print('FAIL: new version marker missing')
            return 1

        if staging.exists():
            print('FAIL: staging directory should have been cleaned')
            return 1

        print('SUCCESS: update committed and staging cleaned')
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
