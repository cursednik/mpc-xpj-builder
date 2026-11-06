"""Batch-манифест: несколько проектов за один запуск."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from errors import ValidationError
from validators import validate_bpm, validate_project_name


@dataclass(frozen=True)
class BatchJob:
    """Одна задача batch-манифеста."""

    label: str
    name: str
    samples: Path
    midi: Path
    bpm: float
    output: Path
    template: Path | None
    sample_map: Path | None
    extended_notes: bool = False


@dataclass(frozen=True)
class BatchSpec:
    """Разобранный batch-манифест."""

    source: Path
    jobs: tuple[BatchJob, ...]


_TOP_LEVEL_KEYS = {"jobs", "template", "output", "bpm"}
_JOB_KEYS = {
    "name",
    "samples",
    "midi",
    "bpm",
    "output",
    "template",
    "map",
    "extended_notes",
}


def _resolve(base: Path, raw: Any, field: str) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise ValidationError(f"Поле {field} должно быть непустой строкой.")
    path = Path(raw.strip())
    if not path.is_absolute():
        path = base / path
    return path


def _optional_path(
    base: Path,
    raw: Any,
    field: str,
    default: Path | None,
) -> Path | None:
    if raw is None:
        return default
    return _resolve(base, raw, field)


def _optional_bpm(raw: Any, field: str) -> float | None:
    if raw is None:
        return None
    return validate_bpm(raw)


def load_batch_manifest(
    path: Path,
    *,
    default_template: Path | None = None,
    default_output: Path | None = None,
) -> BatchSpec:
    """Прочитать JSON-манифест и разрешить относительные пути."""
    if not path.is_file():
        raise ValidationError(f"Batch-манифест не найден: {path}")
    if path.suffix.lower() != ".json":
        raise ValidationError("Batch-манифест должен быть .json.")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Не удалось прочитать batch-манифест {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValidationError("Batch-манифест должен быть JSON-объектом.")

    unknown_top = set(payload) - _TOP_LEVEL_KEYS
    if unknown_top:
        raise ValidationError(
            "Неизвестные поля batch-манифеста: "
            + ", ".join(sorted(unknown_top))
            + "."
        )

    raw_jobs = payload.get("jobs")
    if not isinstance(raw_jobs, list) or not raw_jobs:
        raise ValidationError("В batch-манифесте нужен непустой массив jobs.")

    base = path.resolve().parent
    cli_template = (
        default_template.resolve()
        if default_template is not None
        else None
    )
    cli_output = (
        default_output.resolve()
        if default_output is not None
        else None
    )
    global_template = _optional_path(
        base, payload.get("template"), "template", cli_template
    )
    global_output = _optional_path(
        base, payload.get("output"), "output", cli_output
    )
    global_bpm = _optional_bpm(payload.get("bpm"), "bpm")

    jobs: list[BatchJob] = []
    targets: set[tuple[str, str]] = set()
    names: set[str] = set()

    for index, raw in enumerate(raw_jobs):
        label = f"jobs[{index}]"
        if not isinstance(raw, dict):
            raise ValidationError(f"{label} должен быть объектом.")
        unknown = set(raw) - _JOB_KEYS
        if unknown:
            raise ValidationError(
                f"Неизвестные поля в {label}: {', '.join(sorted(unknown))}."
            )

        raw_name = raw.get("name")
        if not isinstance(raw_name, str):
            raise ValidationError(f"В {label} не задан name.")
        name = validate_project_name(raw_name)

        samples = _resolve(base, raw.get("samples"), f"{label}.samples")
        midi = _resolve(base, raw.get("midi"), f"{label}.midi")
        output = _optional_path(
            base, raw.get("output"), f"{label}.output", global_output
        )
        if output is None:
            raise ValidationError(
                f"Для {label} не задан output (ни в job, ни на верхнем уровне)."
            )
        template = _optional_path(
            base, raw.get("template"), f"{label}.template", global_template
        )
        sample_map = _optional_path(
            base, raw.get("map"), f"{label}.map", None
        )
        extended_notes = raw.get("extended_notes", False)
        if not isinstance(extended_notes, bool):
            raise ValidationError(f"{label}.extended_notes должен быть bool.")

        bpm = _optional_bpm(raw.get("bpm"), f"{label}.bpm")
        if bpm is None:
            bpm = global_bpm
        if bpm is None:
            raise ValidationError(
                f"Для {label} не задан bpm (ни в job, ни на верхнем уровне)."
            )

        name_key = name.casefold()
        if name_key in names:
            raise ValidationError(f"Имя проекта повторяется в batch: {name!r}.")
        names.add(name_key)

        target_key = (str(output.resolve()).casefold(), name_key)
        if target_key in targets:
            raise ValidationError(
                f"Цель batch повторяется: {output / name}."
            )
        targets.add(target_key)

        jobs.append(
            BatchJob(
                label=label,
                name=name,
                samples=samples,
                midi=midi,
                bpm=bpm,
                output=output,
                template=template,
                sample_map=sample_map,
                extended_notes=extended_notes,
            )
        )

    return BatchSpec(source=path.resolve(), jobs=tuple(jobs))
