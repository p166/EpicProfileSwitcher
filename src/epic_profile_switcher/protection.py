"""Windows user-scoped encryption for saved launcher sessions."""

from __future__ import annotations

import ctypes
import os
from ctypes import POINTER, byref, c_byte, c_void_p, create_string_buffer, sizeof, string_at
from ctypes.wintypes import BOOL, DWORD, LPWSTR


class DataBlob(ctypes.Structure):
    _fields_ = [("cbData", DWORD), ("pbData", POINTER(c_byte))]


class DpapiProtector:
    """Protect profile files so only the current Windows user can decrypt them."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise OSError("Windows DPAPI is required to protect profile snapshots.")

        self._crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._crypt32.CryptProtectData.argtypes = [
            POINTER(DataBlob), LPWSTR, POINTER(DataBlob), c_void_p, c_void_p, DWORD,
            POINTER(DataBlob),
        ]
        self._crypt32.CryptProtectData.restype = BOOL
        self._crypt32.CryptUnprotectData.argtypes = [
            POINTER(DataBlob), POINTER(LPWSTR), POINTER(DataBlob), c_void_p, c_void_p,
            DWORD, POINTER(DataBlob),
        ]
        self._crypt32.CryptUnprotectData.restype = BOOL
        self._kernel32.LocalFree.argtypes = [c_void_p]
        self._kernel32.LocalFree.restype = c_void_p

    @staticmethod
    def _blob(data: bytes) -> tuple[DataBlob, ctypes.Array[ctypes.c_char]]:
        buffer = create_string_buffer(data, max(1, len(data)))
        blob = DataBlob(len(data), ctypes.cast(buffer, POINTER(c_byte)))
        return blob, buffer

    def protect(self, data: bytes) -> bytes:
        source, keepalive = self._blob(data)
        result = DataBlob()
        if not self._crypt32.CryptProtectData(
            byref(source), "Epic Profile Switcher", None, None, None, 0, byref(result)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return string_at(result.pbData, result.cbData)
        finally:
            self._kernel32.LocalFree(result.pbData)
            del keepalive

    def unprotect(self, data: bytes) -> bytes:
        source, keepalive = self._blob(data)
        result = DataBlob()
        description = LPWSTR()
        if not self._crypt32.CryptUnprotectData(
            byref(source), byref(description), None, None, None, 0, byref(result)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return string_at(result.pbData, result.cbData)
        finally:
            self._kernel32.LocalFree(result.pbData)
            if description:
                self._kernel32.LocalFree(description)
            del keepalive