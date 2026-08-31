"""从 GitHub Releases 查询可用版本。"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import stat
import tempfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
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
MAIN_EXECUTABLE_NAME = 'SYNTEC-电子票据处理系统.exe'
UPDATE_HELPER_NAME = 'SYNTEC-电子票据更新器.exe'
UPDATE_ASSET_PREFIX = 'SYNTEC-Invoice-Processor'
LEGACY_UPDATE_ASSET_PREFIXES = ('SYNTEC-电子票据处理系统', 'SYNTEC-.-')
REQUEST_TIMEOUT = 3.0
MAX_UPDATE_BYTES = 512 * 1024 * 1024
DOWNLOAD_CHUNK_SIZE = 1024 * 1024
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

    @property
    def installable(self) -> bool:
        return self.available and bool(self.asset_name and self.asset_url)


@dataclass(frozen=True)
class UpdateApplyResult:
    status: str
    message: str
    latest_version: str | None = None


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    url: str
    digest: str | None = None


@dataclass(frozen=True)
class StagedUpdate:
    temporary_dir: Path
    package_dir: Path


class UpdateError(RuntimeError):
    """更新文件无法下载、校验或解压。"""


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
            or Path(name).name != name
        ):
            continue
        url = _safe_download_url(item.get('browser_download_url'))
        if url is None:
            continue
        return ReleaseAsset(
            name=name,
            url=url,
            digest=_normalise_digest(item.get('digest')),
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
    )


def _download_asset(
    asset_url: str,
    destination: Path,
    current_version: str,
    expected_digest: str | None,
    opener: Callable[..., Any] | None,
) -> None:
    request = Request(
        asset_url,
        headers={
            'Accept': 'application/octet-stream',
            'User-Agent': f'SYNTEC-Invoice-Processor/{current_version}',
        },
    )
    open_url = opener or urlopen
    digest = hashlib.sha256()
    total = 0
    try:
        with open_url(request, timeout=REQUEST_TIMEOUT) as response:
            content_length = getattr(response, 'headers', {}).get('Content-Length')
            if content_length is not None and int(content_length) > MAX_UPDATE_BYTES:
                raise UpdateError('更新文件超过 512 MB 限制')
            with destination.open('wb') as output:
                while chunk := response.read(DOWNLOAD_CHUNK_SIZE):
                    total += len(chunk)
                    if total > MAX_UPDATE_BYTES:
                        raise UpdateError('更新文件超过 512 MB 限制')
                    digest.update(chunk)
                    output.write(chunk)
    except UpdateError:
        raise
    except (HTTPError, URLError, TimeoutError, OSError, TypeError, ValueError) as exc:
        raise UpdateError('下载更新文件失败') from exc

    if total == 0:
        raise UpdateError('下载的更新文件为空')
    if expected_digest and digest.hexdigest().lower() != expected_digest.lower():
        raise UpdateError('更新文件校验失败')


def _extract_zip_safely(archive_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            if not target.is_relative_to(root):
                raise UpdateError('更新压缩包包含非法路径')
            mode = member.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise UpdateError('更新压缩包不允许包含符号链接')
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open('wb') as output:
                shutil.copyfileobj(source, output)


def _find_package_dir(extracted_dir: Path) -> Path:
    if (extracted_dir / MAIN_EXECUTABLE_NAME).is_file():
        return extracted_dir
    candidates = [
        child for child in extracted_dir.iterdir()
        if child.is_dir() and (child / MAIN_EXECUTABLE_NAME).is_file()
    ]
    if len(candidates) == 1:
        return candidates[0]
    raise UpdateError('更新压缩包内找不到 SYNTEC 主程序')


def _validate_package_bundle(package_dir: Path) -> None:
    internal_dir = package_dir / '_internal'
    missing: list[str] = []
    if not (package_dir / MAIN_EXECUTABLE_NAME).is_file():
        missing.append(MAIN_EXECUTABLE_NAME)
    if not (package_dir / UPDATE_HELPER_NAME).is_file():
        missing.append(UPDATE_HELPER_NAME)
    if not internal_dir.is_dir():
        missing.append('_internal/')
    else:
        if not any(
            path.is_file() for path in internal_dir.glob('python*.dll')
        ):
            missing.append('_internal/python*.dll')
        if not (internal_dir / '_ctypes.pyd').is_file():
            missing.append('_internal/_ctypes.pyd')
        if not (internal_dir / 'web' / 'dist' / 'index.html').is_file():
            missing.append('_internal/web/dist/index.html')
    if missing:
        raise UpdateError(
            '更新压缩包缺少必备项: ' + ', '.join(missing)
        )


def stage_update(
    result: UpdateResult,
    *,
    temporary_parent: Path | None = None,
    opener: Callable[..., Any] | None = None,
) -> StagedUpdate:
    """下载并解压更新包；返回供独立更新器使用的临时目录。"""
    if not result.installable or result.asset_name is None or result.asset_url is None:
        raise UpdateError('当前 Release 没有可安装的 SYNTEC ZIP 文件')

    temporary_dir = Path(tempfile.mkdtemp(
        prefix='.syntec-update-',
        dir=str(temporary_parent) if temporary_parent else None,
    ))
    archive_path = temporary_dir / result.asset_name
    extracted_dir = temporary_dir / 'extracted'
    try:
        _download_asset(
            result.asset_url,
            archive_path,
            result.current_version,
            result.asset_digest,
            opener,
        )
        _extract_zip_safely(archive_path, extracted_dir)
        package_dir = _find_package_dir(extracted_dir)
        _validate_package_bundle(package_dir)
        return StagedUpdate(temporary_dir, package_dir)
    except (UpdateError, OSError, ValueError, zipfile.BadZipFile) as exc:
        shutil.rmtree(temporary_dir, ignore_errors=True)
        if isinstance(exc, UpdateError):
            raise
        raise UpdateError('更新压缩包无法使用') from exc
