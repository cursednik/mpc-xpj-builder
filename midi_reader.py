"""Минимальный SMF reader без внешних зависимостей."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

from errors import ValidationError

_HEADER_CHUNK = b"MThd"
_TRACK_CHUNK = b"MTrk"
_DEFAULT_TIME_SIGNATURE = (4, 4)


@dataclass(frozen=True)
class MidiNote:
    """Нота в тиках исходного MIDI-файла."""

    pitch: int
    velocity: int
    start_tick: int
    end_tick: int
    channel: int


@dataclass(frozen=True)
class MidiFileData:
    """Извлечённые данные Standard MIDI File."""

    ppq: int
    notes: tuple[MidiNote, ...]
    end_tick: int
    tempo_bpm: float | None
    time_signature: tuple[int, int] = _DEFAULT_TIME_SIGNATURE


@dataclass
class _OpenNote:
    start_tick: int
    velocity: int
    order: int


def _read_varlen(data: bytes, pos: int, end: int) -> tuple[int, int]:
    value = 0
    for _ in range(4):
        if pos >= end:
            raise ValidationError("Некорректный MIDI: обрыв variable-length числа.")
        byte = data[pos]
        pos += 1
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            return value, pos
    raise ValidationError("Некорректный MIDI: variable-length число длиннее 4 байт.")


def _need(data: bytes, pos: int, count: int, end: int) -> int:
    new_pos = pos + count
    if new_pos > end:
        raise ValidationError("Некорректный MIDI: событие выходит за границы трека.")
    return new_pos


def _parse_track(
    data: bytes,
    start: int,
    end: int,
    order_start: int,
) -> tuple[list[MidiNote], int, list[tuple[int, int, int]], list[tuple[int, int, int]], int]:
    pos = start
    tick = 0
    running_status: int | None = None
    open_notes: dict[tuple[int, int], list[_OpenNote]] = {}
    notes: list[MidiNote] = []
    tempo_events: list[tuple[int, int, int]] = []
    time_signature_events: list[tuple[int, int, int]] = []
    order = order_start
    end_tick = 0

    while pos < end:
        delta, pos = _read_varlen(data, pos, end)
        tick += delta
        if pos >= end:
            raise ValidationError("Некорректный MIDI: отсутствует status byte.")

        first = data[pos]
        if first < 0x80:
            if running_status is None:
                raise ValidationError("Некорректный MIDI: data byte без running status.")
            status = running_status
        else:
            status = first
            pos += 1
            if status < 0xF0:
                running_status = status
            else:
                running_status = None

        if status == 0xFF:
            if pos >= end:
                raise ValidationError("Некорректный MIDI: обрыв meta-события.")
            meta_type = data[pos]
            pos += 1
            length, pos = _read_varlen(data, pos, end)
            pos = _need(data, pos, length, end)
            payload = data[pos - length : pos]

            if meta_type == 0x51 and length == 3:
                microseconds = int.from_bytes(payload, "big")
                if microseconds > 0:
                    tempo_events.append((tick, microseconds, order))
                    order += 1
            elif meta_type == 0x58 and length >= 2:
                numerator = payload[0]
                denominator = 2 ** payload[1]
                if numerator > 0:
                    time_signature_events.append((tick, numerator, denominator))
            elif meta_type == 0x2F:
                end_tick = max(end_tick, tick)
                break
            continue

        if status in (0xF0, 0xF7):
            length, pos = _read_varlen(data, pos, end)
            pos = _need(data, pos, length, end)
            continue

        if not 0x80 <= status <= 0xEF:
            raise ValidationError(f"Некорректный MIDI status byte: 0x{status:02X}.")

        event_type = status & 0xF0
        channel = status & 0x0F

        if event_type in (0x80, 0x90, 0xA0, 0xB0, 0xE0):
            data_len = 2
        elif event_type in (0xC0, 0xD0):
            data_len = 1
        else:
            raise ValidationError(f"Неподдерживаемое MIDI-событие: 0x{status:02X}.")

        pos = _need(data, pos, data_len, end)
        data1 = data[pos - data_len]
        data2 = data[pos - 1] if data_len == 2 else 0
        if data1 > 0x7F or (data_len == 2 and data2 > 0x7F):
            raise ValidationError(
                "Некорректный MIDI: status byte встретился внутри data-поля."
            )

        if event_type == 0x90 and data2 > 0:
            key = (channel, data1)
            open_notes.setdefault(key, []).append(
                _OpenNote(start_tick=tick, velocity=data2, order=order)
            )
            order += 1
        elif event_type in (0x80, 0x90):
            key = (channel, data1)
            pending = open_notes.get(key)
            if pending:
                opened = pending.pop(0)
                if not pending:
                    del open_notes[key]
                notes.append(
                    MidiNote(
                        pitch=data1,
                        velocity=opened.velocity,
                        start_tick=opened.start_tick,
                        end_tick=tick,
                        channel=channel,
                    )
                )

    end_tick = max(end_tick, tick)
    for (channel, pitch), pending in open_notes.items():
        for opened in pending:
            notes.append(
                MidiNote(
                    pitch=pitch,
                    velocity=opened.velocity,
                    start_tick=opened.start_tick,
                    end_tick=end_tick,
                    channel=channel,
                )
            )

    return notes, end_tick, tempo_events, time_signature_events, order


def read_midi(path: Path) -> MidiFileData:
    """Прочитать SMF формата 0/1 и извлечь note-on/note-off события."""
    if not path.is_file():
        raise ValidationError(f"MIDI-файл не найден: {path}")

    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ValidationError(f"Не удалось прочитать MIDI {path}: {exc}") from exc

    if len(data) < 14 or data[:4] != _HEADER_CHUNK:
        raise ValidationError(f"Некорректный MIDI {path}: нет MThd.")

    header_length = struct.unpack(">I", data[4:8])[0]
    if header_length < 6 or 8 + header_length > len(data):
        raise ValidationError(f"Некорректный MIDI {path}: неверная длина MThd.")

    midi_format, track_count, division = struct.unpack(">HHH", data[8:14])
    if midi_format not in (0, 1):
        raise ValidationError(
            f"Некорректный MIDI {path}: поддерживаются только format 0 и 1."
        )
    if track_count < 1:
        raise ValidationError(f"Некорректный MIDI {path}: нет треков.")
    if division & 0x8000:
        raise ValidationError("SMPTE time division не поддерживается; нужен PPQ.")
    if division == 0:
        raise ValidationError("Некорректный MIDI: PPQ равен нулю.")

    pos = 8 + header_length
    all_notes: list[MidiNote] = []
    tempo_events: list[tuple[int, int, int]] = []
    time_signature_events: list[tuple[int, int, int]] = []
    max_tick = 0
    order = 0
    parsed_tracks = 0

    while parsed_tracks < track_count and pos + 8 <= len(data):
        chunk_id = data[pos : pos + 4]
        chunk_length = struct.unpack(">I", data[pos + 4 : pos + 8])[0]
        body_start = pos + 8
        body_end = body_start + chunk_length
        if body_end > len(data):
            raise ValidationError(f"Некорректный MIDI {path}: трек выходит за файл.")

        if chunk_id == _TRACK_CHUNK:
            notes, end_tick, tempos, signatures, order = _parse_track(
                data, body_start, body_end, order
            )
            all_notes.extend(notes)
            tempo_events.extend(tempos)
            time_signature_events.extend(signatures)
            max_tick = max(max_tick, end_tick)
            parsed_tracks += 1

        pos = body_end

    if parsed_tracks == 0:
        raise ValidationError(f"Некорректный MIDI {path}: не найден MTrk.")

    if not all_notes:
        raise ValidationError(f"В MIDI {path} нет ни одной note-on/note-off пары.")

    all_notes.sort(key=lambda note: (note.start_tick, note.pitch, note.channel))
    max_tick = max(max_tick, *(note.end_tick for note in all_notes))

    tempo_bpm: float | None = None
    if tempo_events:
        tempo_events.sort()
        tempo_bpm = 60_000_000.0 / tempo_events[0][1]

    signature = _DEFAULT_TIME_SIGNATURE
    if time_signature_events:
        time_signature_events.sort()
        _, numerator, denominator = time_signature_events[0]
        signature = (numerator, denominator)

    return MidiFileData(
        ppq=division,
        notes=tuple(all_notes),
        end_tick=max_tick,
        tempo_bpm=tempo_bpm,
        time_signature=signature,
    )


def to_pulses(ticks: int, ppq: int, target_ppq: int = 960) -> int:
    """Перевести тики в пульсы MPC с округлением half-up."""
    return (ticks * target_ppq + ppq // 2) // ppq
