"""从 GitHub Releases 查询可用版本（仅检测提示，不做下载安装）。"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
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
UPDATE_ASSET_PREFIX = 'SYNTEC-Invoice-Processor'
LEGACY_UPDATE_ASSET_PREFIXES = ('SYNTEC-电子票据处理系统', 'SYNTEC-.-')
REQUEST_TIMEOUT = 3.0
_VERSION_PATTERN = re.compile(r'^v?(\d+)\.(\d+)\.(\d+)$', re.IGNORECASE)
_DIGEST_PATTERN = re.compile(r'^sha256:([0-9a-f]{64})$', re.IGNORECASE)


@dataclass(frozen=True)
class UpdateResult:
    current_version: str
    checked: bool
    available: bool
    latest_version: str | None = None
    release_url: str | None = None
    asset_name: str | None = None
    asset_url: str | None = None
    asset_digest: str | None = None
    asset_size: int | None = None

    @property
    def installable(self) -> bool:
        return self.available and bool(self.asset_name and self.asset_url)


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    url: str
    digest: str | None = None
    size: int | None = None


class UpdateError(RuntimeError):
    """更新检查失败。"""


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


def _safe_release_url(value: object) -> str:
    if isinstance(value, str):
        parsed = urlparse(value)
        expected_path = f'/{GITHUB_REPOSITORY}/releases/'
        if (
            parsed.scheme == 'https'
            and parsed.netloc.lower() == 'github.com'
            and parsed.path.startswith(expected_path)
        ):
            return value
    return GITHUB_RELEASES_URL


def _safe_download_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    expected_path = f'/{GITHUB_REPOSITORY}/releases/download/'
    if (
        parsed.scheme == 'https'
        and parsed.netloc.lower() == 'github.com'
        and parsed.path.startswith(expected_path)
    ):
        return value
    return None


def _normalise_digest(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    match = _DIGEST_PATTERN.fullmatch(value.strip())
    return match.group(1).lower() if match else None


def _select_release_asset(payload: dict[str, Any]) -> ReleaseAsset | None:
    assets = payload.get('assets')
    if not isinstance(assets, list):
        return None
    for item in assets:
        if not isinstance(item, dict):
            continue
        name = item.get('name')
        if (
            not isinstance(name, str)
            or not name.startswith((UPDATE_ASSET_PREFIX, *LEGACY_UPDATE_ASSET_PREFIXES))
            or not name.lower().endswith('.zip')
            or PurePosixPath(name).name != name
        ):
            continue
        url = _safe_download_url(item.get('browser_download_url'))
        if url is None:
            continue
        raw_size = item.get('size')
        size = (
            raw_size
            if (
                isinstance(raw_size, int)
                and not isinstance(raw_size, bool)
                and raw_size >= 0
            )
            else None
        )
        return ReleaseAsset(
            name=name,
            url=url,
            digest=_normalise_digest(item.get('digest')),
            size=size,
        )
    return None


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
    asset = _select_release_asset(payload) if available else None
    return UpdateResult(
        current_version=current_version,
        checked=True,
        available=available,
        latest_version=latest_version,
        release_url=GITHUB_RELEASES_URL,
        asset_name=asset.name if asset else None,
        asset_url=asset.url if asset else None,
        asset_digest=asset.digest if asset else None,
        asset_size=asset.size if asset else None,
    )
