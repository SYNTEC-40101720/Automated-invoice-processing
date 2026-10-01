"""跨启动处理历史：JSON Lines 落盘（logs/job_history.jsonl）。

历史是任务终态的旁路记录，不进关键路径：磁盘 IO 失败一律降级为
warning 日志，不影响任务终态流。写入为「读旧 + 追加 + 裁剪 + 原子
替换」全量重写——上限条数下最简单，且天然规避截断损坏。
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

# 历史落盘挑选的字段（从 job.to_dict() 挑拣，不存 result 全量）。
# to_dict 的任务号键是 ``id``，历史条目对外统一为 ``job_id``
# （与 API JobHistoryEntry.job_id 对齐），在 _entry_from_snapshot 映射。
_SNAPSHOT_FIELDS = (
    'id',
    'source_dir',
    'output_dir',
    'trigger',
    'status',
    'stats',
    'started_at',
    'finished_at',
    'error_code',
    'error_message',
)

# 历史条数上限（磁盘长期记录，与内存 job_history_limit 独立）
DEFAULT_LIMIT = 50

# 历史文件名（logs/ 目录内，随 logs/ 跨升级保留）
HISTORY_FILENAME = 'job_history.jsonl'


def default_history_path() -> Path:
    """默认历史路径：logs/job_history.jsonl（与 invoice.log 同目录）。"""
    import sys

    if getattr(sys, 'frozen', False):
        base_dir = Path(sys.executable).resolve().parent
    else:
        base_dir = Path(__file__).resolve().parents[3]
    return base_dir / 'logs' / HISTORY_FILENAME


def _entry_from_snapshot(snapshot: dict) -> dict:
    entry = {key: snapshot.get(key) for key in _SNAPSHOT_FIELDS if key != 'id'}
    entry['job_id'] = snapshot.get('id') or snapshot.get('job_id')
    return entry


class JobHistoryStore:
    """任务终态历史的磁盘存储；线程安全，进程内单一实例使用。"""

    def __init__(self, path: str | os.PathLike[str], limit: int = DEFAULT_LIMIT):
        self._path = Path(path)
        self._limit = max(1, limit)
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def append(self, snapshot: dict) -> None:
        """追加一条终态记录；重复 job_id 跳过，IO 失败降级不抛出。"""
        entry = _entry_from_snapshot(snapshot)
        job_id = entry.get('job_id')
        if not job_id:
            return
        with self._lock:
            entries = self._read_entries_locked()
            if any(item.get('job_id') == job_id for item in entries):
                return
            entries.append(entry)
            self._write_entries_locked(entries[-self._limit:])

    def list(self) -> list[dict]:
        """返回全部历史（旧→新）；读失败返回空列表。"""
        with self._lock:
            return self._read_entries_locked()

    def _read_entries_locked(self) -> list[dict]:
        try:
            raw = self._path.read_text(encoding='utf-8')
        except FileNotFoundError:
            return []
        except OSError:
            logger.warning('读取处理历史失败: %s', self._path, exc_info=True)
            return []
        entries = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                # 单行损坏（如历史截断）只丢弃该行，不影响其余记录
                logger.warning('处理历史存在损坏行，已跳过: %s', self._path)
                continue
            if isinstance(parsed, dict):
                entries.append(parsed)
        return entries

    def _write_entries_locked(self, entries: list[dict]) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self._path.with_suffix('.jsonl.tmp')
            payload = ''.join(
                json.dumps(entry, ensure_ascii=False) + '\n' for entry in entries
            )
            temp_path.write_text(payload, encoding='utf-8')
            os.replace(temp_path, self._path)
        except OSError:
            logger.warning('写入处理历史失败: %s', self._path, exc_info=True)
