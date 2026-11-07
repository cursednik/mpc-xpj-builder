from __future__ import annotations

import ctypes
import sys
import tempfile
import tkinter as tk
import unittest
from ctypes import wintypes
from pathlib import Path

from dnd import disable_file_drop, enable_file_drop

WM_DROPFILES = 0x0233


class _DROPFILES(ctypes.Structure):
    _fields_ = [
        ("pFiles", wintypes.DWORD),
        ("pt", wintypes.POINT),
        ("fNC", wintypes.BOOL),
        ("fWide", wintypes.BOOL),
    ]


def _make_hdrop(paths: list[str]):
    kernel32 = ctypes.windll.kernel32
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]

    files = "\0".join(paths) + "\0\0"
    data = files.encode("utf-16-le")
    size = ctypes.sizeof(_DROPFILES) + len(data)
    handle = kernel32.GlobalAlloc(0x0042, size)
    pointer = kernel32.GlobalLock(handle)
    header = _DROPFILES(
        ctypes.sizeof(_DROPFILES),
        wintypes.POINT(0, 0),
        False,
        True,
    )
    ctypes.memmove(pointer, ctypes.byref(header), ctypes.sizeof(header))
    ctypes.memmove(
        pointer + ctypes.sizeof(header),
        data,
        len(data),
    )
    kernel32.GlobalUnlock(handle)
    return handle


@unittest.skipUnless(sys.platform == "win32", "Windows only")
class NativeDropTests(unittest.TestCase):
    def test_synthetic_wm_dropfiles(self) -> None:
        user32 = ctypes.windll.user32
        user32.SendMessageW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        user32.SendMessageW.restype = ctypes.c_ssize_t

        root = tk.Tk()
        root.title("DND Test")
        received: list[str] = []
        try:
            enabled = enable_file_drop(root, lambda paths: received.extend(paths))
            if not enabled:
                self.skipTest("file drop is not available")
            root.update()
            hwnd = root.winfo_id()
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
                path = Path(handle.name)
                handle.write(b"RIFF")
            try:
                hdrop = _make_hdrop([str(path)])
                user32.SendMessageW(hwnd, WM_DROPFILES, hdrop, 0)
                root.update()
            finally:
                path.unlink(missing_ok=True)
        finally:
            disable_file_drop(root)
            root.destroy()

        self.assertEqual(received, [str(path)])


if __name__ == "__main__":
    unittest.main()
