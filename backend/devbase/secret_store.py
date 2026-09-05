"""Windows DPAPI secret storage with an explicit test-only fallback."""

from __future__ import annotations

import base64
import binascii
import ctypes
import sys
import warnings
from ctypes import POINTER, Structure, byref, c_bool, c_ubyte, c_uint32, c_void_p
from ctypes import c_wchar_p

DPAPI_PREFIX = "dpapi:"
INSECURE_PREFIX = "insecure:"


class SecretStoreError(RuntimeError):
    """Raised for malformed or unusable protected secret data."""


class SecretStoreUnavailableError(SecretStoreError):
    """Raised when secure storage is unavailable without explicit fallback."""


class _DataBlob(Structure):
    _fields_ = [("cbData", c_uint32), ("pbData", POINTER(c_ubyte))]


def _is_windows(platform: str) -> bool:
    return platform == "win32"


def _bytes_blob(data: bytes) -> tuple[_DataBlob, object]:
    size = max(1, len(data))
    buffer = (c_ubyte * size)()
    if data:
        buffer[: len(data)] = data
    blob = _DataBlob(
        cbData=len(data),
        pbData=ctypes.cast(buffer, POINTER(c_ubyte)),
    )
    return blob, buffer


def _free_local(allocator, pointer) -> None:
    if pointer:
        allocator.LocalFree(ctypes.cast(pointer, c_void_p))


def _dpapi_protect(data: bytes) -> bytes:
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptProtectData.argtypes = [
        POINTER(_DataBlob),
        c_wchar_p,
        POINTER(_DataBlob),
        c_void_p,
        c_void_p,
        c_uint32,
        POINTER(_DataBlob),
    ]
    crypt32.CryptProtectData.restype = c_bool
    kernel32.LocalFree.argtypes = [c_void_p]
    kernel32.LocalFree.restype = c_void_p

    source, source_buffer = _bytes_blob(data)
    protected = _DataBlob()
    if not crypt32.CryptProtectData(
        byref(source),
        "DevBase secret",
        None,
        None,
        None,
        0,
        byref(protected),
    ):
        error = ctypes.get_last_error()
        raise OSError(error, "CryptProtectData failed")
    try:
        return ctypes.string_at(protected.pbData, protected.cbData)
    finally:
        _free_local(kernel32, protected.pbData)
        del source_buffer


def _dpapi_unprotect(data: bytes) -> bytes:
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    description = c_wchar_p()
    crypt32.CryptUnprotectData.argtypes = [
        POINTER(_DataBlob),
        POINTER(c_wchar_p),
        POINTER(_DataBlob),
        c_void_p,
        c_void_p,
        c_uint32,
        POINTER(_DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = c_bool
    kernel32.LocalFree.argtypes = [c_void_p]
    kernel32.LocalFree.restype = c_void_p

    source, source_buffer = _bytes_blob(data)
    plaintext = _DataBlob()
    if not crypt32.CryptUnprotectData(
        byref(source),
        byref(description),
        None,
        None,
        None,
        0,
        byref(plaintext),
    ):
        error = ctypes.get_last_error()
        raise OSError(error, "CryptUnprotectData failed")
    try:
        return ctypes.string_at(plaintext.pbData, plaintext.cbData)
    finally:
        _free_local(kernel32, plaintext.pbData)
        _free_local(kernel32, description)
        del source_buffer


class SecretStore:
    """Protect secrets with DPAPI or an explicitly opt-in test fallback."""

    def __init__(
        self,
        *,
        allow_insecure_fallback: bool = False,
        platform: str | None = None,
    ) -> None:
        self.allow_insecure_fallback = allow_insecure_fallback
        self.platform = platform or sys.platform

    @property
    def secure(self) -> bool:
        return _is_windows(self.platform)

    def protect(self, value: str) -> str:
        data = value.encode("utf-8")
        if self.secure:
            protected = _dpapi_protect(data)
            return DPAPI_PREFIX + base64.b64encode(protected).decode("ascii")
        if not self.allow_insecure_fallback:
            raise SecretStoreUnavailableError(
                "DPAPI is unavailable; enable allow_insecure_fallback only for tests"
            )
        warnings.warn(
            "Using insecure test-only secret storage; do not use in production",
            RuntimeWarning,
            stacklevel=2,
        )
        return INSECURE_PREFIX + base64.b64encode(data).decode("ascii")

    def unprotect(self, value: str) -> str:
        if not value.startswith((DPAPI_PREFIX, INSECURE_PREFIX)):
            return value
        prefix, encoded = value.split(":", 1)
        prefix = f"{prefix}:"
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as error:
            raise SecretStoreError("invalid protected secret encoding") from error

        if prefix == INSECURE_PREFIX:
            if not self.allow_insecure_fallback:
                raise SecretStoreUnavailableError(
                    "insecure secret requires explicit test fallback"
                )
            return data.decode("utf-8")
        if not self.secure:
            raise SecretStoreUnavailableError(
                "DPAPI secret cannot be opened on this platform"
            )
        try:
            return _dpapi_unprotect(data).decode("utf-8")
        except UnicodeDecodeError as error:
            raise SecretStoreError("protected secret is not UTF-8") from error


__all__ = [
    "DPAPI_PREFIX",
    "INSECURE_PREFIX",
    "SecretStore",
    "SecretStoreError",
    "SecretStoreUnavailableError",
]
