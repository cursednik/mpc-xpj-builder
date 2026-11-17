"""USB-аудио: запись и мониторинг через sounddevice (PortAudio)."""

from __future__ import annotations

import importlib.util
import threading
import wave
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class AudioDevice:
    index: int
    name: str
    hostapi: str
    max_input_channels: int
    max_output_channels: int
    default_samplerate: float

    @property
    def label(self) -> str:
        return f"{self.name} · {self.hostapi}"

    @property
    def is_input(self) -> bool:
        return self.max_input_channels > 0

    @property
    def is_output(self) -> bool:
        return self.max_output_channels > 0


def dependency_available() -> bool:
    return importlib.util.find_spec("sounddevice") is not None


def list_devices() -> tuple[AudioDevice, ...]:
    """Список аудиоустройств Windows. Требует sounddevice."""
    if not dependency_available():
        raise RuntimeError(
            "Для USB Audio установите sounddevice: pip install sounddevice"
        )
    import sounddevice as sd

    devices: list[AudioDevice] = []
    try:
        host_apis = sd.query_hostapis()
        for index, info in enumerate(sd.query_devices()):
            hostapi_index = info.get("hostapi", 0)
            hostapi = (
                host_apis[hostapi_index]["name"]
                if 0 <= hostapi_index < len(host_apis)
                else ""
            )
            devices.append(
                AudioDevice(
                    index=index,
                    name=str(info.get("name", f"Device {index}")),
                    hostapi=str(hostapi),
                    max_input_channels=int(info.get("max_input_channels", 0)),
                    max_output_channels=int(info.get("max_output_channels", 0)),
                    default_samplerate=float(info.get("default_samplerate", 44100)),
                )
            )
    except Exception as exc:
        raise RuntimeError(f"Не удалось получить аудиоустройства: {exc}") from exc
    return tuple(devices)


def pick_mpc_input(devices: tuple[AudioDevice, ...]) -> AudioDevice | None:
    """Выбрать вход MPC Sample, предпочитая WASAPI."""
    inputs = [device for device in devices if device.is_input]
    if not inputs:
        return None
    mpc = [device for device in inputs if "mpc sample" in device.name.casefold()]
    if mpc:
        wasapi = [device for device in mpc if "wasapi" in device.hostapi.casefold()]
        return (wasapi or mpc)[0]
    return inputs[0]


def peak_percent(data: bytes) -> float:
    """Пиковый уровень int16 PCM в процентах."""
    if not data:
        return 0.0
    samples = array("h")
    samples.frombytes(data[: len(data) - (len(data) % 2)])
    if not samples:
        return 0.0
    peak = max(abs(value) for value in samples)
    return min(100.0, peak / 32768.0 * 100.0)


class AudioSession:
    """Запись и/или мониторинг аудиопотока в фоновом потоке."""

    def __init__(self, *, blocksize: int = 1024) -> None:
        self.blocksize = blocksize
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._peak = 0.0
        self._frames = 0
        self.error: Exception | None = None
        self.recorded_path: Path | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def peak(self) -> float:
        return self._peak

    @property
    def frames(self) -> int:
        return self._frames

    @property
    def seconds(self) -> float:
        return self._frames / self._sample_rate if getattr(self, "_sample_rate", 0) else 0.0

    def start(
        self,
        *,
        input_device: int,
        output_device: int | None,
        sample_rate: int,
        channels: int,
        wav_path: Path | None = None,
    ) -> None:
        if self.running:
            return
        self.error = None
        self._peak = 0.0
        self._frames = 0
        self._sample_rate = sample_rate
        self.recorded_path = Path(wav_path) if wav_path else None
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            kwargs={
                "input_device": input_device,
                "output_device": output_device,
                "sample_rate": sample_rate,
                "channels": channels,
                "wav_path": self.recorded_path,
            },
            name="usb-audio",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
        self._peak = 0.0

    def _run(
        self,
        *,
        input_device: int,
        output_device: int | None,
        sample_rate: int,
        channels: int,
        wav_path: Path | None,
    ) -> None:
        wave_file: wave.Wave_write | None = None
        input_stream = None
        output_stream = None
        try:
            import sounddevice as sd

            input_stream = sd.RawInputStream(
                samplerate=sample_rate,
                blocksize=self.blocksize,
                device=input_device,
                channels=channels,
                dtype="int16",
            )
            if output_device is not None:
                output_stream = sd.RawOutputStream(
                    samplerate=sample_rate,
                    blocksize=self.blocksize,
                    device=output_device,
                    channels=channels,
                    dtype="int16",
                )
            input_stream.start()
            if output_stream is not None:
                output_stream.start()

            if wav_path is not None:
                wave_file = wave.open(str(wav_path), "wb")
                wave_file.setnchannels(channels)
                wave_file.setsampwidth(2)
                wave_file.setframerate(sample_rate)

            while not self._stop_event.is_set():
                data, _overflowed = input_stream.read(self.blocksize)
                self._peak = peak_percent(data)
                self._frames += self.blocksize
                if wave_file is not None:
                    wave_file.writeframes(data)
                if output_stream is not None:
                    output_stream.write(data)
        except Exception as exc:
            self.error = exc
        finally:
            for stream in (output_stream, input_stream):
                if stream is not None:
                    try:
                        stream.stop()
                        stream.close()
                    except Exception:
                        pass
            if wave_file is not None:
                try:
                    wave_file.close()
                except Exception:
                    pass
            self._peak = 0.0
