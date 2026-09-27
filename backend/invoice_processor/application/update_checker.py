"""从 GitHub Releases 查询可用版本（仅检测提示，不做下载安装）。"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..version import __version__

logger = logging.getLogger(__name__)

GITHUB_REPOSITORY = 'SYNTEC-40101720/Automated-invoice-processing'
GITHUB_API_URL = (
    f'https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/latest'
)
GITHUB_RELEASES_URL = (
    f'https://github.com/{GITHUB_REPOSITORY}/releases/latest'
)
REQUEST_TIMEOUT = 3.0
_VERSION_PATTERN = re.compile(r'^v?(\d+)\.(\d+)\.(\d+)$', re.IGNORECASE)


@dataclass(frozen=True)
class UpdateResult:
    current_version: str
    checked: bool
    available: bool
    latest_version: str | None = None
    release_url: str | None = None


def _parse_version(value: object) -> tuple[int, int, int] | None:
    if not isinstance(value, str):
        return None
    match = _VERSION_PATTERN.fullmatch(value.strip())
    if not match:
        return None
    return (
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3)),
    )


def check_for_update(
    current_version: str = __version__,
    *,
    opener: Callable[..., Any] | None = None,
) -> UpdateResult:
    """查询最新稳定 Release；网络不可用时返回未完成检查。"""
    current_parts = _parse_version(current_version)
    if current_parts is None:
        logger.warning('当前版本格式无效，跳过更新检查: %s', current_version)
        return UpdateResult(
            current_version=current_version,
            checked=False,
            available=False,
            release_url=GITHUB_RELEASES_URL,
        )

    request = Request(
        GITHUB_API_URL,
        headers={
            'Accept': 'application/vnd.github+json',
            'User-Agent': f'SYNTEC-Invoice-Processor/{current_version}',
        },
    )
    open_url = opener or urlopen
    try:
        with open_url(request, timeout=REQUEST_TIMEOUT) as response:
            payload = json.loads(response.read().decode('utf-8'))
    except (HTTPError, URLError, TimeoutError, OSError, TypeError, ValueError) as exc:
        logger.info('GitHub 更新检查失败: %s', exc)
        return UpdateResult(
            current_version=current_version,
            checked=False,
            available=False,
            release_url=GITHUB_RELEASES_URL,
        )

    if not isinstance(payload, dict):
        logger.info('GitHub 更新响应格式无效')
        return UpdateResult(
            current_version=current_version,
            checked=False,
            available=False,
        )

    latest_tag = payload.get('tag_name')
    latest_parts = _parse_version(latest_tag)
    if latest_parts is None:
        logger.info('GitHub Release 没有有效版本标签: %s', latest_tag)
        return UpdateResult(
            current_version=current_version,
            checked=True,
            available=False,
        )

    latest_version = f'{latest_parts[0]}.{latest_parts[1]}.{latest_parts[2]}'
    available = latest_parts > current_parts
    return UpdateResult(
        current_version=current_version,
        checked=True,
        available=available,
        latest_version=latest_version,
        release_url=GITHUB_RELEASES_URL,
    )
