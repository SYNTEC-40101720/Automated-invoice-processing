"""发布归档脚本测试。"""

from __future__ import annotations

import zipfile

import build_syntec
import bump_version


def test_build_script_does_not_mutate_version_sources():
    """打包脚本必须零副作用：不存在修改版本文件的入口。"""
    assert not hasattr(build_syntec, 'prepare_release_version')
    assert not hasattr(build_syntec, 'update_version_files')
    assert not hasattr(build_syntec, 'bump_patch_version')
    assert not hasattr(build_syntec, 'remote_tag_exists')


def test_validate_release_not_published_exits_on_existing_tag(monkeypatch):
    monkeypatch.setattr(build_syntec, 'version_tag_exists', lambda v: True)

    try:
        build_syntec.validate_release_not_published('7.2.1')
    except SystemExit as exc:
        message = str(exc.code)
        assert exc.code not in (None, 0)
        assert '已发布' in message
        assert 'bump_version.py' in message
    else:
        raise AssertionError('已发布的版本必须触发 SystemExit')


def test_validate_release_not_published_passes_on_new_version(
    monkeypatch, capsys,
):
    monkeypatch.setattr(build_syntec, 'version_tag_exists', lambda v: False)
    build_syntec.validate_release_not_published('7.3.0')
    assert '尚未发布' in capsys.readouterr().out


def test_version_tag_exists_queries_local_then_remote(monkeypatch):
    """占用检查先查本地 tag，再查远端；两者命中其一即视为占用。"""
    calls = []

    class Result:
        def __init__(self, returncode: int, stdout: str = ''):
            self.returncode = returncode
            self.stdout = stdout

    def fake_run(cmd, cwd, capture_output, text, timeout):  # noqa: ARG001
        calls.append(cmd)
        # 本地 rev-parse 未命中 -> 走远端 ls-remote 命中
        if cmd[1] == 'rev-parse':
            return Result(1)
        return Result(0, 'abc123\trefs/tags/v9.9.9\n')

    monkeypatch.setattr(bump_version.subprocess, 'run', fake_run)
    assert bump_version.version_tag_exists('9.9.9')
    assert calls[0][:3] == ['git', 'rev-parse', '-q']
    assert calls[1][:3] == ['git', 'ls-remote', '--tags']


def test_version_tag_exists_true_on_local_tag_only(monkeypatch):
    """本地已有 tag 即视为占用，不再查询远端。"""

    class Result:
        returncode = 0
        stdout = ''

    def fake_run(cmd, cwd, capture_output, text, timeout):  # noqa: ARG001
        return Result()

    monkeypatch.setattr(bump_version.subprocess, 'run', fake_run)
    assert bump_version.version_tag_exists('9.9.9')


def test_version_tag_exists_false_when_not_found(monkeypatch):
    class Result:
        def __init__(self, returncode: int):
            self.returncode = returncode
            self.stdout = ''

    def fake_run(cmd, cwd, capture_output, text, timeout):  # noqa: ARG001
        # 本地未命中、远端也未命中
        return Result(1)

    monkeypatch.setattr(bump_version.subprocess, 'run', fake_run)
    assert not bump_version.version_tag_exists('0.0.1')


def test_version_tag_exists_false_on_subprocess_error(monkeypatch):
    def raise_timeout(*args, **kwargs):
        raise bump_version.subprocess.SubprocessError('network down')

    monkeypatch.setattr(bump_version.subprocess, 'run', raise_timeout)
    assert not bump_version.version_tag_exists('9.9.9')


def test_create_release_archive_contains_complete_install_directory(
    tmp_path,
    monkeypatch,
):
    dist_dir = tmp_path / 'dist'
    package_dir = dist_dir / build_syntec.APP_NAME
    (package_dir / '_internal').mkdir(parents=True)
    (package_dir / f'{build_syntec.APP_NAME}.exe').write_bytes(b'app')
    (package_dir / '_internal' / 'python3.dll').write_bytes(b'python')
    monkeypatch.setattr(build_syntec, 'DIST_DIR', dist_dir)

    archive_path = build_syntec.create_release_archive()

    assert archive_path.name == (
        f'{build_syntec.RELEASE_ARCHIVE_PREFIX}-v{build_syntec.__version__}.zip'
    )
    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
    assert f'{build_syntec.APP_NAME}/{build_syntec.APP_NAME}.exe' in names
    assert (
        f'{build_syntec.APP_NAME}/_internal/python3.dll' in names
    )
