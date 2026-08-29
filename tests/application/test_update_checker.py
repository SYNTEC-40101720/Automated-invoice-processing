"""GitHub 更新检查测试。"""

from __future__ import annotations

import hashlib
import io
import zipfile
from urllib.error import URLError

from src.application.update_checker import (
    GITHUB_API_URL,
    GITHUB_RELEASES_URL,
    MAIN_EXECUTABLE_NAME,
    UpdateError,
    UpdateResult,
    check_for_update,
    stage_update,
)


class FakeResponse:
    def __init__(self, payload: object):
        import json

        self._body = json.dumps(payload).encode('utf-8')

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self, _size=-1):
        return self._body


class RawResponse:
    def __init__(self, body: bytes):
        self._body = body
        self.headers = {'Content-Length': str(len(body))}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self, size=-1):
        if size < 0:
            body, self._body = self._body, b''
            return body
        body, self._body = self._body[:size], self._body[size:]
        return body


def test_check_for_update_detects_new_release():
    captured: dict[str, object] = {}

    def opener(request, timeout):
        captured['url'] = request.full_url
        captured['headers'] = request.headers
        captured['timeout'] = timeout
        return FakeResponse({
            'tag_name': 'v7.0.5',
            'html_url': (
                'https://github.com/SYNTEC-40101720/'
                'Automated-invoice-processing/releases/tag/v7.0.5'
            ),
        })

    result = check_for_update('7.0.4', opener=opener)

    assert result.checked is True
    assert result.available is True
    assert result.latest_version == '7.0.5'
    assert result.release_url is not None
    assert captured['url'] == GITHUB_API_URL
    assert captured['timeout'] == 3.0
    assert captured['headers']['Accept'] == 'application/vnd.github+json'


def test_check_for_update_selects_installable_zip_asset():
    result = check_for_update(
        '7.0.4',
        opener=lambda *_args, **_kwargs: FakeResponse({
            'tag_name': 'v7.0.5',
            'html_url': 'https://github.com/SYNTEC-40101720/Automated-invoice-processing/releases/tag/v7.0.5',
            'assets': [{
                'name': 'SYNTEC-电子票据处理系统-v7.0.5.zip',
                'browser_download_url': 'https://github.com/SYNTEC-40101720/Automated-invoice-processing/releases/download/v7.0.5/SYNTEC.zip',
                'digest': 'sha256:' + 'a' * 64,
            }],
        }),
    )

    assert result.installable is True
    assert result.asset_name == 'SYNTEC-电子票据处理系统-v7.0.5.zip'
    assert result.asset_digest == 'a' * 64


def test_check_for_update_ignores_older_release_and_untrusted_url():
    result = check_for_update(
        '7.0.5',
        opener=lambda *_args, **_kwargs: FakeResponse({
            'tag_name': '7.0.4',
            'html_url': 'https://example.com/fake-release',
        }),
    )

    assert result.checked is True
    assert result.available is False
    assert result.latest_version == '7.0.4'
    assert result.release_url is None


def test_check_for_update_falls_back_to_known_release_url():
    result = check_for_update(
        '7.0.4',
        opener=lambda *_args, **_kwargs: FakeResponse({
            'tag_name': 'v7.0.5',
            'html_url': 'https://example.com/fake-release',
        }),
    )

    assert result.available is True
    assert result.release_url == GITHUB_RELEASES_URL


def test_check_for_update_does_not_fail_when_github_is_unreachable():
    def opener(*_args, **_kwargs):
        raise URLError('offline')

    result = check_for_update('7.0.4', opener=opener)

    assert result.checked is False
    assert result.available is False
    assert result.latest_version is None
    assert result.release_url is None
    assert GITHUB_RELEASES_URL.endswith('/releases/latest')


def test_stage_update_downloads_and_extracts_zip(tmp_path):
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, 'w') as archive:
        archive.writestr(
            f'SYNTEC-电子票据处理系统-v7.0.5/{MAIN_EXECUTABLE_NAME}',
            b'exe',
        )
    archive_body = archive_buffer.getvalue()
    result = UpdateResult(
        current_version='7.0.4',
        checked=True,
        available=True,
        latest_version='7.0.5',
        asset_name='SYNTEC-电子票据处理系统-v7.0.5.zip',
        asset_url='https://github.com/SYNTEC-40101720/Automated-invoice-processing/releases/download/v7.0.5/SYNTEC.zip',
        asset_digest=hashlib.sha256(archive_body).hexdigest(),
    )

    staged = stage_update(
        result,
        temporary_parent=tmp_path,
        opener=lambda *_args, **_kwargs: RawResponse(archive_body),
    )

    assert (staged.package_dir / MAIN_EXECUTABLE_NAME).read_bytes() == b'exe'


def test_stage_update_rejects_zip_path_traversal(tmp_path):
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, 'w') as archive:
        archive.writestr('../outside.txt', b'unsafe')
    archive_body = archive_buffer.getvalue()
    result = UpdateResult(
        current_version='7.0.4',
        checked=True,
        available=True,
        latest_version='7.0.5',
        asset_name='SYNTEC-电子票据处理系统-v7.0.5.zip',
        asset_url='https://github.com/SYNTEC-40101720/Automated-invoice-processing/releases/download/v7.0.5/SYNTEC.zip',
    )

    try:
        stage_update(
            result,
            temporary_parent=tmp_path,
            opener=lambda *_args, **_kwargs: RawResponse(archive_body),
        )
    except UpdateError:
        pass
    else:
        raise AssertionError('应拒绝包含路径穿越的更新压缩包')
    assert not (tmp_path / 'outside.txt').exists()
