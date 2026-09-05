"""发票配置的密钥兼容层。

通用 DPAPI 实现由 DevBase 提供；本模块保留历史的函数式 API 和
``dpapi:`` 前缀，避免业务配置读写层发生变化。
"""

from __future__ import annotations

import base64
import sys

from devbase.secret_store import DPAPI_PREFIX, SecretStore


PREFIX = DPAPI_PREFIX


def encrypt(plain: str) -> str:
    """保护明文，返回可写入 config.ini 的密文。"""
    if not plain:
        return ""
    if sys.platform != "win32":
        return PREFIX + base64.b64encode(plain.encode("utf-8")).decode("ascii")
    return SecretStore().protect(plain)


def decrypt(stored: str) -> str:
    """解密 DevBase DPAPI 密文；无前缀值按历史明文兼容。"""
    if not stored or not stored.startswith(PREFIX):
        return stored
    if sys.platform != "win32":
        return base64.b64decode(stored[len(PREFIX):]).decode("utf-8")
    return SecretStore().unprotect(stored)


__all__ = ["PREFIX", "decrypt", "encrypt"]
