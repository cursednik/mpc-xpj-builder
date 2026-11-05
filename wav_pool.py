"""Сканирование, валидация и безопасные имена WAV-семплов."""

from __future__ import annotations

import re
import struct
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from errors import ValidationError
from validators import MAX_SAMPLES, validate_sample_count

MAX_SAMPLE_STEM_LENGTH = 40
_SUPPORTED_BITS = {8, 16, 24, 32}
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9_]+")


@dataclass(frozen=True)
class WavInfo:
    """Проверенные параметры WAV-файла."""

    path: Path
    frames: int
    channels: int
    sample_rate: int
    bits_per_sample: int
    codec: str


@dataclass(frozen=True)
class PoolSample:
    """Один семпл в пуле проекта."""

    source: Path
    output_name: str
    display_name: str
    info: WavInfo


@dataclass(frozen=True)
class WavPool:
    """Результат сканирования папки семплов."""

    samples: tuple[PoolSample, ...]

    @property
    def count(self) -> int:
        return len(self.samples)


def scan_wav_files(folder: Path) -> tuple[Path, ...]:
    """Найти WAV-файлы рекурсивно и вернуть их в стабильном порядке."""
    files = sorted(
        (
            path
            for path in folder.rglob("*")
            if path.is_file() and path.suffix.lower() == ".wav"
        ),
        key=lambda path: (str(path.relative_to(folder)).casefold(), path.name),
    )
    return tuple(files)


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    data = stream.read(size)
    if len(data) != size:
        raise ValueError("неожиданный конец файла")
    return data


