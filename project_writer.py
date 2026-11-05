"""Атомарная запись папки проекта и копирование WAV-ресурсов."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from errors import ExportError, ValidationError
from validators import validate_export_targets
from wav_pool import PoolSample
from xpj_schema import BuildPlan
from xpj_writer import XPJHeader, write_xpj


def _copy_samples(samples: tuple[PoolSample, ...], destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    for sample in samples:
        target = destination / sample.output_name
        try:
            shutil.copy2(sample.source, target)
        except OSError as exc:
            raise ExportError(
                f"Не удалось скопировать {sample.source} -> {target}: {exc}"
            ) from exc


def write_project(
    plan: BuildPlan,
    header: XPJHeader,
    payload: dict[str, Any],
) -> tuple[Path, Path]:
    """Собрать проект во временной папке и переименовать в финальные пути."""
    output_dir = plan.output_dir
    created_output = False
    if not output_dir.exists():
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            created_output = True
        except OSError as exc:
            raise ExportError(
                f"Не удалось создать целевую папку {output_dir}: {exc}"
            ) from exc

    try:
        xpj_path, data_dir = validate_export_targets(output_dir, plan.project_name)
    except ValidationError:
        if created_output:
            try:
                output_dir.rmdir()
            except OSError:
                pass
        raise

    try:
        temp_dir = Path(
            tempfile.mkdtemp(prefix=f".{plan.project_name}.tmp-", dir=output_dir)
        )
    except OSError as exc:
        raise ExportError(f"Не удалось создать временную папку: {exc}") from exc

    staged_data = temp_dir / data_dir.name
    staged_xpj = temp_dir / xpj_path.name
    moved_data = False

    try:
        _copy_samples(plan.wavs, staged_data)
        write_xpj(staged_xpj, header, payload)

        try:
            os.replace(staged_data, data_dir)
            moved_data = True
            os.replace(staged_xpj, xpj_path)
        except OSError as exc:
            raise ExportError(
                f"Не удалось переименовать проект в {output_dir}: {exc}"
            ) from exc

        return xpj_path, data_dir
    except Exception:
        if moved_data and data_dir.exists():
            shutil.rmtree(data_dir, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        if created_output and output_dir.exists():
            try:
                if not any(output_dir.iterdir()):
                    output_dir.rmdir()
            except OSError:
                pass
