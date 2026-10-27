"""DuplicateIndex / compute_sha256 单元测试。

运行方式: pytest tests/application/test_duplicate_check.py -v
"""
from __future__ import annotations

import json
import threading

from invoice_processor.core.duplicate_check import (
    DuplicateIndex,
    compute_sha256,
)


def _write(path, data: bytes):
    path.write_bytes(data)
    return path


def test_compute_sha256_matches_known_vector(tmp_path):
    # sha256('abc') 标准测试向量
    file_path = _write(tmp_path / 'a.pdf', b'abc')
    assert compute_sha256(file_path) == (
        'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'
    )


def test_compute_sha256_streams_large_file(tmp_path):
    # 超过 1MiB 块边界的内容仍正确（流式分块读取）
    payload = b'x' * (1024 * 1024 + 123)
    file_path = _write(tmp_path / 'big.pdf', payload)
    import hashlib

    assert compute_sha256(file_path) == hashlib.sha256(payload).hexdigest()


def test_duplicate_index_add_contains_size(tmp_path):
    index = DuplicateIndex(tmp_path / 'duplicate_index.json')
    index.load()
    assert index.size() == 0
    assert not index.contains('h1')
    index.add('h1', {'first_seen': 'invoice-0.pdf'})
    assert index.contains('h1')
    assert not index.contains('h2')
    index.add('h1', {'first_seen': 'other.pdf'})
    assert index.size() == 1  # 重复 add 不覆盖首见元数据


def test_duplicate_index_persists_and_reloads(tmp_path):
    path = tmp_path / 'logs' / 'duplicate_index.json'
    index = DuplicateIndex(path)
    index.load()
    index.add('h1', {'first_seen': 'invoice-0.pdf'})
    index.add('h2')
    index.save()

    reloaded = DuplicateIndex(path)
    reloaded.load()
    assert reloaded.contains('h1')
    assert reloaded.contains('h2')
    assert reloaded.size() == 2


def test_duplicate_index_missing_file_loads_empty(tmp_path):
    index = DuplicateIndex(tmp_path / 'missing.json')
    index.load()
    assert index.size() == 0
    assert not index.contains('h1')


def test_duplicate_index_corrupt_file_resets_to_empty(tmp_path):
    path = tmp_path / 'duplicate_index.json'
    path.write_text('{"h1": {"first_seen": "a.pdf"', encoding='utf-8')
    index = DuplicateIndex(path)
    index.load()  # 损坏容错：重置为空而不是抛出
    assert index.size() == 0
    index.add('h2')
    index.save()
    reloaded = DuplicateIndex(path)
    reloaded.load()
    assert reloaded.contains('h2')
    assert not reloaded.contains('h1')


def test_duplicate_index_invalid_shape_resets_to_empty(tmp_path):
    path = tmp_path / 'duplicate_index.json'
    path.write_text(json.dumps(['h1', 'h2']), encoding='utf-8')
    index = DuplicateIndex(path)
    index.load()
    assert index.size() == 0


def test_duplicate_index_survives_io_error_on_readonly_dir(tmp_path):
    # 目录不可写时 save 降级为 warning 不抛出（旁路记录不阻断任务）
    read_only = tmp_path / 'locked'
    read_only.mkdir()
    index = DuplicateIndex(read_only / 'sub' / 'duplicate_index.json')
    index.load()
    index.add('h1')  # 父目录不存在时 add 会尝试 mkdir；此处路径可写所以成功
    # 直接验证 save 对不可创建路径不抛出：指向一个不可能的位置
    import os
    if os.name == 'nt':
        bad = DuplicateIndex('N:\\不存在的盘\\duplicate_index.json')
    else:
        bad = DuplicateIndex('/proc/1/duplicate_index.json')
    bad.load()
    bad.add('h1')
    bad.save()  # 不应抛出


def test_duplicate_index_thread_safety_concurrent_adds(tmp_path):
    index = DuplicateIndex(tmp_path / 'duplicate_index.json')
    index.load()
    barrier = threading.Barrier(8)

    def worker(worker_id: int):
        barrier.wait()
        for step in range(50):
            index.add(f'h-{worker_id}-{step}')
            assert index.contains(f'h-{worker_id}-{step}')

    threads = [
        threading.Thread(target=worker, args=(i,)) for i in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert index.size() == 8 * 50
