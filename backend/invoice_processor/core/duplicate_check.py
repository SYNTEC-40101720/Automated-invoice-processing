"""全局内容去重索引：sha256 持久化（logs/duplicate_index.json）。

D4（docs/ADR-2026-10-27-识别增强.md）：同内容 PDF 跨任务只处理一次。
索引是处理链路的旁路记录，与 job_history 同策略：磁盘 IO 失败一律降级
为 warning 日志，不阻断任务；文件损坏时重置为空（宁可重复处理也不误跳）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

# 流式读取块大小（1 MiB，避免大文件整载内存）
_CHUNK_SIZE = 1024 * 1024

# 索引文件名（放 logs/ 目录，与 job_history.jsonl 同级，随 logs/ 跨升级保留）
INDEX_FILENAME = 'duplicate_index.json'

# 索引重审线（ADR D4：条数超过阈值时改 SQLite）
SOFT_LIMIT_ENTRIES = 50000


def default_duplicate_index_path() -> Path:
    """索引默认落点：logs/duplicate_index.json（与 job_history 同级保留策略）。"""
    import sys

    if getattr(sys, 'frozen', False):
        base_dir = Path(sys.executable).resolve().parent
    else:
        base_dir = Path(__file__).resolve().parents[3]
    return base_dir / 'logs' / INDEX_FILENAME


def compute_sha256(path: str | os.PathLike[str]) -> str:
    """流式计算文件 sha256；读失败抛 OSError（调用方决定降级语义）。"""
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        while True:
            chunk = handle.read(_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


class DuplicateIndex:
    """sha256 → 元数据 的进程内索引，持久化为 JSON；线程安全。

    进程内唯一实例由 JobService 持有；add/contains 均持锁，「先查后加」
    竞态在任务书里被允许（同批两个相同文件有一个被处理即可接受）。
    """

    def __init__(self, path: str | os.PathLike[str]):
        self._path = Path(path)
        self._lock = threading.Lock()
        self._entries: dict[str, dict] = {}
        self._loaded = False

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> None:
        """从磁盘读索引；缺失/损坏一律重置为空（容错优先）。"""
        with self._lock:
            self._loaded = True
            self._entries = self._read_entries_locked()

    def add(self, content_hash: str, meta: dict | None = None) -> None:
        """登记一个内容哈希；meta 任意 JSON 值（如首见文件相对路径）。"""
        if not content_hash:
            return
        with self._lock:
            if content_hash not in self._entries:
                self._entries[content_hash] = meta or {}
            self._write_entries_locked()

    def contains(self, content_hash: str) -> bool:
        with self._lock:
            return content_hash in self._entries

    def size(self) -> int:
        with self._lock:
            return len(self._entries)

    def save(self) -> None:
        """显式落盘（任务终态调用）；add 已实时落盘，此处为兜底幂等。"""
        with self._lock:
            self._write_entries_locked()

    # -- 内部（调用方须持锁） -------------------------------------------------

    def _read_entries_locked(self) -> dict[str, dict]:
        try:
            raw = self._path.read_text(encoding='utf-8')
        except FileNotFoundError:
            return {}
        except OSError:
            logger.warning('读取重复索引失败: %s', self._path, exc_info=True)
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning('重复索引损坏，已重置为空: %s', self._path)
            return {}
        if not isinstance(parsed, dict):
            logger.warning('重复索引格式异常，已重置为空: %s', self._path)
            return {}
        entries: dict[str, dict] = {}
        for key, value in parsed.items():
            if isinstance(key, str) and isinstance(value, dict):
                entries[key] = value
        return entries

    def _write_entries_locked(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self._path.with_name(self._path.name + '.tmp')
            payload = json.dumps(self._entries, ensure_ascii=False, indent=1)
            temp_path.write_text(payload, encoding='utf-8')
            os.replace(temp_path, self._path)
        except OSError:
            logger.warning('写入重复索引失败: %s', self._path, exc_info=True)
