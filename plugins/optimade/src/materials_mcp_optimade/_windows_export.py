"""Handle-bound exclusive export primitives for Windows.

This module is imported only when ``os.name == "nt"``. It opens and verifies
every parent by its final kernel path before creating the destination. Provider
bytes are written only through the verified destination handle.
"""

from __future__ import annotations

import ctypes
import msvcrt
import os
from ctypes import wintypes
from pathlib import Path
from typing import Any, Final, cast

_GENERIC_WRITE: Final = 0x40000000
_DELETE: Final = 0x00010000
_FILE_READ_ATTRIBUTES: Final = 0x00000080
_FILE_SHARE_READ: Final = 0x00000001
_CREATE_NEW: Final = 1
_OPEN_EXISTING: Final = 3
_FILE_ATTRIBUTE_DIRECTORY: Final = 0x00000010
_FILE_ATTRIBUTE_NORMAL: Final = 0x00000080
_FILE_ATTRIBUTE_REPARSE_POINT: Final = 0x00000400
_FILE_FLAG_BACKUP_SEMANTICS: Final = 0x02000000
_FILE_FLAG_OPEN_REPARSE_POINT: Final = 0x00200000
_FILE_ATTRIBUTE_TAG_INFO_CLASS: Final = 9
_FILE_DISPOSITION_INFO_CLASS: Final = 4
_ERROR_FILE_EXISTS: Final = 80
_ERROR_ALREADY_EXISTS: Final = 183
_INVALID_HANDLE_VALUE: Final = cast(int, ctypes.c_void_p(-1).value)


class UnsafeExportPathError(OSError):
    """The opened Windows object did not match the reviewed export path."""


class _FileAttributeTagInfo(ctypes.Structure):
    _fields_ = (("file_attributes", wintypes.DWORD), ("reparse_tag", wintypes.DWORD))


class _FileDispositionInfo(ctypes.Structure):
    _fields_ = (("delete_file", wintypes.BOOL),)


_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_create_file_w = cast(Any, _kernel32.CreateFileW)
_create_file_w.argtypes = (
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.c_void_p,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.HANDLE,
)
_create_file_w.restype = wintypes.HANDLE
_close_handle = cast(Any, _kernel32.CloseHandle)
_close_handle.argtypes = (wintypes.HANDLE,)
_close_handle.restype = wintypes.BOOL
_get_file_information = cast(Any, _kernel32.GetFileInformationByHandleEx)
_get_file_information.argtypes = (
    wintypes.HANDLE,
    ctypes.c_int,
    ctypes.c_void_p,
    wintypes.DWORD,
)
_get_file_information.restype = wintypes.BOOL
_get_final_path = cast(Any, _kernel32.GetFinalPathNameByHandleW)
_get_final_path.argtypes = (wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD)
_get_final_path.restype = wintypes.DWORD
_set_file_information = cast(Any, _kernel32.SetFileInformationByHandle)
_set_file_information.argtypes = (
    wintypes.HANDLE,
    ctypes.c_int,
    ctypes.c_void_p,
    wintypes.DWORD,
)
_set_file_information.restype = wintypes.BOOL


def _last_error(message: str) -> OSError:
    code = ctypes.get_last_error()
    return OSError(code, message)


def _close(handle: int) -> None:
    if not _close_handle(handle):
        raise _last_error("Windows could not close an export handle")


def _attributes(handle: int) -> int:
    info = _FileAttributeTagInfo()
    if not _get_file_information(
        handle,
        _FILE_ATTRIBUTE_TAG_INFO_CLASS,
        ctypes.byref(info),
        ctypes.sizeof(info),
    ):
        raise _last_error("Windows could not inspect an export handle")
    return int(info.file_attributes)


