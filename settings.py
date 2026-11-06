"""Сохранение настроек GUI в %APPDATA%."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class GuiSettings:
    samples: str = ""
    midi: str = ""
    name: str = "My Kit"
    bpm: str = "120"
    output: str = ""
    template: str = ""
    sample_map: str = ""
    extended_notes: bool = False
    verbose: bool = True
    recent_projects: tuple[str, ...] = ()


def settings_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "mpc-xpj-builder" / "settings.json"
    return Path.home() / ".config" / "mpc-xpj-builder" / "settings.json"


def _text(data: dict, key: str, default: str) -> str:
    value = data.get(key)
    return value if isinstance(value, str) else default


def _bool(data: dict, key: str, default: bool) -> bool:
    value = data.get(key)
    return value if isinstance(value, bool) else default


def _text_list(data: dict, key: str) -> tuple[str, ...]:
    value = data.get(key)
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item)


def load_settings(path: Path | None = None) -> GuiSettings:
    target = path or settings_path()
    if not target.is_file():
        return GuiSettings()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return GuiSettings()
    if not isinstance(data, dict):
        return GuiSettings()
    defaults = GuiSettings()
    return GuiSettings(
        samples=_text(data, "samples", defaults.samples),
        midi=_text(data, "midi", defaults.midi),
        name=_text(data, "name", defaults.name),
        bpm=_text(data, "bpm", defaults.bpm),
        output=_text(data, "output", defaults.output),
        template=_text(data, "template", defaults.template),
        sample_map=_text(data, "sample_map", defaults.sample_map),
        extended_notes=_bool(
            data, "extended_notes", defaults.extended_notes
        ),
        verbose=_bool(data, "verbose", defaults.verbose),
        recent_projects=_text_list(data, "recent_projects"),
    )


def remember_recent(
    projects: tuple[str, ...] | list[str],
    path: Path | str,
    limit: int = 10,
) -> tuple[str, ...]:
    text = str(path)
    result = [text]
    result.extend(
        item
        for item in projects
        if item.casefold() != text.casefold()
    )
    return tuple(result[: max(1, limit)])


def save_settings(
    settings: GuiSettings,
    path: Path | None = None,
) -> Path:
    target = path or settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(asdict(settings), handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(temp_path, target)
    except OSError:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise
    return target
