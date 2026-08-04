"""敏感配置保护：Windows DPAPI 加解密

通过系统 CryptProtectData/CryptUnprotectData 对密钥（邮箱授权码、API Key）
加密后写入 config.ini，密文带 `dpapi:` 前缀，仅当前 Windows 用户可解密。

非 Windows 平台（CI/跨平台测试）降级为 base64 编码透传，不保证安全性。
"""
import base64
import ctypes
import logging
import sys
from ctypes import wintypes

logger = logging.getLogger(__name__)

PREFIX = 'dpapi:'

# CRYPTPROTECT_UI_FORBIDDEN = 0x1（禁止弹出 UI 提示）
_FLAG = 0x1


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [('cbData', wintypes.DWORD),
                ('pbData', ctypes.POINTER(ctypes.c_char))]


def _is_windows() -> bool:
    return sys.platform == 'win32'


def encrypt(plain: str) -> str:
    """加密明文，返回可写入 config.ini 的串（空串原样返回）"""
    if not plain:
        return ''
    if not _is_windows():
        logger.warning('非 Windows 平台，密钥仅 base64 编码存储（不加密）')
        return PREFIX + base64.b64encode(plain.encode('utf-8')).decode('ascii')

    data = plain.encode('utf-8')
    src_buf = ctypes.create_string_buffer(data)
    blob_in = _DATA_BLOB(len(data),
                         ctypes.cast(src_buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = _DATA_BLOB()
    if not ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(blob_in), None, None, None, None, _FLAG,
            ctypes.byref(blob_out)):
        raise ctypes.WinError()
    try:
        enc = ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)
    return PREFIX + base64.b64encode(enc).decode('ascii')


def decrypt(stored: str) -> str:
    """解密 `dpapi:` 前缀的密文；无前缀串原样返回（兼容历史明文/空值）"""
    if not stored:
        return ''
    if not stored.startswith(PREFIX):
        return stored
    payload = base64.b64decode(stored[len(PREFIX):])
    if not _is_windows():
        return payload.decode('utf-8')

    data = bytes(payload)
    src_buf = ctypes.create_string_buffer(data)
    blob_in = _DATA_BLOB(len(data),
                         ctypes.cast(src_buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = _DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), None, None, None, None, _FLAG,
            ctypes.byref(blob_out)):
        raise ctypes.WinError()
    try:
        raw = ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)
    return raw.decode('utf-8')
