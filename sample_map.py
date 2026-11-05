"""Загрузка явной карты WAV -> MIDI note/pad.

Формат 1 (рекомендуемый):

{
  "samples": [
    {"file": "kicks/kick.wav", "note": 36, "gain": 0.9, "pan": 0.5},
    {"file": "snares/snare.wav", "note": 38, "tune": 0.0, "loop": false}
  ]
}

Формат 2 (компактный, с произвольными метками):

{
  "kick":  {"file": "kick.wav", "note": 36},
  "snare": {"file": "snare.wav", "note": 38}
}
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from errors import ValidationError
from validators import MAX_DRUM_NOTE, MIN_DRUM_NOTE
from wav_pool import PoolSample, WavPool, build_wav_pool, scan_wav_files


@dataclass(frozen=True)
class PadBinding:
    """Один pad: семпл + MIDI note + необязательные параметры."""

    sample: PoolSample
    pad_index: int
    midi_note: int | None
    gain: float | None = None
    pan: float | None = None
    tune: float | None = None
    loop: bool | None = None


@dataclass(frozen=True)
class MapEntry:
    """Строка карты после чтения JSON."""

    label: str
    file: str
    note: int
    gain: float | None = None
    pan: float | None = None
    tune: float | None = None
    loop: bool | None = None
    source: Path | None = None


_ALLOWED_KEYS = {"file", "note", "gain", "pan", "tune", "loop"}


def _number(
    value: Any,
    field: str,
    *,
    minimum: float,
    maximum: float,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"Поле {field} должно быть числом.")
    number = float(value)
    if not math.isfinite(number):
        raise ValidationError(f"Поле {field} должно быть конечным числом.")
    if not minimum <= number <= maximum:
        raise ValidationError(
            f"Поле {field} вне диапазона {minimum:g}..{maximum:g}: {number:g}."
        )
    return number


def _entry(label: str, raw: Any) -> MapEntry:
    if not isinstance(raw, dict):
        raise ValidationError(f"Запись {label!r} в карте должна быть объектом.")
    unknown = set(raw) - _ALLOWED_KEYS
    if unknown:
        raise ValidationError(
            f"Неизвестные поля в записи {label!r}: {', '.join(sorted(unknown))}."
        )
    file_value = raw.get("file")
    if not isinstance(file_value, str) or not file_value.strip():
        raise ValidationError(f"В записи {label!r} не задан file.")
    note_value = raw.get("note")
    if isinstance(note_value, bool) or not isinstance(note_value, int):
        raise ValidationError(f"В записи {label!r} note должен быть целым числом.")
    if not MIN_DRUM_NOTE <= note_value <= MAX_DRUM_NOTE:
        raise ValidationError(
            f"В записи {label!r} note={note_value}; "
            f"допустимо {MIN_DRUM_NOTE}..{MAX_DRUM_NOTE}."
        )

    gain = None if "gain" not in raw else _number(
        raw["gain"], f"{label}.gain", minimum=0.0, maximum=1.0
    )
    pan = None if "pan" not in raw else _number(
        raw["pan"], f"{label}.pan", minimum=0.0, maximum=1.0
    )
    tune = None if "tune" not in raw else _number(
        raw["tune"], f"{label}.tune", minimum=-24.0, maximum=24.0
    )
    loop = raw.get("loop")
    if loop is not None and not isinstance(loop, bool):
        raise ValidationError(f"В записи {label!r} loop должен быть bool.")

    return MapEntry(
        label=label,
        file=file_value.strip(),
        note=note_value,
        gain=gain,
        pan=pan,
        tune=tune,
        loop=loop,
    )


def load_sample_map(path: Path) -> tuple[MapEntry, ...]:
    """Прочитать и провалидировать JSON-карту."""
    if not path.is_file():
        raise ValidationError(f"Файл карты не найден: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Не удалось прочитать карту {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValidationError("Карта семплов должна быть JSON-объектом.")

    entries: list[MapEntry]
    if "samples" in payload:
        raw_entries = payload["samples"]
        if not isinstance(raw_entries, list):
            raise ValidationError("Ключ samples в карте должен быть массивом.")
        entries = [
            _entry(f"samples[{index}]", raw)
            for index, raw in enumerate(raw_entries)
        ]
    else:
        entries = [_entry(label, raw) for label, raw in payload.items()]

    if not entries:
        raise ValidationError("Карта семплов пуста.")

    seen_notes: set[int] = set()
    for entry in entries:
        if entry.note in seen_notes:
            raise ValidationError(f"MIDI note {entry.note} указан в карте дважды.")
        seen_notes.add(entry.note)
    return tuple(entries)


def _normalize_relative(raw: str) -> str:
    text = raw.replace("\\", "/").strip()
    if not text:
        raise ValidationError("Пустой file в карте.")
    path = Path(text)
    if path.is_absolute() or text.startswith("/"):
        raise ValidationError(f"file должен быть относительным путём: {raw!r}.")
    parts = [part for part in text.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise ValidationError(f"file не должен содержать '..': {raw!r}.")
    return "/".join(parts)


def _resolve_sources(
    entries: tuple[MapEntry, ...],
    folder: Path,
) -> tuple[MapEntry, ...]:
    all_wavs = scan_wav_files(folder)
    by_relative = {
        path.relative_to(folder).as_posix().casefold(): path for path in all_wavs
    }
    by_name: dict[str, list[Path]] = {}
    for path in all_wavs:
        by_name.setdefault(path.name.casefold(), []).append(path)

    resolved: list[MapEntry] = []
    for entry in entries:
        relative = _normalize_relative(entry.file)
        source = by_relative.get(relative.casefold())
        if source is None:
            matches = by_name.get(Path(relative).name.casefold(), [])
            if len(matches) == 1:
                source = matches[0]
            elif len(matches) > 1:
                raise ValidationError(
                    f"Файл {entry.file!r} неоднозначен; укажите путь относительно "
                    "папки семплов."
                )
            else:
                raise ValidationError(
                    f"Файл из карты не найден в папке семплов: {entry.file!r}."
                )
        resolved.append(replace(entry, source=source))
    return tuple(resolved)


def prepare_mapped_pool(
    map_path: Path,
    folder: Path,
    note_to_pad: dict[int, int],
) -> tuple[WavPool, tuple[PadBinding, ...]]:
    """Разрешить карту, проверить WAV и построить bindings."""
    entries = _resolve_sources(load_sample_map(map_path), folder)
    selected = {
        entry.source.resolve()
        for entry in entries
        if entry.source is not None
    }
    pool = build_wav_pool(folder, selected=selected)
    by_source = {sample.source.resolve(): sample for sample in pool.samples}

    bindings: list[PadBinding] = []
    used_pads: set[int] = set()
    for entry in entries:
        source = entry.source
        if source is None:
            raise ValidationError(f"Не разрешён путь для {entry.label}.")
        sample = by_source.get(source.resolve())
        if sample is None:
            raise ValidationError(f"Семпл не попал в пул: {source}.")
        pad_index = note_to_pad.get(entry.note)
        if pad_index is None:
            raise ValidationError(
                f"В эталонном .xpj нет pad для MIDI note {entry.note}."
            )
        if pad_index in used_pads:
            raise ValidationError(
                f"MIDI note {entry.note} и другая запись ведут на pad {pad_index}."
            )
        used_pads.add(pad_index)
        bindings.append(
            PadBinding(
                sample=sample,
                pad_index=pad_index,
                midi_note=entry.note,
                gain=entry.gain,
                pan=entry.pan,
                tune=entry.tune,
                loop=entry.loop,
            )
        )
    return pool, tuple(bindings)
