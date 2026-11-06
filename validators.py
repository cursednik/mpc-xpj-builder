"""Проверки пользовательских аргументов и путей."""

from __future__ import annotations

import math
import re
from pathlib import Path

from errors import ValidationError

MAX_SAMPLES = 128
MIN_DRUM_NOTE = 35
MAX_DRUM_NOTE = 51
MIN_EXTENDED_NOTE = 0
MAX_EXTENDED_NOTE = 127
MIN_BPM = 20.0
MAX_BPM = 300.0
PPQ = 960
PROJECT_DATA_SUFFIX = "_[ProjectData]"
MAX_PROJECT_NAME_LENGTH = 80
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_INVALID_PROJECT_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def validate_project_name(raw_name: str) -> str:
    """Проверить и нормализовать имя проекта."""
    name = raw_name.strip()
    if name.lower().endswith(".xpj"):
        name = name[:-4].rstrip()
    if not name:
        raise ValidationError("Имя проекта не может быть пустым.")
    if len(name) > MAX_PROJECT_NAME_LENGTH:
        raise ValidationError(
            f"Имя проекта слишком длинное (максимум {MAX_PROJECT_NAME_LENGTH} символов)."
        )
    if _INVALID_PROJECT_CHARS.search(name):
        raise ValidationError(
            'Имя проекта содержит недопустимые символы: <>:"/\\|?* или управляющие символы.'
        )
    if name.endswith((".", " ")):
        raise ValidationError("Имя проекта не может заканчиваться точкой или пробелом.")
    if name.upper().split(".")[0] in _WINDOWS_RESERVED:
        raise ValidationError(f"Имя проекта зарезервировано Windows: {name!r}.")
    return name


def validate_bpm(raw_bpm: float) -> float:
    """Проверить диапазон и конечность BPM."""
    try:
        bpm = float(raw_bpm)
    except (TypeError, ValueError) as exc:
        raise ValidationError("BPM должен быть числом.") from exc
    if not math.isfinite(bpm):
        raise ValidationError("BPM должен быть конечным числом.")
    if not MIN_BPM <= bpm <= MAX_BPM:
        raise ValidationError(
            f"BPM вне поддерживаемого диапазона {MIN_BPM:g}..{MAX_BPM:g}: {bpm:g}."
        )
    return bpm


def validate_sample_count(count: int) -> None:
    """Проверить количество WAV-семплов."""
    if count < 1:
        raise ValidationError("В папке не найдено ни одного WAV-файла.")
    if count > MAX_SAMPLES:
        raise ValidationError(
            f"Найдено {count} WAV-файлов; поддерживается не более {MAX_SAMPLES}."
        )


def validate_note_range(
    pitches: set[int] | list[int] | tuple[int, ...],
    *,
    extended: bool = False,
) -> None:
    """Разрешить drum-ноты 35..51 или, в extended-режиме, 0..127."""
    minimum = MIN_EXTENDED_NOTE if extended else MIN_DRUM_NOTE
    maximum = MAX_EXTENDED_NOTE if extended else MAX_DRUM_NOTE
    invalid = sorted(
        pitch for pitch in set(pitches) if not minimum <= pitch <= maximum
    )
    if invalid:
        shown = ", ".join(str(pitch) for pitch in invalid[:16])
        suffix = "..." if len(invalid) > 16 else ""
        mode = "0..127" if extended else f"{MIN_DRUM_NOTE}..{MAX_DRUM_NOTE}"
        raise ValidationError(
            f"Поддерживаются только MIDI-ноты {mode}. "
            f"Найдены неподдерживаемые ноты: {shown}{suffix}."
        )


def validate_sample_directory(path: Path) -> Path:
    """Проверить, что папка с семплами существует."""
    if not path.exists():
        raise ValidationError(f"Папка с семплами не найдена: {path}")
    if not path.is_dir():
        raise ValidationError(f"Путь к семплам не является папкой: {path}")
    return path


def validate_midi_path(path: Path) -> Path:
    """Проверить путь к MIDI-файлу."""
    if not path.exists():
        raise ValidationError(f"MIDI-файл не найден: {path}")
    if not path.is_file():
        raise ValidationError(f"Путь к MIDI не является файлом: {path}")
    if path.suffix.lower() not in {".mid", ".midi"}:
        raise ValidationError("Ожидается файл с расширением .mid или .midi.")
    return path


def validate_template_path(path: Path | None) -> Path | None:
    """Проверить необязательный эталонный .xpj."""
    if path is None:
        return None
    if not path.exists():
        raise ValidationError(f"Эталонный .xpj не найден: {path}")
    if not path.is_file():
        raise ValidationError(f"Путь к эталону не является файлом: {path}")
    return path


def validate_map_path(path: Path | None) -> Path | None:
    """Проверить необязательный JSON-файл карты семплов."""
    if path is None:
        return None
    if not path.exists():
        raise ValidationError(f"Файл карты не найден: {path}")
    if not path.is_file():
        raise ValidationError(f"Путь к карте не является файлом: {path}")
    if path.suffix.lower() != ".json":
        raise ValidationError("Карта семплов должна быть .json.")
    return path


def validate_output_dir(path: Path) -> Path:
    """Проверить целевую папку (она может ещё не существовать)."""
    if path.exists() and not path.is_dir():
        raise ValidationError(f"Целевой путь существует и не является папкой: {path}")
    return path


def validate_export_targets(output_dir: Path, project_name: str) -> tuple[Path, Path]:
    """Проверить, что итоговые .xpj и ProjectData ещё не заняты."""
    xpj_path = output_dir / f"{project_name}.xpj"
    data_dir = output_dir / f"{project_name}{PROJECT_DATA_SUFFIX}"
    if xpj_path.exists():
        raise ValidationError(f"Файл уже существует: {xpj_path}")
    if data_dir.exists():
        raise ValidationError(f"Папка проекта уже существует: {data_dir}")
    return xpj_path, data_dir


def validate_notes_present(note_count: int) -> None:
    """Проверить, что MIDI содержит хотя бы одну ноту."""
    if note_count < 1:
        raise ValidationError("В MIDI-файле не найдено ни одной note-on/note-off пары.")


def validate_samples_cover_notes(sample_count: int, note_count: int) -> None:
    """Проверить, что каждому уникальному pitch хватит WAV-семпла."""
    if sample_count < note_count:
        raise ValidationError(
            f"Уникальных drum-нот в MIDI: {note_count}, а WAV-семплов: {sample_count}. "
            "Нужно минимум по одному семплу на каждую используемую ноту."
        )
