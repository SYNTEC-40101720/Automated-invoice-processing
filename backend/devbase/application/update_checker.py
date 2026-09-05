"""GitHub Release discovery and verified asset download."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen


class UpdateCheckError(RuntimeError):
    """Raised for malformed or unsafe release metadata."""


@dataclass(frozen=True, order=True, slots=True)
class ReleaseVersion:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, value: str) -> "ReleaseVersion":
        match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", value.strip())
        if match is None:
            raise UpdateCheckError(f"invalid release version: {value!r}")
        return cls(*(int(part) for part in match.groups()))

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclass(frozen=True, slots=True)
class UpdateConfig:
    owner: str = "SYNTEC-40101720"
    repository: str = "Zy-DevBase"
    asset_prefix: str = "SYNTEC_DevBase-"
    max_download_bytes: int = 512 * 1024 * 1024
    timeout_seconds: float = 15.0

    @property
    def api_url(self) -> str:
        return f"https://api.github.com/repos/{self.owner}/{self.repository}/releases/latest"

    @property
    def download_prefix(self) -> str:
        return f"https://github.com/{self.owner}/{self.repository}/releases/download/"


@dataclass(frozen=True, slots=True)
class ReleaseAsset:
    name: str
    download_url: str
    size: int
    sha256: str | None = None


@dataclass(frozen=True, slots=True)
class ReleaseInfo:
    tag_name: str
    version: ReleaseVersion
    html_url: str
    asset: ReleaseAsset


@dataclass(frozen=True, slots=True)
class UpdateCheckResult:
    current: ReleaseVersion
    latest: ReleaseVersion | None
    available: bool
    installable: bool
    release: ReleaseInfo | None = None
    error: str | None = None


Opener = Callable[..., Any]


class GitHubReleaseClient:
    """Query one configured stable Release and download its matching asset."""

    def __init__(
        self,
        config: UpdateConfig | None = None,
        *,
        opener: Opener = urlopen,
    ) -> None:
        self.config = config or UpdateConfig()
        self._opener = opener

    def check(self, current: str | ReleaseVersion) -> UpdateCheckResult:
        current_version = (
            current if isinstance(current, ReleaseVersion) else ReleaseVersion.parse(current)
        )
        try:
            payload = self._fetch_release()
            release = self._parse_release(payload)
        except (OSError, URLError, TimeoutError, ValueError, TypeError, KeyError, UpdateCheckError) as error:
            return UpdateCheckResult(
                current=current_version,
                latest=None,
                available=False,
                installable=False,
                error=str(error),
            )
        if release.version <= current_version:
            return UpdateCheckResult(
                current=current_version,
                latest=release.version,
                available=False,
                installable=False,
                release=release,
            )
        return UpdateCheckResult(
            current=current_version,
            latest=release.version,
            available=True,
            installable=True,
            release=release,
        )

    def download_asset(
        self,
        asset: ReleaseAsset,
        destination: str | Path,
    ) -> Path:
        destination_dir = Path(destination)
        destination_dir.mkdir(parents=True, exist_ok=True)
        if asset.size < 0 or asset.size > self.config.max_download_bytes:
            raise UpdateCheckError("release asset exceeds configured size limit")
        request = Request(
            asset.download_url,
            headers={
                "Accept": "application/octet-stream",
                "User-Agent": "Zy-DevBase-updater",
            },
        )
        target: Path | None = None
        total = 0
        digest = hashlib.sha256()
        try:
            with self._opener(request, timeout=self.config.timeout_seconds) as response:
                content_length = response.headers.get("Content-Length")
                if content_length is not None and int(content_length) > self.config.max_download_bytes:
                    raise UpdateCheckError("release asset exceeds configured size limit")
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    prefix="download-",
                    suffix=".zip",
                    dir=destination_dir,
                    delete=False,
                ) as output:
                    target = Path(output.name)
                    for chunk in _chunks(response):
                        total += len(chunk)
                        if total > self.config.max_download_bytes:
                            raise UpdateCheckError("release asset exceeds configured size limit")
                        digest.update(chunk)
                        output.write(chunk)
            if total == 0:
                raise UpdateCheckError("release asset is empty")
            actual = digest.hexdigest()
            if asset.sha256 is not None and actual != asset.sha256:
                raise UpdateCheckError(
                    f"release SHA-256 mismatch: expected {asset.sha256}, got {actual}"
                )
            return target
        except Exception:
            if target is not None:
                target.unlink(missing_ok=True)
            raise

    def _fetch_release(self) -> dict[str, Any]:
        request = Request(
            self.config.api_url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "Zy-DevBase-updater",
            },
        )
        with self._opener(request, timeout=self.config.timeout_seconds) as response:
            payload = json.load(response)
        if not isinstance(payload, dict):
            raise UpdateCheckError("GitHub release response is not an object")
        return payload

    def _parse_release(self, payload: dict[str, Any]) -> ReleaseInfo:
        if payload.get("draft") or payload.get("prerelease"):
            raise UpdateCheckError("latest GitHub release is not stable")
        tag_name = payload.get("tag_name")
        html_url = payload.get("html_url")
        if not isinstance(tag_name, str) or not isinstance(html_url, str):
            raise UpdateCheckError("release is missing tag_name or html_url")
        version = ReleaseVersion.parse(tag_name)
        assets = payload.get("assets")
        if not isinstance(assets, list):
            raise UpdateCheckError("release assets are missing")
        asset = self._select_asset(assets)
        return ReleaseInfo(tag_name, version, html_url, asset)

    def _select_asset(self, assets: list[Any]) -> ReleaseAsset:
        candidates: list[ReleaseAsset] = []
        for raw in assets:
            if not isinstance(raw, dict):
                continue
            name = raw.get("name")
            download_url = raw.get("browser_download_url")
            if not isinstance(name, str) or not isinstance(download_url, str):
                continue
            if not name.startswith(self.config.asset_prefix) or not name.endswith(".zip"):
                continue
            if not download_url.startswith(self.config.download_prefix):
                continue
            digest = _parse_digest(raw.get("digest"))
            size = raw.get("size", 0)
            if not isinstance(size, int):
                raise UpdateCheckError("release asset size is invalid")
            candidates.append(ReleaseAsset(name, download_url, size, digest))
        if len(candidates) != 1:
            raise UpdateCheckError(
                f"expected one matching release asset, found {len(candidates)}"
            )
        return candidates[0]


def _parse_digest(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise UpdateCheckError("release asset digest is invalid")
    digest = value.removeprefix("sha256:").lower()
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise UpdateCheckError("release asset digest is not SHA-256")
    return digest


def _chunks(response: Any, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
    while True:
        chunk = response.read(chunk_size)
        if not chunk:
            return
        yield chunk


__all__ = [
    "GitHubReleaseClient",
    "ReleaseAsset",
    "ReleaseInfo",
    "ReleaseVersion",
    "UpdateCheckError",
    "UpdateCheckResult",
    "UpdateConfig",
]
