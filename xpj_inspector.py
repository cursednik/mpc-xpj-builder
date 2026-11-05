"""Режим --inspect: только чтение эталонного .xpj."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from errors import ValidationError
from xpj_writer import read_xpj, write_json_file


def _describe(value: Any) -> str:
    if isinstance(value, dict):
        return f"dict[{len(value)}]"
    if isinstance(value, list):
        return f"list[{len(value)}]"
    if isinstance(value, str):
        shown = value if len(value) <= 80 else value[:77] + "..."
        return f"str = {shown!r}"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return f"bool = {value}"
    if isinstance(value, (int, float)):
        return f"{type(value).__name__} = {value!r}"
    return type(value).__name__


def inspect_xpj(path: Path, pretty_path: Path) -> Path:
    """Показать заголовок и top-level JSON, сохранить pretty-payload."""
    source = path.resolve()
    destination = pretty_path.resolve()
    if source == destination:
        raise ValidationError("Нельзя перезаписывать исходный .xpj через --inspect.")

    header, payload, json_text = read_xpj(path)
    print("XPJ header:")
    for line in header.lines():
        print(f"  {line}")
    print(f"Source: {path} ({path.stat().st_size} bytes)")
    print(f"JSON payload: {len(json_text.encode('utf-8'))} bytes")

    write_json_file(pretty_path, payload)
    print(f"Pretty JSON saved: {pretty_path}")

    print(f"Top-level keys ({len(payload)}):")
    for key in payload:
        print(f"  {key}: {_describe(payload[key])}")
    return pretty_path
