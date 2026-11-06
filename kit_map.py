"""Модель карты семплов для GUI и автоназначения."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from errors import ValidationError
from pads import (
    BANK_NAMES,
    PADS_PER_BANK,
    TOTAL_PADS,
    bank_pad_label,
    default_pad_to_note_full,
    global_pad_index,
)
from sample_map import load_sample_map
from validators import MAX_EXTENDED_NOTE, MIN_EXTENDED_NOTE
from wav_pool import inspect_wav, scan_wav_files
from xpj_schema import extract_note_to_pad
from xpj_writer import read_xpj

_NUMERIC_PREFIX = re.compile(r"^\s*(\d{1,3})(?:[_\-\s.]|$)")
_KEYWORD_RULES = (
    ("openhat", 46),
    ("open hat", 46),
    ("open_hat", 46),
    ("closedhat", 42),
    ("closed hat", 42),
    ("closed_hat", 42),
    ("hihat", 42),
    ("hi-hat", 42),
    ("hat", 42),
    ("kick", 36),
    ("snare", 38),
    ("clap", 39),
    ("rim", 37),
    ("ride", 51),
    ("crash", 49),
    ("tom", 45),
    ("perc", 43),
    ("808", 35),
    ("sub", 35),
)


@dataclass(frozen=True)
class WavItem:
    """WAV-файл в папке семплов."""

    relative: str
    path: Path
    frames: int
    channels: int
    sample_rate: int
    bits_per_sample: int

    @property
    def duration(self) -> float:
        return self.frames / self.sample_rate if self.sample_rate else 0.0

    @property
    def info(self) -> str:
        return (
            f"{self.duration:.2f}s · {self.sample_rate} Hz · "
            f"{self.bits_per_sample} bit · {self.channels} ch"
        )


@dataclass(frozen=True)
class PadAssignment:
    """Назначение семпла на конкретный pad."""

    pad_index: int
    file: str
    gain: float = 1.0
    pan: float = 0.5
    tune: float = 0.0
    loop: bool = False

    @property
    def pad_label(self) -> str:
        return bank_pad_label(self.pad_index)


def scan_wav_items(folder: Path) -> tuple[WavItem, ...]:
    """Прочитать WAV-файлы для таблицы редактора."""
    if not folder.is_dir():
        raise ValidationError(f"Папка с семплами не найдена: {folder}")
    items: list[WavItem] = []
    for path in scan_wav_files(folder):
        info = inspect_wav(path)
        items.append(
            WavItem(
                relative=path.relative_to(folder).as_posix(),
                path=path,
                frames=info.frames,
                channels=info.channels,
                sample_rate=info.sample_rate,
                bits_per_sample=info.bits_per_sample,
            )
        )
    return tuple(items)


def default_pad_to_note() -> dict[int, int]:
    return default_pad_to_note_full()


def default_note_to_pad() -> dict[int, int]:
    return {note: pad for pad, note in default_pad_to_note_full().items()}


def pad_to_note_from_template(
    template: Path | None,
) -> tuple[dict[int, int], str | None]:
    """Получить pad -> note из эталона; при ошибке — стандартная карта."""
    if template is None or not template.is_file():
        return default_pad_to_note(), None
    try:
        _, payload, _ = read_xpj(template)
        note_to_pad = extract_note_to_pad(payload)
        return {pad: note for note, pad in note_to_pad.items()}, None
    except Exception as exc:
        return default_pad_to_note(), str(exc)


def load_kit_map(
    path: Path,
    note_to_pad: dict[int, int] | None = None,
) -> dict[int, PadAssignment]:
    """Загрузить map.json в модель редактора."""
    if note_to_pad is None:
        note_to_pad = {note: pad for pad, note in default_pad_to_note().items()}
    entries = load_sample_map(path, allow_extended_notes=True)
    result: dict[int, PadAssignment] = {}
    for entry in entries:
        if entry.pad_index is not None:
            pad_index = entry.pad_index
        else:
            if entry.note is None:
                raise ValidationError(f"В записи {entry.label!r} нужен note или pad.")
            pad_index = note_to_pad.get(entry.note)
            if pad_index is None:
                raise ValidationError(
                    f"Нет pad для note {entry.note} в текущем шаблоне."
                )
        result[pad_index] = PadAssignment(
            pad_index=pad_index,
            file=entry.file,
            gain=1.0 if entry.gain is None else entry.gain,
            pan=0.5 if entry.pan is None else entry.pan,
            tune=0.0 if entry.tune is None else entry.tune,
            loop=bool(entry.loop),
        )
    return result


def save_kit_map(path: Path, assignments: dict[int, PadAssignment]) -> Path:
    """Сохранить map.json в формате --map."""
    samples = []
    for pad_index in sorted(assignments):
        assignment = assignments[pad_index]
        samples.append(
            {
                "pad": assignment.pad_label,
                "file": assignment.file,
                "gain": float(assignment.gain),
                "pan": float(assignment.pan),
                "tune": float(assignment.tune),
                "loop": bool(assignment.loop),
            }
        )
    path.write_text(
        json.dumps({"samples": samples}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def _note_from_filename(stem: str) -> int | None:
    numeric = _NUMERIC_PREFIX.match(stem)
    if numeric:
        note = int(numeric.group(1))
        if MIN_EXTENDED_NOTE <= note <= MAX_EXTENDED_NOTE:
            return note
    lowered = stem.casefold()
    for token, note in _KEYWORD_RULES:
        if token in lowered:
            return note
    return None


def auto_assign(
    items: Iterable[WavItem],
    assignments: dict[int, PadAssignment],
    note_to_pad: dict[int, int],
    *,
    fill_free: bool = False,
) -> dict[int, PadAssignment]:
    """Автоназначить новые семплы, не трогая уже занятые pads."""
    result = dict(assignments)
    used_files = {assignment.file for assignment in result.values()}
    used_pads = set(result)
    items = tuple(items)

    for item in items:
        note = _note_from_filename(Path(item.relative).stem)
        if note is None or item.relative in used_files:
            continue
        pad = note_to_pad.get(note)
        if pad is None or pad in used_pads:
            continue
        result[pad] = PadAssignment(pad_index=pad, file=item.relative)
        used_files.add(item.relative)
        used_pads.add(pad)

    if fill_free:
        free_pads = [pad for pad in range(TOTAL_PADS) if pad not in used_pads]
        for item, pad in zip(
            (item for item in items if item.relative not in used_files),
            free_pads,
        ):
            result[pad] = PadAssignment(pad_index=pad, file=item.relative)
            used_files.add(item.relative)
            used_pads.add(pad)

    return result
