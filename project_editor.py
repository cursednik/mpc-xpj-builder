"""Открытие, редактирование и безопасное сохранение существующего .xpj."""

from __future__ import annotations

import copy
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from errors import ExportError, ValidationError
from validators import validate_bpm
from xpj_schema import float32
from xpj_writer import XPJHeader, read_xpj, write_xpj

DATA_DIR_SUFFIX = "_[ProjectData]"


@dataclass(frozen=True)
class SequenceSummary:
    index: int
    name: str
    bpm: float | None
    bars: int
    notes: int


@dataclass(frozen=True)
class ProjectSummary:
    path: Path
    version: str
    platform: str
    title: str
    bpm: float
    sequences: tuple[SequenceSummary, ...]
    tracks: int
    samples: int
    pads: int
    data_dir: Path | None
    data_wavs: int


def data_dir_for(path: Path) -> Path:
    """Папка ресурсов, соответствующая .xpj с таким именем."""
    return path.parent / f"{path.stem}{DATA_DIR_SUFFIX}"


def backup_path(path: Path) -> Path:
    """Резервная копия, создаваемая перед перезаписью."""
    return path.with_name(path.name + ".bak")


def validate_title(title: str) -> str:
    """Проверить название проекта."""
    if not isinstance(title, str):
        raise ValidationError("Название проекта должно быть строкой.")
    cleaned = title.strip()
    if not cleaned:
        raise ValidationError("Название проекта не может быть пустым.")
    if len(cleaned) > 160:
        raise ValidationError("Название проекта слишком длинное (максимум 160 символов).")
    return cleaned


def _require_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValidationError("В .xpj нет объекта data.")
    return data


def _sequence_values(data: dict[str, Any]) -> list[dict[str, Any]]:
    sequences = data.get("sequences")
    if not isinstance(sequences, list) or not sequences:
        raise ValidationError("В .xpj нет sequences.")
    values: list[dict[str, Any]] = []
    for wrapper in sequences:
        if not isinstance(wrapper, dict):
            continue
        value = wrapper.get("value")
        if isinstance(value, dict):
            values.append(value)
    if not values:
        raise ValidationError("В .xpj нет корректных sequence.")
    return values


def _count_notes(sequence: dict[str, Any]) -> int:
    total = 0
    rows = sequence.get("trackClipMaps")
    if not isinstance(rows, list):
        return 0
    for row in rows:
        if not isinstance(row, list):
            continue
        for clip in row:
            if not isinstance(clip, dict):
                continue
            value = clip.get("value")
            if not isinstance(value, dict):
                continue
            event_list = value.get("eventList")
            if not isinstance(event_list, dict):
                continue
            events = event_list.get("events")
            if isinstance(events, list):
                total += sum(
                    1
                    for event in events
                    if isinstance(event, dict) and event.get("type") == 3
                )
    return total


def _drum_instruments(data: dict[str, Any]) -> list[dict[str, Any]]:
    tracks = data.get("tracks")
    if not isinstance(tracks, list):
        return []
    for track in tracks:
        if not isinstance(track, dict):
            continue
        program = track.get("program")
        if not isinstance(program, dict):
            continue
        drum = program.get("drum")
        if not isinstance(drum, dict):
            continue
        instruments = drum.get("instruments")
        if isinstance(instruments, list):
            return [item for item in instruments if isinstance(item, dict)]
    return []


def _count_assigned_pads(instruments: list[dict[str, Any]]) -> int:
    assigned = 0
    for instrument in instruments:
        layers = instrument.get("layersv")
        if not isinstance(layers, list):
            continue
        if any(
            isinstance(layer, dict) and layer.get("sampleFile")
            for layer in layers
        ):
            assigned += 1
    return assigned


def _project_title(data: dict[str, Any], sequences: list[dict[str, Any]], path: Path) -> str:
    info = data.get("info")
    if isinstance(info, dict):
        title = info.get("title")
        if isinstance(title, str) and title.strip():
            return title.strip()
    for sequence in sequences:
        name = sequence.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return path.stem


def _project_bpm(data: dict[str, Any], sequences: list[dict[str, Any]]) -> float:
    raw = sequences[0].get("bpm", data.get("masterTempo"))
    try:
        return validate_bpm(raw)
    except ValidationError as exc:
        raise ValidationError("В проекте не найден корректный BPM.") from exc


