"""Прослушивание WAV-семплов без внешних зависимостей."""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path


class AudioPreview:
    """Короткое прослушивание WAV через MCI или winsound."""

    def __init__(self) -> None:
        self._alias: str | None = None
        self._backend: str | None = None
        self._winmm = None
        if sys.platform == "win32":
            try:
                self._winmm = ctypes.windll.winmm
                self._winmm.mciSendStringW.argtypes = [
                    ctypes.c_wchar_p,
                    ctypes.c_wchar_p,
                    ctypes.c_uint,
                    ctypes.c_void_p,
                ]
                self._winmm.mciSendStringW.restype = ctypes.c_uint
                self._winmm.mciGetErrorStringW.argtypes = [
                    ctypes.c_uint,
                    ctypes.c_wchar_p,
                    ctypes.c_uint,
                ]
                self._winmm.mciGetErrorStringW.restype = ctypes.c_int
            except Exception:
                self._winmm = None

    @property
    def available(self) -> bool:
        return sys.platform == "win32"

    def play(self, path: Path) -> float | None:
        """Начать воспроизведение. Возвращает длительность в секундах, если известна."""
        self.stop()
        if sys.platform != "win32":
            raise RuntimeError("Прослушивание WAV доступно только на Windows.")
        target = Path(path)
        if not target.is_file():
            raise RuntimeError(f"WAV-файл не найден: {target}")

        mci_error: Exception | None = None
        if self._winmm is not None:
            try:
                return self._play_mci(target)
            except Exception as exc:
                mci_error = exc
                self._close_mci()

        try:
            return self._play_winsound(target)
        except Exception as exc:
            message = str(mci_error or exc)
            raise RuntimeError(f"Не удалось прослушать WAV: {message}") from exc

    def stop(self) -> None:
        """Остановить текущее воспроизведение, если оно есть."""
        if self._backend == "mci":
            self._close_mci()
        elif self._backend == "winsound":
            try:
                import winsound

                winsound.PlaySound(None, 0)
            except Exception:
                pass
        self._backend = None

    def _play_mci(self, path: Path) -> float | None:
        assert self._winmm is not None
        self._alias = f"mpcxpj{id(self) % 100000}"
        self._mci(f'open "{path}" type waveaudio alias {self._alias}')
        length_text = self._mci(f"status {self._alias} length")
        self._mci(f"play {self._alias} from 0")
        self._backend = "mci"
        if length_text.strip().isdigit():
            return int(length_text.strip()) / 1000.0
        return None

    def _play_winsound(self, path: Path) -> float | None:
        import winsound

        winsound.PlaySound(
            str(path),
            winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
        )
        self._backend = "winsound"
        return None

    def _mci(self, command: str) -> str:
        assert self._winmm is not None
        buffer = ctypes.create_unicode_buffer(1024)
        result = self._winmm.mciSendStringW(command, buffer, len(buffer), None)
        if result != 0:
            error = ctypes.create_unicode_buffer(512)
            self._winmm.mciGetErrorStringW(result, error, len(error))
            raise RuntimeError(error.value or f"MCI error {result}")
        return buffer.value

    def _close_mci(self) -> None:
        if self._alias is None or self._winmm is None:
            self._alias = None
            return
        try:
            self._mci(f"close {self._alias}")
        except Exception:
            pass
        self._alias = None
