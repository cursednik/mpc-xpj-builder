"""MIDI Clock sync через Windows MIDI API без внешних зависимостей."""

from __future__ import annotations

import ctypes
import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable

from errors import ValidationError
from validators import validate_bpm

CLOCK = 0xF8
START = 0xFA
CONTINUE = 0xFB
STOP = 0xFC
PPQN = 24


@dataclass(frozen=True)
class MidiDevice:
    index: int
    name: str


class _MIDIOUTCAPSW(ctypes.Structure):
    _fields_ = [
        ("wMid", ctypes.c_ushort),
        ("wPid", ctypes.c_ushort),
        ("vDriverVersion", ctypes.c_uint),
        ("szPname", ctypes.c_wchar * 32),
        ("wTechnology", ctypes.c_ushort),
        ("wVoices", ctypes.c_ushort),
        ("wNotes", ctypes.c_ushort),
        ("wChannelMask", ctypes.c_ushort),
        ("dwSupport", ctypes.c_uint),
    ]


class MidiOutput:
    """Один Windows MIDI-выход."""

    def __init__(self) -> None:
        self._winmm = None
        self._handle: ctypes.c_void_p | None = None
        self._device_index: int | None = None
        if sys.platform == "win32":
            try:
                self._winmm = ctypes.windll.winmm
                self._configure()
            except Exception:
                self._winmm = None

    @staticmethod
    def available() -> bool:
        return sys.platform == "win32"

    @classmethod
    def list_devices(cls) -> tuple[MidiDevice, ...]:
        if sys.platform != "win32":
            return ()
        try:
            return cls()._list_devices()
        except Exception:
            return ()

    def _configure(self) -> None:
        assert self._winmm is not None
        self._winmm.midiOutGetNumDevs.argtypes = []
        self._winmm.midiOutGetNumDevs.restype = ctypes.c_uint
        self._winmm.midiOutGetDevCapsW.argtypes = [
            ctypes.c_size_t,
            ctypes.POINTER(_MIDIOUTCAPSW),
            ctypes.c_uint,
        ]
        self._winmm.midiOutGetDevCapsW.restype = ctypes.c_uint
        self._winmm.midiOutOpen.argtypes = [
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_uint,
            ctypes.c_size_t,
            ctypes.c_size_t,
            ctypes.c_uint,
        ]
        self._winmm.midiOutOpen.restype = ctypes.c_uint
        self._winmm.midiOutShortMsg.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
        ]
        self._winmm.midiOutShortMsg.restype = ctypes.c_uint
        self._winmm.midiOutClose.argtypes = [ctypes.c_void_p]
        self._winmm.midiOutClose.restype = ctypes.c_uint
        self._winmm.midiOutGetErrorTextW.argtypes = [
            ctypes.c_uint,
            ctypes.c_wchar_p,
            ctypes.c_uint,
        ]
        self._winmm.midiOutGetErrorTextW.restype = ctypes.c_uint

    def _list_devices(self) -> tuple[MidiDevice, ...]:
        assert self._winmm is not None
        count = int(self._winmm.midiOutGetNumDevs())
        devices: list[MidiDevice] = []
        for index in range(count):
            caps = _MIDIOUTCAPSW()
            result = self._winmm.midiOutGetDevCapsW(
                index,
                ctypes.byref(caps),
                ctypes.sizeof(caps),
            )
            if result == 0:
                devices.append(MidiDevice(index=index, name=caps.szPname))
        return tuple(devices)

    def open(self, device_index: int) -> None:
        if sys.platform != "win32" or self._winmm is None:
            raise RuntimeError("MIDI доступен только на Windows.")
        if self._handle is not None:
            self.close()
        handle = ctypes.c_void_p()
        result = self._winmm.midiOutOpen(
            ctypes.byref(handle),
            int(device_index),
            0,
            0,
            0,
        )
        if result != 0:
            raise RuntimeError(self._error_text(result))
        self._handle = handle
        self._device_index = int(device_index)

    def send(self, status: int) -> None:
        if self._handle is None or self._winmm is None:
            raise RuntimeError("MIDI-выход не открыт.")
        result = self._winmm.midiOutShortMsg(self._handle, status & 0xFF)
        if result != 0:
            raise RuntimeError(self._error_text(result))

    def close(self) -> None:
        if self._handle is not None and self._winmm is not None:
            try:
                self._winmm.midiOutClose(self._handle)
            except Exception:
                pass
        self._handle = None
        self._device_index = None

    def _error_text(self, code: int) -> str:
        if self._winmm is None:
            return f"MIDI error {code}"
        buffer = ctypes.create_unicode_buffer(512)
        result = self._winmm.midiOutGetErrorTextW(code, buffer, len(buffer))
        if result == 0 and buffer.value:
            return buffer.value
        return f"MIDI error {code}"

    def __enter__(self) -> "MidiOutput":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def __del__(self) -> None:
        self.close()


class ClockEngine:
    """Отправляет MIDI Clock/Start/Stop в фоновом потоке."""

    def __init__(
        self,
        output: MidiOutput,
        bpm: float,
        *,
        clock: Callable[[], float] = time.perf_counter,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.output = output
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._bpm = validate_bpm(bpm)
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._pulses = 0
        self._last_error: Exception | None = None

    @staticmethod
    def interval_for_bpm(bpm: float) -> float:
        value = validate_bpm(bpm)
        return 60.0 / (value * PPQN)

    @property
    def bpm(self) -> float:
        with self._lock:
            return self._bpm

    def set_bpm(self, bpm: float) -> None:
        value = validate_bpm(bpm)
        with self._lock:
            self._bpm = value

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def pulses(self) -> int:
        return self._pulses

    @property
    def last_error(self) -> Exception | None:
        return self._last_error

    def start(self) -> None:
        if self.running:
            return
        self._last_error = None
        self._pulses = 0
        self._stop_event.clear()
        self.output.send(START)
        self._thread = threading.Thread(
            target=self._run,
            name="midi-clock",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        thread = self._thread
        if thread is None:
            return
        self._stop_event.set()
        thread.join(timeout=1.0)
        self._thread = None
        try:
            self.output.send(STOP)
        except Exception:
            pass

    def send_continue(self) -> None:
        self.output.send(CONTINUE)

    def _run(self) -> None:
        next_tick = self._clock()
        while not self._stop_event.is_set():
            interval = self.interval_for_bpm(self.bpm)
            now = self._clock()
            if now < next_tick:
                remaining = next_tick - now
                if remaining > 0.001:
                    self._sleep(remaining - 0.0008)
                while not self._stop_event.is_set() and self._clock() < next_tick:
                    pass
            if self._stop_event.is_set():
                break
            try:
                self.output.send(CLOCK)
            except Exception as exc:
                self._last_error = exc
                break
            self._pulses += 1
            next_tick += interval
            if next_tick < self._clock() - interval:
                next_tick = self._clock() + interval