def read_project(path: Path) -> tuple[XPJHeader, dict[str, Any], ProjectSummary]:
    """Прочитать .xpj и собрать сводку, не изменяя файл."""
    target = Path(path)
    header, payload, _ = read_xpj(target)
    data = _require_data(payload)
    sequences = _sequence_values(data)

    summaries: list[SequenceSummary] = []
    for index, sequence in enumerate(sequences):
        name = sequence.get("name")
        if not isinstance(name, str) or not name.strip():
            name = f"Sequence {index + 1:02d}"
        bpm_raw = sequence.get("bpm")
        bpm = float(bpm_raw) if isinstance(bpm_raw, (int, float)) else None
        bars_raw = sequence.get("lengthBars")
        bars = int(bars_raw) if isinstance(bars_raw, int) else 0
        summaries.append(
            SequenceSummary(
                index=index,
                name=name,
                bpm=bpm,
                bars=bars,
                notes=_count_notes(sequence),
            )
        )

    tracks = data.get("tracks")
    samples = data.get("samples")
    instruments = _drum_instruments(data)
    resource_dir = data_dir_for(target)
    if not resource_dir.is_dir():
        resource_dir = None

    summary = ProjectSummary(
        path=target,
        version=header.version,
        platform=header.platform,
        title=_project_title(data, sequences, target),
        bpm=_project_bpm(data, sequences),
        sequences=tuple(summaries),
        tracks=len(tracks) if isinstance(tracks, list) else 0,
        samples=len(samples) if isinstance(samples, list) else 0,
        pads=_count_assigned_pads(instruments),
        data_dir=resource_dir,
        data_wavs=(
            len(list(resource_dir.rglob("*.wav")))
            if resource_dir is not None
            else 0
        ),
    )
    return header, payload, summary


def apply_metadata(payload: dict[str, Any], title: str, bpm: float) -> dict[str, Any]:
    """Изменить только название проекта и BPM, сохранив остальные поля."""
    cleaned_title = validate_title(title)
    bpm_value = validate_bpm(bpm)
    result = copy.deepcopy(payload)
    data = _require_data(result)

    info = data.get("info")
    if not isinstance(info, dict):
        raise ValidationError("В .xpj нет объекта data.info.")
    old_title = info.get("title")
    if not isinstance(old_title, str):
        old_title = ""
    info["title"] = cleaned_title
    data["masterTempo"] = float32(bpm_value)

    for sequence in _sequence_values(data):
        if old_title and sequence.get("name") == old_title:
            sequence["name"] = cleaned_title
        sequence["bpm"] = float32(bpm_value)
    return result


def save_project_copy(
    source: Path,
    target: Path,
    header: XPJHeader,
    payload: dict[str, Any],
) -> tuple[Path, Path | None]:
    """Сохранить проект в новый .xpj и скопировать папку ресурсов."""
    source = Path(source)
    target = Path(target)
    if target.suffix.lower() != ".xpj":
        raise ValidationError("Новый проект должен иметь расширение .xpj.")
    if target.resolve() == source.resolve():
        raise ValidationError(
            "Для сохранения поверх исходного используйте «Перезаписать с backup»."
        )
    if target.exists():
        raise ValidationError(f"Файл уже существует: {target}")

    source_data = data_dir_for(source)
    target_data = data_dir_for(target)
    if target_data.exists():
        raise ValidationError(f"Папка ресурсов уже существует: {target_data}")

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ExportError(
            f"Не удалось создать папку {target.parent}: {exc}"
        ) from exc

    temp_root = Path(
        tempfile.mkdtemp(prefix=f".{target.stem}.tmp-", dir=target.parent)
    )
    staged_xpj = temp_root / target.name
    staged_data = temp_root / target_data.name
    moved_data = False

    try:
        if source_data.is_dir():
            shutil.copytree(source_data, staged_data)
        write_xpj(staged_xpj, header, payload)
        read_xpj(staged_xpj)

        if staged_data.exists():
            os.replace(staged_data, target_data)
            moved_data = True
        os.replace(staged_xpj, target)
    except Exception:
        if moved_data and target_data.exists():
            shutil.rmtree(target_data, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)

    return target, target_data if source_data.is_dir() else None


def save_project_in_place(
    path: Path,
    header: XPJHeader,
    payload: dict[str, Any],
) -> tuple[Path, Path]:
    """Перезаписать .xpj атомарно, предварительно создав .bak."""
    target = Path(path)
    if not target.is_file():
        raise ValidationError(f"XPJ-файл не найден: {target}")

    backup = backup_path(target)
    try:
        shutil.copy2(target, backup)
    except OSError as exc:
        raise ExportError(f"Не удалось создать backup {backup}: {exc}") from exc

    temp_path: Path | None = None
    try:
        descriptor, raw_temp = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
        )
        os.close(descriptor)
        temp_path = Path(raw_temp)
        write_xpj(temp_path, header, payload)
        read_xpj(temp_path)
        os.replace(temp_path, target)
    except OSError as exc:
        raise ExportError(f"Не удалось записать {target}: {exc}") from exc
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return target, backup
