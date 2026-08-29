"""发布归档脚本测试。"""

from __future__ import annotations

import zipfile

import build_syntec


def test_create_release_archive_contains_complete_install_directory(
    tmp_path,
    monkeypatch,
):
    dist_dir = tmp_path / 'dist'
    package_dir = dist_dir / build_syntec.APP_NAME
    (package_dir / '_internal').mkdir(parents=True)
    (package_dir / f'{build_syntec.APP_NAME}.exe').write_bytes(b'app')
    (package_dir / f'{build_syntec.UPDATER_NAME}.exe').write_bytes(b'updater')
    (package_dir / '_internal' / 'python3.dll').write_bytes(b'python')
    monkeypatch.setattr(build_syntec, 'DIST_DIR', dist_dir)

    archive_path = build_syntec.create_release_archive()

    assert archive_path.name == (
        f'{build_syntec.RELEASE_ARCHIVE_PREFIX}-v{build_syntec.__version__}.zip'
    )
    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
    assert f'{build_syntec.APP_NAME}/{build_syntec.APP_NAME}.exe' in names
    assert f'{build_syntec.APP_NAME}/{build_syntec.UPDATER_NAME}.exe' in names
    assert (
        f'{build_syntec.APP_NAME}/_internal/python3.dll' in names
    )
