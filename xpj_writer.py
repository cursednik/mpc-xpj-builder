"""Чтение и запись gzip-контейнера .xpj."""

from __future__ import annotations

import gzip
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from errors import ExportError, ValidationError

_HEADER_LINES = 5
_GZIP_MAGIC = b"\x1f\x8b"
_MAGIC = "ACVS"
_DATA_TYPE = "SerialisableProjectData"
_SERIALIZATION = "json"


@dataclass(frozen=True)
class XPJHeader:
    """Пять текстовых строк заголовка .xpj."""

    version: str
    platform: str
    magic: str = _MAGIC
    data_type: str = _DATA_TYPE
    serialization_format: str = _SERIALIZATION

    def lines(self) -> tuple[str, str, str, str, str]:
        return (
            self.magic,
            self.version,
            self.data_type,
            self.serialization_format,
            self.platform,
        )


def read_xpj(path: Path) -> tuple[XPJHeader, dict[str, Any], str]:
    """Прочитать .xpj, не изменяя исходный файл."""
    if not path.is_file():
        raise ValidationError(f"XPJ-файл не найден: {path}")

    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        raise ValidationError(f"Не удалось прочитать {path}: {exc}") from exc

    try:
        payload_bytes = (
            gzip.decompress(raw_bytes)
            if raw_bytes.startswith(_GZIP_MAGIC)
            else raw_bytes
        )
    except (OSError, EOFError) as exc:
        raise ValidationError(f"Некорректный gzip в {path}: {exc}") from exc

    try:
        text = payload_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError(f"XPJ не является UTF-8 текстом: {path}") from exc

    parts = text.split("\n", _HEADER_LINES)
    if len(parts) < _HEADER_LINES + 1:
        raise ValidationError(
            f"XPJ {path} слишком короткий: нужен заголовок из 5 строк и JSON."
        )

    raw_header = [line.rstrip("\r") for line in parts[:_HEADER_LINES]]
    if raw_header[0] != _MAGIC:
        raise ValidationError(
            f"Некорректный XPJ {path}: ожидался ACVS, найден {raw_header[0]!r}."
        )
    if raw_header[2] != _DATA_TYPE:
        raise ValidationError(
            f"Некорректный XPJ {path}: неизвестный тип {raw_header[2]!r}."
        )
    if raw_header[3] != _SERIALIZATION:
        raise ValidationError(
            f"Некорректный XPJ {path}: неизвестная сериализация {raw_header[3]!r}."
        )

    json_text = parts[_HEADER_LINES]
    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise ValidationError(
            f"Некорректный JSON внутри {path}: {exc.msg} "
            f"(строка {exc.lineno}, столбец {exc.colno})."
        ) from exc

    if not isinstance(payload, dict):
        raise ValidationError(f"Корень JSON в {path} должен быть объектом.")

    header = XPJHeader(version=raw_header[1], platform=raw_header[4])
    return header, payload, json_text


def dumps_xpj(header: XPJHeader, payload: dict[str, Any]) -> bytes:
    """Сериализовать заголовок + JSON и сжать gzip."""
    try:
        json_text = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ExportError(f"Не удалось сериализовать JSON проекта: {exc}") from exc

    text = "\n".join(header.lines()) + "\n" + json_text
    return gzip.compress(text.encode("utf-8"), compresslevel=9, mtime=0)


def write_xpj(path: Path, header: XPJHeader, payload: dict[str, Any]) -> Path:
    """Записать .xpj в указанный (обычно временный) путь."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = dumps_xpj(header, payload)
    try:
        path.write_bytes(data)
    except OSError as exc:
        raise ExportError(f"Не удалось записать {path}: {exc}") from exc
    return path


def write_json_file(path: Path, payload: dict[str, Any]) -> Path:
    """Записать pretty JSON через временный файл в той же папке."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(
                payload,
                handle,
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
            handle.write("\n")
        os.replace(temp_path, path)
    except (OSError, TypeError, ValueError) as exc:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise ExportError(f"Не удалось записать {path}: {exc}") from exc
    return path
