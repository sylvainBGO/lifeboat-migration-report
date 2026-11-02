"""Filesystem paths with explicit Win32 long-path support.

Keep display/manifest paths ordinary. Only the OS path protocol adds the
extended prefix, so no registry change or administrator rights are needed.
"""
from __future__ import annotations
import ntpath
import os
from pathlib import Path as StandardPath, WindowsPath, PurePath


def ordinary_windows_path(value: str) -> str:
    if value.startswith('\\\\?\\UNC\\'):
        return '\\\\' + value[8:]
    if value.startswith('\\\\?\\') and len(value) > 5 and value[5] == ':':
        return value[4:]
    return value


def extended_windows_path(value: str) -> str:
    if value.startswith(('\\\\?\\', '\\\\.\\')):
        return value
    # Resolve relative paths before using extended syntax (which treats .. literally).
    absolute = ntpath.abspath(value)
    if absolute.startswith('\\\\'):
        return '\\\\?\\UNC\\' + absolute[2:]
    if ntpath.isabs(absolute) and ntpath.splitdrive(absolute)[0]:
        return '\\\\?\\' + absolute
    return absolute


class LongWindowsPath(WindowsPath):
    def __init__(self, *args):
        super().__init__(*(ordinary_windows_path(str(arg) if isinstance(arg, PurePath) else os.fspath(arg)) for arg in args))

    def __fspath__(self) -> str:
        value = str(self)
        return extended_windows_path(value) if self.is_absolute() else value


Path = LongWindowsPath if os.name == 'nt' else StandardPath


def sqlite_uri(path, immutable=False):
    import urllib.parse
    value = os.fspath(Path(path).resolve())
    encoded = urllib.parse.quote(value, safe="/:")
    return f"file:{encoded}?mode=ro" + ("&immutable=1" if immutable else "")
