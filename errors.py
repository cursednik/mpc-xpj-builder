"""Ошибки и коды возврата mpc_xpj_builder."""

from __future__ import annotations


class MpcBuilderError(Exception):
    """Базовая ошибка инструмента с кодом возврата процесса."""

    exit_code: int = 1

    def __init__(self, message: str, *, details: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class InputError(MpcBuilderError):
    """Некорректные входные данные или аргументы."""

    exit_code = 2


class ValidationError(MpcBuilderError):
    """Входные файлы не прошли проверку."""

    exit_code = 3


class SchemaCalibrationError(MpcBuilderError):
    """Схема .xpj не может быть заполнена без эталонного проекта."""

    exit_code = 4


class ExportError(MpcBuilderError):
    """Ошибка записи проекта или файловой системы."""

    exit_code = 5
