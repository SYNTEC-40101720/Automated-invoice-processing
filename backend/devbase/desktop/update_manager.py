"""Stage and apply verified GitHub Release updates."""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from threading import RLock
from typing import Callable
from uuid import uuid4

from devbase.application.update_checker import (
    GitHubReleaseClient,
    ReleaseVersion,
    UpdateCheckResult,
)

from .update_helper import (
    ReadyUpdate,
    apply_staged_update,
    require_release_files,
    safe_extract_zip,
    write_ready_file,
)


@dataclass(frozen=True, slots=True)
class UpdateProgress:
    status: str = "idle"
    percent: int = 0
    message: str = ""
    error: str | None = None
    rollback: bool = False
    ready_file: str | None = None


class UpdateManager:
    """Own update state without embedding business-specific release names."""

    def __init__(
        self,
        current_version: str,
        *,
        client: GitHubReleaseClient | None = None,
        install_dir: str | Path,
        update_root: str | Path | None = None,
        executable_name: str = "SYNTEC_DevBase.exe",
        updater_name: str | None = "SYNTEC_DevBase-updater.exe",
    ) -> None:
        self.current_version = ReleaseVersion.parse(current_version)
        self.client = client or GitHubReleaseClient()
        self.install_dir = Path(install_dir).resolve()
        self.update_root = Path(update_root or tempfile.gettempdir()).resolve()
        self.executable_name = executable_name
        self.updater_name = updater_name
        self._lock = RLock()
        self._progress = UpdateProgress()
        self._ready: ReadyUpdate | None = None
        self._ready_file: Path | None = None

    def progress(self) -> UpdateProgress:
        with self._lock:
            return self._progress

    def check(self) -> UpdateCheckResult:
        self._set_progress("checking", 5, "checking for updates")
        result = self.client.check(self.current_version)
        if result.error:
            self._set_progress("failed", 0, result.error, error=result.error)
        elif result.available:
            self._set_progress("available", 10, f"version {result.latest} is available")
        else:
            self._set_progress("up_to_date", 100, "already up to date")
        return result

    def stage(self, result: UpdateCheckResult | None = None) -> ReadyUpdate:
        if result is None:
            result = self.check()
        if not result.installable or result.release is None:
            raise RuntimeError(result.error or "no installable update is available")

        session = self.update_root / f"devbase-update-{uuid4().hex}"
        extracted = session / "extracted"
        download_dir = session / "download"
        self._set_progress("downloading", 20, "downloading release")
        try:
            archive = self.client.download_asset(result.release.asset, download_dir)
            self._set_progress("staging", 65, "verifying release files")
            release_dir = safe_extract_zip(
                archive,
                extracted,
                expected_top_level=self._expected_top_level(result.release.asset.name),
            )
            require_release_files(
                release_dir,
                executable_name=self.executable_name,
                updater_name=self.updater_name,
            )
            backup_dir = self.install_dir.with_name(
                f"{self.install_dir.name}.backup-{uuid4().hex[:8]}"
            )
            ready = ReadyUpdate(
                staged_dir=release_dir,
                install_dir=self.install_dir,
                backup_dir=backup_dir,
                executable_name=self.executable_name,
                updater_name=self.updater_name or "SYNTEC_DevBase-updater.exe",
            )
            ready_file = write_ready_file(session / "ready.json", ready)
            with self._lock:
                self._ready = ready
                self._ready_file = ready_file
                self._progress = UpdateProgress(
                    status="ready",
                    percent=80,
                    message="update is ready to apply",
                    ready_file=str(ready_file),
                )
            return ready
        except Exception as error:
            shutil.rmtree(session, ignore_errors=True)
            self._set_progress("failed", 0, str(error), error=str(error))
            raise

    def apply(
        self,
        *,
        process_id: int | None = None,
        wait_for_exit: Callable[[int], bool] | None = None,
        restart: Callable[[Path], None] | None = None,
    ) -> UpdateProgress:
        with self._lock:
            ready = self._ready
        if ready is None:
            raise RuntimeError("no staged update is ready")
        self._set_progress("applying", 85, "applying update")
        try:
            apply_staged_update(
                ready.staged_dir,
                ready.install_dir,
                ready.backup_dir,
                process_id=process_id,
                wait_for_exit=wait_for_exit,
                restart=restart,
            )
        except Exception as error:
            self._set_progress("failed", 0, str(error), error=str(error), rollback=True)
            raise
        with self._lock:
            self._ready = None
            ready_file = self._ready_file
            self._ready_file = None
            self._progress = UpdateProgress(
                status="succeeded",
                percent=100,
                message="update applied successfully",
            )
        if ready_file is not None:
            shutil.rmtree(ready_file.parent, ignore_errors=True)
            return self._progress

    def _expected_top_level(self, asset_name: str) -> str:
        prefix = self.client.config.asset_prefix.rstrip("-_")
        if prefix:
            return prefix
        stem = asset_name.removesuffix(".zip")
        if not stem:
            raise ValueError("release asset has no top-level directory name")
        return stem

    def _set_progress(
        self,
        status: str,
        percent: int,
        message: str,
        *,
        error: str | None = None,
        rollback: bool = False,
    ) -> None:
        with self._lock:
            self._progress = replace(
                self._progress,
                status=status,
                percent=percent,
                message=message,
                error=error,
                rollback=rollback,
            )


__all__ = ["UpdateManager", "UpdateProgress"]
