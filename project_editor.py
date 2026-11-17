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
from kit_map import PadAssignment
from sample_map import PadBinding
from validators import validate_bpm
from wav_pool import PoolSample, inspect_wav
from xpj_schema import _assign_layer, _clear_instrument, float32
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


def _drum_track(data: dict[str, Any]) -> dict[str, Any] | None:
    tracks = data.get("tracks")
    if not isinstance(tracks, list):
        return None
    for track in tracks:
        if not isinstance(track, dict):
            continue
        program = track.get("program")
        if isinstance(program, dict) and isinstance(program.get("drum"), dict):
            return track
    return None


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


def _first_assigned_layer(instrument: dict[str, Any]) -> dict[str, Any] | None:
    layers = instrument.get("layersv")
    if not isinstance(layers, list):
        return None
    for layer in layers:
        if isinstance(layer, dict) and layer.get("sampleFile"):
            return layer
    return None


def read_pad_assignments(payload: dict[str, Any]) -> dict[int, PadAssignment]:
    """Прочитать назначения падов из существующего проекта."""
    data = _require_data(payload)
    instruments = _drum_instruments(data)
    assignments: dict[int, PadAssignment] = {}
    for pad_index, instrument in enumerate(instruments):
        layer = _first_assigned_layer(instrument)
        if layer is None:
            continue
        file = layer.get("sampleFile")
        if not isinstance(file, str) or not file:
            continue
        volume = layer.get("volume")
        gain = 1.0
        if isinstance(volume, dict):
            value = volume.get("gainCoefficient")
            if isinstance(value, (int, float)):
                gain = float(value)
        pan_value = layer.get("pan")
        pan = float(pan_value) if isinstance(pan_value, (int, float)) else 0.5
        tune_value = layer.get("pitch")
        if not isinstance(tune_value, (int, float)):
            coarse = layer.get("coarseTune", 0)
            fine = layer.get("fineTune", 0)
            tune_value = (
                (coarse if isinstance(coarse, (int, float)) else 0)
                + (fine if isinstance(fine, (int, float)) else 0) / 100.0
            )
        loop = (
            instrument.get("triggerMode") == 3
            or layer.get("loopMode") == 1
            or bool(layer.get("loop"))
        )
        assignments[pad_index] = PadAssignment(
            pad_index=pad_index,
            file=file,
            gain=gain,
            pan=pan,
            tune=float(tune_value),
            loop=bool(loop),
        )
    return assignments


def apply_pad_assignments(
    payload: dict[str, Any],
    assignments: dict[int, PadAssignment],
    data_dir: Path | None,
) -> dict[str, Any]:
    """Записать назначения падов в существующий проект."""
    result = copy.deepcopy(payload)
    data = _require_data(result)
    instruments = _drum_instruments(data)

    sample_paths: set[str] = set()
    samples = data.get("samples")
    if isinstance(samples, list):
        for entry in samples:
            if isinstance(entry, dict):
                path = entry.get("path")
                if isinstance(path, str) and path:
                    sample_paths.add(path)

    for pad_index, instrument in enumerate(instruments):
        assignment = assignments.get(pad_index)
        if assignment is None:
            _clear_instrument(instrument)
            instrument["triggerMode"] = 0
            continue
        if data_dir is None:
            raise ValidationError(
                "Для изменения падов нужна папка ресурсов _[ProjectData]."
            )
        file_path = Path(data_dir) / assignment.file
        if not file_path.is_file():
            raise ValidationError(f"WAV не найден: {file_path}")
        if sample_paths and assignment.file not in sample_paths:
            raise ValidationError(
                f"WAV {assignment.file!r} не входит в список samples проекта."
            )
        try:
            info = inspect_wav(file_path)
        except Exception as exc:
            raise ValidationError(
                f"Не удалось прочитать WAV {file_path}: {exc}"
            ) from exc
        sample = PoolSample(
            source=file_path,
            output_name=assignment.file,
            display_name=Path(assignment.file).stem,
            info=info,
        )
        binding = PadBinding(
            sample=sample,
            pad_index=pad_index,
            midi_note=None,
            gain=assignment.gain,
            pan=assignment.pan,
            tune=assignment.tune,
            loop=assignment.loop,
        )
        layers = instrument.get("layersv")
        if not isinstance(layers, list) or not layers:
            raise ValidationError(
                f"У пада {pad_index + 1} нет layersv."
            )
        layer = next(
            (item for item in layers if isinstance(item, dict)),
            None,
        )
        if layer is None:
            raise ValidationError(f"У пада {pad_index + 1} нет слоя.")
        _assign_layer(layer, binding)
        instrument["triggerMode"] = 3 if assignment.loop else 0
    return result


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


def import_sample(
    payload: dict[str, Any],
    data_dir: Path,
    source: Path,
) -> tuple[dict[str, Any], str]:
    """Скопировать WAV в проект и добавить sample entry."""
    result = copy.deepcopy(payload)
    data = _require_data(result)
    source = Path(source)
    if not source.is_file():
        raise ValidationError(f"WAV не найден: {source}")
    if source.suffix.lower() != ".wav":
        raise ValidationError("Можно добавлять только WAV-файлы.")
    try:
        inspect_wav(source)
    except Exception as exc:
        raise ValidationError(f"Не удалось прочитать WAV {source}: {exc}") from exc

    directory = Path(data_dir)
    if not directory.is_dir():
        raise ValidationError(
            f"Папка ресурсов проекта не найдена: {directory}"
        )

    samples = data.get("samples")
    if not isinstance(samples, list):
        samples = []
        data["samples"] = samples
    paths = {
        entry.get("path")
        for entry in samples
        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
    }
    target_name = source.name
    target = directory / target_name
    if target_name in paths or target.exists():
        try:
            same = source.resolve() == target.resolve()
        except OSError:
            same = False
        if same and target_name in paths:
            return result, target_name
        base = source.stem
        suffix = source.suffix
        counter = 2
        while True:
            candidate = f"{base}_{counter}{suffix}"
            if candidate not in paths and not (directory / candidate).exists():
                target_name = candidate
                target = directory / target_name
                break
            counter += 1

    try:
        shutil.copy2(source, target)
    except OSError as exc:
        raise ExportError(f"Не удалось скопировать {source} -> {target}: {exc}") from exc

    prototype = next(
        (entry for entry in samples if isinstance(entry, dict)),
        None,
    )
    entry = copy.deepcopy(prototype) if prototype is not None else {
        "version": 1,
        "loadImpl": 1,
        "metadata": {},
    }
    entry["version"] = 1
    entry["name"] = target.stem
    entry["path"] = target_name
    entry.setdefault("loadImpl", 1)
    metadata = entry.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
        entry["metadata"] = metadata
    bpm_raw = data.get("masterTempo", 120.0)
    bpm = float(bpm_raw) if isinstance(bpm_raw, (int, float)) else 120.0
    metadata["tempo"] = float32(bpm)
    metadata.setdefault("rootNote", 60)
    metadata.setdefault("tune", 0.0)
    metadata.setdefault("key", data.get("key") or "C Major")
    samples.append(entry)

    track = _drum_track(data)
    if track is not None:
        track_samples = track.get("samples")
        if not isinstance(track_samples, list):
            track_samples = []
            track["samples"] = track_samples
        track_samples.append(copy.deepcopy(entry))
    return result, target_name


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
