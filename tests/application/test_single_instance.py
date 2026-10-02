"""单实例锁测试：双开检测、旁路、降级语义。

Windows 命名互斥体语义（实测踩坑后固化）：``ctypes.get_last_error()`` 只在
``WinDLL(use_last_error=True)`` 下可靠——``ctypes.windll`` 下恒为 0，双开检测
会整体失效。第二条用例直接锁住这一点。
"""

from __future__ import annotations

import ctypes
import sys

import pytest
from invoice_processor.desktop.single_instance import (
    BYPASS_ENV,
    acquire_single_instance_lock,
)


def _release_mutex(handle: int) -> None:
    ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(handle)


@pytest.mark.skipif(
    sys.platform != 'win32', reason='命名互斥体双开语义仅 Windows'
)
def test_first_acquire_succeeds_and_second_is_rejected(monkeypatch):
    # 非 Windows 走 os.name 直通返回哨兵 -1（非 None），无法在此断言
    # 互斥体语义——Linux CI 上按 skip 处理，本测试仅 Windows 生效。
    monkeypatch.delenv(BYPASS_ENV, raising=False)
    first = acquire_single_instance_lock()
    assert first not in (0, -1), '首个获取应返回真实互斥体句柄'
    try:
        second = acquire_single_instance_lock()
        assert second is None, "已有实例时二次获取必须返回 None"
    finally:
        _release_mutex(first)


def test_bypass_env_skips_mutex(monkeypatch):
    monkeypatch.setenv(BYPASS_ENV, "1")
    lock = acquire_single_instance_lock()
    assert lock is not None
    # 旁路直通不持互斥体（返回哨兵），无需释放


def test_kernel32_binding_uses_last_error():
    # 回归锚点：绑定必须 use_last_error=True，否则 ctypes.get_last_error()
    # 恒为 0（源码静态检查，防手滑改回 windll）。
    import inspect

    from invoice_processor.desktop import single_instance

    source = inspect.getsource(single_instance.acquire_single_instance_lock)
    assert "use_last_error=True" in source
    assert "ctypes.windll" not in source