def inspect_wav(path: Path) -> WavInfo:
    """Прочитать RIFF/WAVE-заголовок без декодирования аудиоданных."""
    if not path.is_file():
        raise ValidationError(f"WAV-файл не найден: {path}")

    try:
        file_size = path.stat().st_size
        if file_size < 20:
            raise ValueError("файл слишком короткий")

        with path.open("rb") as stream:
            riff = _read_exact(stream, 4)
            if riff != b"RIFF":
                raise ValueError("нет сигнатуры RIFF")
            _read_exact(stream, 4)  # размер RIFF, часто неточный
            wave = _read_exact(stream, 4)
            if wave != b"WAVE":
                raise ValueError("нет сигнатуры WAVE")

            fmt: tuple[int, int, int, int, int, int] | None = None
            data_size: int | None = None
            offset = 12

            while offset + 8 <= file_size:
                stream.seek(offset)
                chunk_id = _read_exact(stream, 4)
                chunk_size = struct.unpack("<I", _read_exact(stream, 4))[0]
                body_start = offset + 8
                if body_start + chunk_size > file_size:
                    raise ValueError(
                        f"chunk {chunk_id!r} выходит за границы файла"
                    )

                if chunk_id == b"fmt ":
                    if chunk_size < 16:
                        raise ValueError("слишком короткий fmt chunk")
                    body = _read_exact(stream, min(chunk_size, 64))
                    (
                        audio_format,
                        channels,
                        sample_rate,
                        _byte_rate,
                        block_align,
                        bits_per_sample,
                    ) = struct.unpack("<HHIIHH", body[:16])

                    if audio_format == 0xFFFE:
                        if chunk_size < 40 or len(body) < 40:
                            raise ValueError(
                                "WAVEFORMATEXTENSIBLE без SubFormat GUID"
                            )
                        audio_format = struct.unpack("<H", body[24:26])[0]

                    fmt = (
                        audio_format,
                        channels,
                        sample_rate,
                        block_align,
                        bits_per_sample,
                        chunk_size,
                    )

                elif chunk_id == b"data":
                    data_size = chunk_size

                offset = body_start + chunk_size + (chunk_size & 1)

    except (OSError, ValueError, struct.error) as exc:
        raise ValidationError(f"Некорректный WAV {path}: {exc}") from exc

    if fmt is None:
        raise ValidationError(f"Некорректный WAV {path}: отсутствует fmt chunk.")
    if data_size is None or data_size <= 0:
        raise ValidationError(f"Некорректный WAV {path}: отсутствует data chunk.")

    audio_format, channels, sample_rate, block_align, bits, _ = fmt
    if audio_format == 1:
        codec = "PCM"
    elif audio_format == 3:
        codec = "IEEE float"
    else:
        raise ValidationError(
            f"Некорректный WAV {path}: поддерживается только PCM/IEEE float, "
            f"найден format={audio_format}."
        )
    if channels not in {1, 2}:
        raise ValidationError(
            f"Некорректный WAV {path}: поддерживается mono/stereo, найдено каналов: {channels}."
        )
    if not 8_000 <= sample_rate <= 192_000:
        raise ValidationError(
            f"Некорректный WAV {path}: неподдерживаемая частота {sample_rate} Hz."
        )
    if bits not in _SUPPORTED_BITS:
        raise ValidationError(
            f"Некорректный WAV {path}: неподдерживаемая разрядность {bits} bit."
        )
    if audio_format == 3 and bits != 32:
        raise ValidationError(
            f"Некорректный WAV {path}: IEEE float поддерживается только 32-bit."
        )
    if block_align <= 0:
        raise ValidationError(f"Некорректный WAV {path}: blockAlign <= 0.")
    expected_align = channels * ((bits + 7) // 8)
    if block_align != expected_align:
        raise ValidationError(
            f"Некорректный WAV {path}: blockAlign={block_align}, "
            f"ожидалось {expected_align}."
        )
    if data_size % block_align:
        raise ValidationError(
            f"Некорректный WAV {path}: размер data не кратен blockAlign."
        )

    frames = data_size // block_align
    if frames <= 0:
        raise ValidationError(f"Некорректный WAV {path}: нет аудиофреймов.")

    return WavInfo(
        path=path,
        frames=frames,
        channels=channels,
        sample_rate=sample_rate,
        bits_per_sample=bits,
        codec=codec,
    )


def sanitize_sample_stem(stem: str) -> str:
    """Сделать ASCII-имя без пробелов и спецсимволов."""
    normalized = unicodedata.normalize("NFKD", stem)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    cleaned = _UNSAFE_CHARS.sub("_", ascii_text).strip("_")
    if not cleaned:
        cleaned = "sample"
    if cleaned.upper() in _WINDOWS_RESERVED:
        cleaned = f"s_{cleaned}"
    cleaned = cleaned[:MAX_SAMPLE_STEM_LENGTH].rstrip("_")
    return cleaned or "sample"


def _unique_stem(base: str, used: set[str]) -> str:
    candidate = base
    if candidate.casefold() not in used:
        used.add(candidate.casefold())
        return candidate

    for index in range(1, 10_000):
        suffix = f"_{index:02d}"
        prefix = base[: max(1, MAX_SAMPLE_STEM_LENGTH - len(suffix))].rstrip("_")
        candidate = f"{prefix or 'sample'}{suffix}"
        if candidate.casefold() not in used:
            used.add(candidate.casefold())
            return candidate

    raise ValidationError("Не удалось подобрать уникальное имя WAV-семпла.")


def build_wav_pool(
    folder: Path,
    *,
    selected: set[Path] | None = None,
) -> WavPool:
    """Проверить WAV-файлы и назначить им безопасные уникальные имена.

    Если selected задан, обрабатываются только эти пути (после resolve).
    Это позволяет использовать большую папку семплов с явной картой.
    """
    files = scan_wav_files(folder)
    if selected is not None:
        resolved = {path.resolve() for path in selected}
        files = tuple(path for path in files if path.resolve() in resolved)
    validate_sample_count(len(files))
    if len(files) > MAX_SAMPLES:
        raise ValidationError(
            f"Найдено {len(files)} WAV-файлов; поддерживается не более {MAX_SAMPLES}."
        )

    used_names: set[str] = set()
    samples: list[PoolSample] = []

    for source in files:
        info = inspect_wav(source)
        stem = sanitize_sample_stem(source.stem)
        unique_stem = _unique_stem(stem, used_names)
        samples.append(
            PoolSample(
                source=source,
                output_name=f"{unique_stem}.wav",
                display_name=unique_stem,
                info=info,
            )
        )

    return WavPool(samples=tuple(samples))
