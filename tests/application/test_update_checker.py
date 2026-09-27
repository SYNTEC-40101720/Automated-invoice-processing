"""GitHub 更新检查测试。"""

from __future__ import annotations

from urllib.error import URLError

from invoice_processor.application.update_checker import (
    GITHUB_API_URL,
    GITHUB_RELEASES_URL,
    check_for_update,
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
    assert result.release_url == GITHUB_RELEASES_URL


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
    assert result.release_url == GITHUB_RELEASES_URL
    assert GITHUB_RELEASES_URL.endswith('/releases/latest')
