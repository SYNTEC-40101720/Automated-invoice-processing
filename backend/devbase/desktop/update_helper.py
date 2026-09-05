"""Safe staged replacement primitives and the independent updater entry point."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable


class UpdateApplyError(RuntimeError):
    """Raised when staged replacement or rollback fails."""


@dataclass(frozen=True, slots=True)
class ReadyUpdate:
    staged_dir: Path
    install_dir: Path
    backup_dir: Path
    process_id: int | None = None
    executable_name: str = "SYNTEC_DevBase.exe"
    updater_name: str = "SYNTEC_DevBase-updater.exe"


def _member_parts(name: str) -> tuple[str, ...]:
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or (len(normalized) >= 2 and normalized[1] == ":"):
        raise UpdateApplyError(f"absolute ZIP member is not allowed: {name}")
    path = PurePosixPath(normalized)
    parts = path.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise UpdateApplyError(f"unsafe ZIP member path: {name}")
    return parts


def _is_symlink(info) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return stat.S_ISLNK(mode)


def safe_extract_zip(
    archive: str | Path,
    destination: str | Path,
    *,
    expected_top_level: str | None = None,
) -> Path:
    """Extract a single-top-level-directory ZIP without path traversal."""
    import zipfile

    destination_path = Path(destination).resolve()
    destination_path.mkdir(parents=True, exist_ok=True)
    members: list[tuple[object, tuple[str, ...]]] = []
    top_levels: set[str] = set()
    with zipfile.ZipFile(archive) as source:
        for info in source.infolist():
            if _is_symlink(info):
                raise UpdateApplyError(f"symbolic links are not allowed: {info.filename}")
            parts = _member_parts(info.filename)
            top_levels.add(parts[0])
            members.append((info, parts))
        if len(top_levels) != 1:
            raise UpdateApplyError("ZIP must contain exactly one top-level directory")
        top_level = next(iter(top_levels))
        if expected_top_level is not None and top_level != expected_top_level:
            raise UpdateApplyError(
                f"unexpected ZIP top-level directory: {top_level!r}"
            )
        root = destination_path / top_level
        for info, parts in members:
            target = (destination_path.joinpath(*parts)).resolve()
            if destination_path not in target.parents and target != destination_path:
                raise UpdateApplyError(f"ZIP member escapes extraction root: {info.filename}")
            if info.is_dir() or info.filename.endswith(("/", "\\")):
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open(info) as input_file, target.open("wb") as output_file:
                shutil.copyfileobj(input_file, output_file)
    return root


def require_release_files(
    release_dir: str | Path,
    *,
    executable_name: str,
    updater_name: str | None = None,
) -> None:
    root = Path(release_dir)
    executable_matches = [path for path in root.rglob(executable_name) if path.is_file()]
    if len(executable_matches) != 1:
        raise UpdateApplyError(
            f"expected one {executable_name}, found {len(executable_matches)}"
        )
    if updater_name is not None:
        updater_matches = [path for path in root.rglob(updater_name) if path.is_file()]
        if len(updater_matches) != 1:
            raise UpdateApplyError(
                f"expected one {updater_name}, found {len(updater_matches)}"
            )


def _same_volume(*paths: Path) -> bool:
    drives = {os.path.splitdrive(str(path.resolve()))[0].lower() for path in paths}
    return len(drives) <= 1


def wait_for_process_exit(
    process_id: int,
    *,
    timeout: float = 30.0,
    poll_seconds: float = 0.1,
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(process_id, 0)
        except OSError:
            return True
        time.sleep(poll_seconds)
    return False


def _copy_preserved_paths(
    source_root: Path,
    destination_root: Path,
    preserved_paths: Iterable[str],
) -> None:
    for relative in preserved_paths:
        source = source_root / relative
        destination = destination_root / relative
        if not source.exists():
            continue
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)


def apply_staged_update(
    staged_dir: str | Path,
    install_dir: str | Path,
    backup_dir: str | Path,
    *,
    process_id: int | None = None,
    wait_for_exit: Callable[[int], bool] | None = None,
    preserved_paths: Iterable[str] = ("config", "logs"),
    restart: Callable[[Path], None] | None = None,
) -> None:
    """Replace an install directory, preserving data and rolling back on error."""
    staged = Path(staged_dir).resolve()
    install = Path(install_dir).resolve()
    backup = Path(backup_dir).resolve()
    if not staged.is_dir():
        raise UpdateApplyError(f"staged directory does not exist: {staged}")
    if not install.is_dir():
        raise UpdateApplyError(f"install directory does not exist: {install}")
    if backup.exists():
        raise UpdateApplyError(f"backup directory already exists: {backup}")
    if not _same_volume(staged, install, backup):
        raise UpdateApplyError("staging, install, and backup must share a volume")
    if process_id is not None:
        waiter = wait_for_exit or (lambda pid: wait_for_process_exit(pid))
        if not waiter(process_id):
            raise UpdateApplyError("main process did not exit before timeout")

    try:
        shutil.move(str(install), str(backup))
        shutil.move(str(staged), str(install))
        _copy_preserved_paths(backup, install, preserved_paths)
        if restart is not None:
            restart(install)
    except Exception as error:
        try:
            if install.exists():
                failed_dir = install.with_name(f"{install.name}.failed")
                if failed_dir.exists():
                    shutil.rmtree(failed_dir)
                shutil.move(str(install), str(failed_dir))
            if backup.exists():
                shutil.move(str(backup), str(install))
        except Exception as rollback_error:
            raise UpdateApplyError(
                f"update failed and rollback failed: {rollback_error}"
            ) from error
        raise UpdateApplyError(f"update failed and was rolled back: {error}") from error
    else:
        shutil.rmtree(backup)


def write_ready_file(path: str | Path, update: ReadyUpdate) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "staged_dir": str(update.staged_dir),
        "install_dir": str(update.install_dir),
        "backup_dir": str(update.backup_dir),
        "process_id": update.process_id,
        "executable_name": update.executable_name,
        "updater_name": update.updater_name,
    }
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, target)
    return target


def read_ready_file(path: str | Path) -> ReadyUpdate:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return ReadyUpdate(
        staged_dir=Path(payload["staged_dir"]),
        install_dir=Path(payload["install_dir"]),
        backup_dir=Path(payload["backup_dir"]),
        process_id=payload.get("process_id"),
        executable_name=payload.get("executable_name", "SYNTEC_DevBase.exe"),
        updater_name=payload.get("updater_name", "SYNTEC_DevBase-updater.exe"),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ready-file", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        update = read_ready_file(args.ready_file)
        apply_staged_update(
            update.staged_dir,
            update.install_dir,
            update.backup_dir,
            process_id=update.process_id,
            restart=lambda install: subprocess.Popen(
                [str(install / update.executable_name)],
                cwd=install,
                close_fds=True,
            ),
        )
        args.ready_file.unlink(missing_ok=True)
        shutil.rmtree(args.ready_file.parent, ignore_errors=True)
        return 0
    except (OSError, ValueError, KeyError, UpdateApplyError) as error:
        print(f"update failed: {error}", file=sys.stderr)
        return 1


__all__ = [
    "ReadyUpdate",
    "UpdateApplyError",
    "apply_staged_update",
    "main",
    "read_ready_file",
    "require_release_files",
    "safe_extract_zip",
    "wait_for_process_exit",
    "write_ready_file",
]


if __name__ == "__main__":
    raise SystemExit(main())
