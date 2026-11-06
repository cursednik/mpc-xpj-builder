"""Просмотр .xpj-проектов в папке без загрузки на устройство."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from errors import ValidationError
from xpj_writer import read_xpj


@dataclass(frozen=True)
class ProjectInfo:
    path: Path
    name: str
    bpm: float | None
    samples: int
    bars: int
    tracks: int
    modified: float
    error: str | None = None

    @property
    def modified_text(self) -> str:
        return datetime.fromtimestamp(self.modified).strftime("%Y-%m-%d %H:%M")


def _project_info(path: Path) -> ProjectInfo:
    modified = path.stat().st_mtime
    try:
        _, payload, _ = read_xpj(path)
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ValueError("нет data")
        sequences = data.get("sequences")
        sequence = {}
        if isinstance(sequences, list) and sequences:
            first = sequences[0]
            if isinstance(first, dict) and isinstance(first.get("value"), dict):
                sequence = first["value"]
        samples = data.get("samples")
        tracks = data.get("tracks")
        bpm_value = sequence.get("bpm", data.get("masterTempo"))
        bpm = float(bpm_value) if isinstance(bpm_value, (int, float)) else None
        bars_value = sequence.get("lengthBars")
        bars = int(bars_value) if isinstance(bars_value, int) else 0
        name = sequence.get("name")
        if not isinstance(name, str) or not name:
            name = path.stem
        return ProjectInfo(
            path=path,
            name=name,
            bpm=bpm,
            samples=len(samples) if isinstance(samples, list) else 0,
            bars=bars,
            tracks=len(tracks) if isinstance(tracks, list) else 0,
            modified=modified,
        )
    except Exception as exc:
        return ProjectInfo(
            path=path,
            name=path.stem,
            bpm=None,
            samples=0,
            bars=0,
            tracks=0,
            modified=modified,
            error=str(exc),
        )


def scan_projects(folder: Path) -> tuple[ProjectInfo, ...]:
    """Прочитать все .xpj верхнего уровня в папке."""
    if not folder.is_dir():
        raise ValidationError(f"Папка проектов не найдена: {folder}")
    files = sorted(
        folder.glob("*.xpj"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return tuple(_project_info(path) for path in files)
