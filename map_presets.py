"""Именованные пресеты карт семплов."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from errors import ValidationError
from kit_map import PadAssignment, load_kit_map, save_kit_map

_INVALID_CHARS = set('<>:"/\\|?*') | {chr(code) for code in range(32)}


@dataclass(frozen=True)
class MapPreset:
    """Пресет карты: отображаемое имя и файл на диске."""

    name: str
    path: Path


def presets_dir(base: Path | None = None) -> Path:
    """Папка пресетов. По умолчанию — %APPDATA%\\mpc-xpj-builder\\map-presets."""
    if base is not None:
        return Path(base)
    appdata = os.environ.get("APPDATA")
    root = Path(appdata) if appdata else Path.home() / ".config"
    return root / "mpc-xpj-builder" / "map-presets"


def validate_preset_name(name: str) -> str:
    """Проверить имя пресета и вернуть его без пробелов по краям."""
    if not isinstance(name, str):
        raise ValidationError("Имя пресета должно быть строкой.")
    cleaned = name.strip()
    if not cleaned:
        raise ValidationError("Имя пресета не может быть пустым.")
    if cleaned in {".", ".."}:
        raise ValidationError("Недопустимое имя пресета.")
    if any(char in _INVALID_CHARS for char in cleaned):
        raise ValidationError(
            "Имя пресета не должно содержать символы < > : \" / \\ | ? *."
        )
    if cleaned.endswith((".", " ")):
        raise ValidationError("Имя пресета не должно заканчиваться точкой или пробелом.")
    return cleaned


def preset_path(name: str, base: Path | None = None) -> Path:
    """Путь файла пресета для заданного имени."""
    return presets_dir(base) / f"{validate_preset_name(name)}.json"


def list_presets(base: Path | None = None) -> tuple[MapPreset, ...]:
    """Список пресетов, отсортированный по имени без учёта регистра."""
    folder = presets_dir(base)
    if not folder.is_dir():
        return ()
    items = [
        MapPreset(path.stem, path)
        for path in folder.glob("*.json")
        if path.is_file()
    ]
    return tuple(sorted(items, key=lambda preset: preset.name.casefold()))


def save_preset(
    name: str,
    assignments: dict[int, PadAssignment],
    base: Path | None = None,
) -> MapPreset:
    """Атомарно сохранить карту как именованный пресет."""
    cleaned = validate_preset_name(name)
    folder = presets_dir(base)
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ValidationError(f"Не удалось создать папку пресетов {folder}: {exc}") from exc

    target = folder / f"{cleaned}.json"
    temp_path: Path | None = None
    try:
        descriptor, raw_temp = tempfile.mkstemp(
            prefix=f".{cleaned}.",
            suffix=".tmp",
            dir=folder,
        )
        os.close(descriptor)
        temp_path = Path(raw_temp)
        save_kit_map(temp_path, assignments)
        os.replace(temp_path, target)
    except OSError as exc:
        raise ValidationError(f"Не удалось сохранить пресет {cleaned!r}: {exc}") from exc
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return MapPreset(cleaned, target)


def load_preset(
    preset: MapPreset,
    note_to_pad: dict[int, int] | None = None,
) -> dict[int, PadAssignment]:
    """Загрузить назначения падов из пресета."""
    if not preset.path.is_file():
        raise ValidationError(f"Пресет не найден: {preset.path}")
    return load_kit_map(preset.path, note_to_pad)


def delete_preset(preset: MapPreset) -> bool:
    """Удалить пресет. Возвращает False, если файла уже нет."""
    try:
        preset.path.unlink()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise ValidationError(f"Не удалось удалить пресет {preset.name!r}: {exc}") from exc
    return True