def _final_path(handle: int) -> Path:
    required = int(_get_final_path(handle, None, 0, 0))
    if required <= 0:
        raise _last_error("Windows could not resolve an export handle")
    buffer = ctypes.create_unicode_buffer(required + 1)
    written = int(_get_final_path(handle, buffer, len(buffer), 0))
    if written <= 0 or written >= len(buffer):
        raise _last_error("Windows could not resolve an export handle")
    value = buffer.value
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    return Path(value)


def _normalized(path: Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _open_directory(path: Path) -> int:
    handle = _create_file_w(
        os.fspath(path),
        _FILE_READ_ATTRIBUTES,
        _FILE_SHARE_READ,
        None,
        _OPEN_EXISTING,
        _FILE_FLAG_BACKUP_SEMANTICS | _FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    if handle is None or handle == _INVALID_HANDLE_VALUE:
        raise _last_error("Windows could not open an export directory")
    value = int(handle)
    try:
        attributes = _attributes(value)
    except OSError:
        _close(value)
        raise
    if not attributes & _FILE_ATTRIBUTE_DIRECTORY or attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
        _close(value)
        raise UnsafeExportPathError("Export parent is not a plain directory")
    return value


def _create_destination(path: Path) -> int:
    handle = _create_file_w(
        os.fspath(path),
        _GENERIC_WRITE | _DELETE | _FILE_READ_ATTRIBUTES,
        0,
        None,
        _CREATE_NEW,
        _FILE_ATTRIBUTE_NORMAL | _FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    if handle is None or handle == _INVALID_HANDLE_VALUE:
        code = ctypes.get_last_error()
        if code in {_ERROR_FILE_EXISTS, _ERROR_ALREADY_EXISTS}:
            raise FileExistsError(code, "Export destination already exists", os.fspath(path))
        raise OSError(code, "Windows could not create the export destination")
    return int(handle)


def _delete_on_close(handle: int) -> None:
    disposition = _FileDispositionInfo(wintypes.BOOL(1))
    if not _set_file_information(
        handle,
        _FILE_DISPOSITION_INFO_CLASS,
        ctypes.byref(disposition),
        ctypes.sizeof(disposition),
    ):
        raise _last_error("Windows could not remove an incomplete export")


def _write_descriptor(descriptor: int, content: bytes) -> None:
    offset = 0
    while offset < len(content):
        written = os.write(descriptor, content[offset:])
        if written <= 0:
            raise OSError("Windows returned a zero-length export write")
        offset += written
    os.fsync(descriptor)


def write_exclusive(root: Path, destination: Path, content: bytes) -> None:
    """Create and write ``destination`` beneath ``root`` without path races."""

    relative = destination.relative_to(root)
    parent_parts = relative.parts[:-1]
    guards: list[int] = []
    target_handle: int | None = None
    descriptor: int | None = None
    try:
        root_handle = _open_directory(root)
        guards.append(root_handle)
        root_final = _final_path(root_handle)

        for count in range(1, len(parent_parts) + 1):
            candidate = root.joinpath(*parent_parts[:count])
            guard = _open_directory(candidate)
            guards.append(guard)
            expected = root_final.joinpath(*parent_parts[:count])
            if _normalized(_final_path(guard)) != _normalized(expected):
                raise UnsafeExportPathError("Export parent resolved outside its reviewed path")

        target_handle = _create_destination(destination)
        expected_target = root_final.joinpath(*relative.parts)
        if _normalized(_final_path(target_handle)) != _normalized(expected_target):
            _delete_on_close(target_handle)
            raise UnsafeExportPathError("Export destination resolved outside its reviewed path")

        descriptor = msvcrt.open_osfhandle(target_handle, os.O_WRONLY | os.O_BINARY)
        target_handle = None  # the CRT descriptor now owns the Windows handle
        try:
            _write_descriptor(descriptor, content)
        except OSError:
            _delete_on_close(msvcrt.get_osfhandle(descriptor))
            raise
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if target_handle is not None:
            _close(target_handle)
        for guard in reversed(guards):
            _close(guard)
