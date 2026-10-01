"""单实例锁：Windows 命名互斥体，防止双开。

锁失效不挡启动——单实例是体验优化而非安全边界：创建互斥体失败时
放行（宁可开两个窗口，不能开不了）。句柄不显式释放，进程终止时
由操作系统自动回收，taskkill /F 也不会残留死锁。
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# 全局命名空间（无 Local\ 前缀）覆盖同机所有会话
_MUTEX_NAME = 'SYNTEC-Invoice-Processor-SingleInstance'
_ERROR_ALREADY_EXISTS = 183

# 非 Windows / 创建失败直通时返回的哨兵句柄（非 None 即视为持锁）
_OPEN_LOCK = -1

# 验收/冒烟脚本注入的环境变量：跳过互斥体获取，允许并行拉起多实例
BYPASS_ENV = 'PLATFORM_ALLOW_SECOND_INSTANCE'


def acquire_single_instance_lock() -> int | None:
    """获取单实例锁；成功返回句柄哨兵，已有实例返回 None。

    非 Windows 平台无锁直通（返回哨兵）；创建失败降级放行。
    """
    if os.name != 'nt':
        return _OPEN_LOCK
    if os.environ.get(BYPASS_ENV) == '1':
        logger.info('单实例锁旁路生效（%s=1），跳过互斥体获取', BYPASS_ENV)
        return _OPEN_LOCK
    try:
        import ctypes

        # use_last_error=True：ctypes.get_last_error() 只有在该标志下才
        # 可靠——windll（use_last_error=False）下恒为 0，ALREADY_EXISTS
        # 永远检测不到，双开检测会整体失效（实测 GetLastError=183 但
        # ctypes.get_last_error()=0）。
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        handle = kernel32.CreateMutexW(None, False, _MUTEX_NAME)
        if not handle:
            logger.warning('单实例互斥体创建失败，本次放行启动')
            return _OPEN_LOCK
        if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
            return None
        return handle
    except Exception:
        logger.warning('单实例锁获取异常，本次放行启动', exc_info=True)
        return _OPEN_LOCK
