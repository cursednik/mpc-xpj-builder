"""Модель карты семплов для GUI и автоназначения."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from errors import ValidationError
from sample_map import load_sample_map
from validators import MAX_DRUM_NOTE, MIN_DRUM_NOTE
from wav_pool import inspect_wav, scan_wav_files
from xpj_schema import default_note_to_pad, extract_note_to_pad
from xpj_writer import read_xpj

BANK_NAMES = "ABCDEFGH"
PADS_PER_BANK = 16
TOTAL_PADS = 128

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
    """Назначение семпла на note/pad."""

    note: int
    file: str
    gain: float = 1.0
    pan: float = 0.5
    tune: float = 0.0
    loop: bool = False


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


def global_pad_index(bank: str, pad_number: int) -> int:
    """A1 -> 0, H16 -> 127."""
    bank = bank.strip().upper()
    if len(bank) != 1 or bank not in BANK_NAMES:
        raise ValueError(f"Неизвестный банк: {bank!r}.")
    if not 1 <= pad_number <= PADS_PER_BANK:
        raise ValueError("Pad должен быть в диапазоне 1..16.")
    return BANK_NAMES.index(bank) * PADS_PER_BANK + pad_number - 1


def bank_pad_label(pad_index: int) -> str:
    if not 0 <= pad_index < TOTAL_PADS:
        raise ValueError(f"Некорректный pad index: {pad_index}.")
    return f"{BANK_NAMES[pad_index // PADS_PER_BANK]}{pad_index % PADS_PER_BANK + 1}"


def default_pad_to_note() -> dict[int, int]:
    return {pad: note for note, pad in default_note_to_pad().items()}


def pad_to_note_from_template(
    template: Path | None,
) -> tuple[dict[int, int], str | None]:
    """Получить pad -> note из эталона; при ошибке — стандартная карта."""
    if template is None or not template.is_file():
        return default_pad_to_note(), None
    try:
        _, payload, _ = read_xpj(template)
        note_to_pad = extract_note_to_pad(payload)
        return {
            pad: note
            for note, pad in note_to_pad.items()
            if MIN_DRUM_NOTE <= note <= MAX_DRUM_NOTE
        }, None
    except Exception as exc:
        return default_pad_to_note(), str(exc)


def load_kit_map(path: Path) -> dict[int, PadAssignment]:
    """Загрузить map.json в модель редактора."""
    entries = load_sample_map(path)
    return {
        entry.note: PadAssignment(
            note=entry.note,
            file=entry.file,
            gain=1.0 if entry.gain is None else entry.gain,
            pan=0.5 if entry.pan is None else entry.pan,
            tune=0.0 if entry.tune is None else entry.tune,
            loop=bool(entry.loop),
        )
        for entry in entries
    }


def save_kit_map(path: Path, assignments: dict[int, PadAssignment]) -> Path:
    """Сохранить map.json в формате --map."""
    samples = []
    for note in sorted(assignments):
        assignment = assignments[note]
        samples.append(
            {
                "file": assignment.file,
                "note": assignment.note,
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
        if MIN_DRUM_NOTE <= note <= MAX_DRUM_NOTE:
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
) -> dict[int, PadAssignment]:
    """Автоназначить новые семплы, не трогая уже занятые notes."""
    result = dict(assignments)
    used_files = {assignment.file for assignment in result.values()}
    used_notes = set(result)
    for item in items:
        note = _note_from_filename(Path(item.relative).stem)
        if note is None or note in used_notes or item.relative in used_files:
            continue
        if note not in note_to_pad:
            continue
        result[note] = PadAssignment(note=note, file=item.relative)
        used_notes.add(note)
        used_files.add(item.relative)
    return result
