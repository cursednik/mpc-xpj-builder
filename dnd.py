"""Windows drag-and-drop файлов в главное окно."""

from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

_WM_DROPFILES = 0x0233
_GWLP_WNDPROC = -4


@dataclass(frozen=True)
class DropResult:
    samples: Path | None = None
    midi: Path | None = None
    template: Path | None = None
    sample_map: Path | None = None
    unsupported: tuple[Path, ...] = ()
    midi_files: tuple[Path, ...] = ()

    @property
    def has_any(self) -> bool:
        return any(
            (self.samples, self.midi, self.template, self.sample_map)
        )


def route_dropped(paths: list[str] | tuple[str, ...]) -> DropResult:
    """Разложить упавшие пути по полям GUI."""
    samples: Path | None = None
    midi_files: list[Path] = []
    template: Path | None = None
    sample_map: Path | None = None
    unsupported: list[Path] = []

    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            if samples is None:
                samples = path
            continue
        suffix = path.suffix.lower()
        if suffix == ".wav":
            if samples is None:
                samples = path.parent
        elif suffix in {".mid", ".midi"}:
            midi_files.append(path)
        elif suffix == ".xpj":
            if template is None:
                template = path
        elif suffix == ".json":
            if sample_map is None:
                sample_map = path
        else:
            unsupported.append(path)

    return DropResult(
        samples=samples,
        midi=midi_files[0] if midi_files else None,
        template=template,
        sample_map=sample_map,
        unsupported=tuple(unsupported),
        midi_files=tuple(midi_files),
    )


class _DropState:
    def __init__(self, hwnd: int, callback: Callable[[list[str]], None]) -> None:
        self.hwnd = hwnd
        self.callback = callback
        self.old_proc: int | None = None
        self.wndproc = None


def _enable_windows_drop(
    root,
    callback: Callable[[list[str]], None],
) -> bool:
    try:
        from ctypes import wintypes
    except ImportError:
        return False

    user32 = ctypes.windll.user32
    shell32 = ctypes.windll.shell32
    root.update_idletasks()
    # Tk child window is the one that receives the actual drop. This mirrors
    # the approach used by the long-standing windnd implementation.
    hwnd = root.winfo_id()
    if not hwnd:
        return False
    state = _DropState(hwnd, callback)

    lresult = ctypes.c_ssize_t
    wndproc_type = ctypes.WINFUNCTYPE(
        lresult,
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    )

    user32.CallWindowProcW.argtypes = [
        ctypes.c_void_p,
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    user32.CallWindowProcW.restype = lresult
    shell32.DragQueryFileW.argtypes = [
        wintypes.HANDLE,
        wintypes.UINT,
        wintypes.LPWSTR,
        wintypes.UINT,
    ]
    shell32.DragQueryFileW.restype = wintypes.UINT
    shell32.DragFinish.argtypes = [wintypes.HANDLE]
    shell32.DragFinish.restype = None
    shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
    shell32.DragAcceptFiles.restype = None

    def wndproc(hwnd_value, message, wparam, lparam):
        if message == _WM_DROPFILES:
            try:
                hdrop = wintypes.HANDLE(wparam)
                count = shell32.DragQueryFileW(hdrop, 0xFFFFFFFF, None, 0)
                paths: list[str] = []
                for index in range(count):
                    length = shell32.DragQueryFileW(hdrop, index, None, 0)
                    buffer = ctypes.create_unicode_buffer(length + 1)
                    shell32.DragQueryFileW(hdrop, index, buffer, length + 1)
                    paths.append(buffer.value)
                shell32.DragFinish(hdrop)
                callback(paths)
            except Exception:
                pass
        return user32.CallWindowProcW(
            state.old_proc,
            hwnd_value,
            message,
            wparam,
            lparam,
        )

    state.wndproc = wndproc_type(wndproc)
    user32.SetWindowLongPtrW.argtypes = [
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_void_p,
    ]
    user32.SetWindowLongPtrW.restype = ctypes.c_void_p
    old = user32.SetWindowLongPtrW(
        hwnd,
        _GWLP_WNDPROC,
        ctypes.cast(state.wndproc, ctypes.c_void_p),
    )
    if not old:
        return False
    state.old_proc = old
    shell32.DragAcceptFiles(hwnd, True)
    root._file_drop_state = state  # type: ignore[attr-defined]
    return True


def enable_file_drop(root, callback: Callable[[list[str]], None]) -> bool:
    """Включить приём файлов; на не-Windows вернуть False."""
    if sys.platform != "win32":
        return False
    try:
        return _enable_windows_drop(root, callback)
    except Exception:
        return False


def disable_file_drop(root) -> None:
    state = getattr(root, "_file_drop_state", None)
    if state is None:
        return
    try:
        user32 = ctypes.windll.user32
        user32.DragAcceptFiles(state.hwnd, False)
        user32.SetWindowLongPtrW(
            state.hwnd,
            _GWLP_WNDPROC,
            ctypes.c_void_p(state.old_proc),
        )
    except Exception:
        pass
    finally:
        root._file_drop_state = None  # type: ignore[attr-defined]
