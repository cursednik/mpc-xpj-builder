"""Схема MPC-проекта и перенос данных в эталонный .xpj.

Главный принцип модуля: не придумывать поля, которых нет в эталоне.
Мы клонируем структуру реального .xpj и меняем только документированные
участки (имя, BPM, samples, pads, notes). Всё неизвестное сохраняется.
"""

from __future__ import annotations

import copy
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from errors import SchemaCalibrationError, ValidationError
from midi_reader import MidiFileData, to_pulses
from sample_map import PadBinding
from validators import (
    MAX_DRUM_NOTE,
    MAX_SAMPLES,
    MIN_DRUM_NOTE,
    PPQ,
    validate_note_range,
    validate_samples_cover_notes,
)
from wav_pool import PoolSample

REFERENCE_REQUIRED_MESSAGE = (
    "Требуется эталонный .xpj от MPC Sample для заполнения схемы"
)
INT64_MAX = 9223372036854775807
PAD_COUNT = 128


@dataclass(frozen=True)
class BuildPlan:
    """Полный план экспорта, пригодный для dry-run и записи."""

    project_name: str
    bpm: float
    output_dir: Path
    xpj_path: Path
    data_dir: Path
    wavs: tuple[PoolSample, ...]
    midi: MidiFileData
    bindings: tuple[PadBinding, ...]
    sequence_bars: int
    sequence_pulses: int
    bar_pulses: int
    time_signature: tuple[int, int]
    template_path: Path | None
    mapping_path: Path | None = None


@dataclass(frozen=True)
class UnknownField:
    """Поле, которое нельзя безопасно синтезировать без эталона."""

    path: str
    reason: str


def unresolved_fields() -> tuple[UnknownField, ...]:
    """Перечень участков схемы, которые закрываются только эталоном."""
    return (
        UnknownField(
            "header (version/platform)",
            "Версия прошивки и platform должны совпадать с эталонным .xpj.",
        ),
        UnknownField(
            "data.*",
            "Около 60 UI/controller/mixer-полей: TUI layouts, Q-Link, XY Pad, "
            "assignable controllers, snapshotter, MIDI Learn, scene, arpeggiator и др.",
        ),
        UnknownField(
            "data.tracks[].program.programPads / base.*",
            "Цвета падов, custom Q-Links, macro scenes и controller mapping.",
        ),
        UnknownField(
            "data.tracks[].program.drum.instruments[]",
            "Версия instrument, synthSection, articulations, chopProperties, "
            "padEffects, modLinks, noteCounters и random seeds.",
        ),
        UnknownField(
            "data.tracks[].program.padNoteMap",
            "Соответствие pad -> MIDI note зависит от модели/шаблона; "
            "на MPC Sample наблюдалось 36..51 -> pad 1..16 и 35 -> pad 128.",
        ),
        UnknownField(
            "data.samples[].loadImpl / metadata",
            "Семантика loadImpl (0/1), tempo, rootNote, tune и key не подтверждена "
            "для всех прошивок.",
        ),
        UnknownField(
            "data.sequences[].trackClipMaps / events",
            "Служебные поля клипов и note modifiers (articulation, invented, "
            "quantisation, perClipParameterValues) переносятся из эталона.",
        ),
        UnknownField(
            "data.mixer",
            "Зеркало инфраструктурных треков; должно оставаться согласованным "
            "с data.tracks[].",
        ),
        UnknownField(
            "data.version / formatVersion",
            "Версия схемы зависит от прошивки MPC Sample.",
        ),
        UnknownField(
            "ProjectData",
            "Фактическое имя папки: <ProjectName>_[ProjectData]; подтверждено "
            "сторонними реализациями, но требует проверки на целевой прошивке.",
        ),
    )


def require_reference(field_path: str = "data") -> NoReturn:
    """Явная заглушка для полей, которые нельзя заполнить без эталона."""
    details = [f"Не заполнено: {field_path}."]
    details.extend(
        f"- {item.path}: {item.reason}" for item in unresolved_fields()
    )
    raise SchemaCalibrationError(
        REFERENCE_REQUIRED_MESSAGE,
        details="\n".join(details),
    )


def build_project_without_reference(plan: BuildPlan) -> NoReturn:
    """Заглушка экспорта без эталонного проекта.

    TODO: заменить на построение JSON после калибровки всех полей
    (см. unresolved_fields) на реальном .xpj от целевой прошивки MPC Sample.
    """
    del plan
    require_reference("data.tracks[].program.drum (полная структура проекта)")


def default_note_to_pad() -> dict[int, int]:
    """Наблюдённая на MPC Sample карта drum-нот для планирования dry-run.

    Значения 36..51 соответствуют Bank A Pad 1..16, нота 35 — последнему
    паду (индекс 127). Это не подставляется в реальный экспорт: для него
    карта берётся из эталонного .xpj.
    """
    mapping = {35: 127}
    for note in range(36, 52):
        mapping[note] = note - 36
    return mapping


def _require_dict(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        require_reference(path)
    return value


def _require_list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        require_reference(path)
    return value


def find_drum_track_index(data: dict[str, Any]) -> int:
    """Найти первый content-track с drum program."""
    tracks = _require_list(data.get("tracks"), "data.tracks")
    for index, track in enumerate(tracks):
        if not isinstance(track, dict):
            continue
        program = track.get("program")
        if not isinstance(program, dict) or program.get("type") != 0:
            continue
        drum = program.get("drum")
        if not isinstance(drum, dict):
            continue
        instruments = drum.get("instruments")
        if isinstance(instruments, list) and instruments:
            return index
    require_reference("data.tracks[].program.drum")


def extract_note_to_pad(payload: dict[str, Any]) -> dict[int, int]:
    """Извлечь карту MIDI note -> pad index из эталонного проекта."""
    data = _require_dict(payload.get("data"), "data")
    track_index = find_drum_track_index(data)
    track = data["tracks"][track_index]
    program = _require_dict(track.get("program"), "data.tracks[].program")

    pad_note_map = program.get("padNoteMap")
    if not isinstance(pad_note_map, dict):
        drum = program.get("drum")
        pad_note_map = drum.get("padNoteMap") if isinstance(drum, dict) else None
    if not isinstance(pad_note_map, dict):
        require_reference("data.tracks[].program.padNoteMap")

    note_for_pad = pad_note_map.get("noteForPad")
    if not isinstance(note_for_pad, dict):
        require_reference("data.tracks[].program.padNoteMap.noteForPad")

    note_to_pad: dict[int, int] = {}
    for pad_index in range(PAD_COUNT):
        key = f"value{pad_index}"
        if key not in note_for_pad:
            require_reference(f"padNoteMap.noteForPad.{key}")
        try:
            note = int(note_for_pad[key])
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                f"Некорректная нота для pad {pad_index} в шаблоне."
            ) from exc
        if note in note_to_pad:
            if MIN_DRUM_NOTE <= note <= MAX_DRUM_NOTE:
                raise ValidationError(
                    f"Шаблон назначает drum-ноту {note} на несколько падов."
                )
            continue
        note_to_pad[note] = pad_index
    return note_to_pad


def validate_template_payload(payload: dict[str, Any]) -> None:
    """Проверить минимум, необходимый для переноса данных."""
    data = _require_dict(payload.get("data"), "data")
    track_index = find_drum_track_index(data)
    track = data["tracks"][track_index]
    program = _require_dict(track.get("program"), "data.tracks[].program")
    drum = _require_dict(program.get("drum"), "data.tracks[].program.drum")
    instruments = _require_list(
        drum.get("instruments"), "data.tracks[].program.drum.instruments"
    )
    if len(instruments) != PAD_COUNT:
        require_reference(
            f"data.tracks[].program.drum.instruments[] (нужно {PAD_COUNT}, "
            f"в шаблоне {len(instruments)})"
        )
    for index, instrument in enumerate(instruments):
        if not isinstance(instrument, dict):
            require_reference(f"instruments[{index}]")
        layers = instrument.get("layersv")
        if not isinstance(layers, list) or not layers:
            require_reference(f"instruments[{index}].layersv")

    sequences = _require_list(data.get("sequences"), "data.sequences")
    if not sequences or not isinstance(sequences[0], dict):
        require_reference("data.sequences[0]")

    extract_note_to_pad(payload)


def assign_samples_to_pads(
    samples: tuple[PoolSample, ...],
    midi: MidiFileData,
    note_to_pad: dict[int, int],
    *,
    allow_extended_notes: bool = False,
) -> tuple[PadBinding, ...]:
    """Сопоставить WAV-семплы нотам и свободным падам.

    Первые N семплов (в стабильном порядке имён) назначаются N уникальным
    нотам в возрастающем порядке. Остальные семплы занимают свободные пады.
    """
    if len(samples) > MAX_SAMPLES:
        raise ValidationError("Слишком много семплов.")
    pitches = sorted({note.pitch for note in midi.notes})
    validate_note_range(pitches, extended=allow_extended_notes)
    validate_samples_cover_notes(len(samples), len(pitches))

    used_pads: set[int] = set()
    bindings: list[PadBinding] = []

    for sample, pitch in zip(samples, pitches):
        pad_index = note_to_pad.get(pitch)
        if pad_index is None:
            raise ValidationError(
                f"В эталонном .xpj нет pad для MIDI note {pitch}; "
                "нужен шаблон с drum-картой, включающей 35..51."
            )
        if not 0 <= pad_index < PAD_COUNT:
            raise ValidationError(
                f"Некорректный pad index {pad_index} для MIDI note {pitch}."
            )
        if pad_index in used_pads:
            raise ValidationError(
                f"MIDI note {pitch} и другая нота ведут на один pad {pad_index}."
            )
        used_pads.add(pad_index)
        bindings.append(
            PadBinding(sample=sample, pad_index=pad_index, midi_note=pitch)
        )

    next_pad = 0
    for sample in samples[len(pitches) :]:
        while next_pad in used_pads:
            next_pad += 1
        if next_pad >= PAD_COUNT:
            raise ValidationError("Не хватило свободных pad-слотов для семплов.")
        used_pads.add(next_pad)
        bindings.append(
            PadBinding(sample=sample, pad_index=next_pad, midi_note=None)
        )
        next_pad += 1

    return tuple(bindings)


def sequence_timing(midi: MidiFileData) -> tuple[int, int, int, tuple[int, int]]:
    """Рассчитать bars/pulses sequence из MIDI."""
    numerator, denominator = midi.time_signature
    if numerator < 1 or numerator > 32:
        raise ValidationError(f"Неподдерживаемый размер такта: {numerator}.")
    if denominator < 1 or denominator > 32:
        raise ValidationError(f"Неподдерживаемый знаменатель такта: {denominator}.")

    beat_length = (PPQ * 4) // denominator
    if beat_length * denominator != PPQ * 4:
        raise ValidationError(
            f"Знаменатель {denominator} не выражается целым числом пульсов MPC."
        )
    bar_pulses = numerator * beat_length

    final_tick = max(midi.end_tick, *(note.end_tick for note in midi.notes))
    end_pulse = to_pulses(final_tick, midi.ppq, PPQ)
    bars = max(1, (end_pulse + bar_pulses - 1) // bar_pulses)
    sequence_pulses = bars * bar_pulses
    return bars, sequence_pulses, bar_pulses, (numerator, denominator)


def float32(value: float) -> float:
    """Привести float к точности 32 бит, как в прошивке MPC."""
    return struct.unpack("<f", struct.pack("<f", value))[0]


def _find_sequence_value(data: dict[str, Any]) -> dict[str, Any]:
    sequences = _require_list(data.get("sequences"), "data.sequences")
    if not sequences:
        require_reference("data.sequences[0]")
    wrapper = _require_dict(sequences[0], "data.sequences[0]")
    value = wrapper.get("value")
    return _require_dict(value, "data.sequences[0].value")


def _template_clip_order(
    data: dict[str, Any],
    rename_map: dict[str, str],
) -> tuple[str, ...]:
    """Порядок клипов в первой строке trackClipMaps из эталона."""
    sequence = _find_sequence_value(data)
    rows = sequence.get("trackClipMaps")
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], list):
        return ()
    result: list[str] = []
    for clip in rows[0]:
        if not isinstance(clip, dict):
            continue
        key = clip.get("key")
        if not isinstance(key, str):
            continue
        result.append(rename_map.get(key, key))
    return tuple(result)


def _find_clip_prototype(data: dict[str, Any]) -> dict[str, Any] | None:
    sequence = _find_sequence_value(data)
    rows = sequence.get("trackClipMaps")
    if not isinstance(rows, list):
        return None
    for row in rows:
        if not isinstance(row, list):
            continue
        for clip in row:
            if isinstance(clip, dict) and isinstance(clip.get("value"), dict):
                return clip["value"]
    return None


def _find_event_list_prototype(data: dict[str, Any]) -> dict[str, Any] | None:
    clip = _find_clip_prototype(data)
    if clip is not None and isinstance(clip.get("eventList"), dict):
        return clip["eventList"]
    sequence = _find_sequence_value(data)
    if isinstance(sequence.get("seqEventList"), dict):
        return sequence["seqEventList"]
    return None


def _find_note_event_prototype(data: dict[str, Any]) -> dict[str, Any] | None:
    sequence = _find_sequence_value(data)
    rows = sequence.get("trackClipMaps")
    if not isinstance(rows, list):
        return None
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
            if not isinstance(events, list):
                continue
            for event in events:
                if (
                    isinstance(event, dict)
                    and event.get("type") == 3
                    and isinstance(event.get("note"), dict)
                ):
                    return event
    return None


def _find_sample_entry_prototype(data: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("samples",):
        samples = data.get(key)
        if isinstance(samples, list):
            for entry in samples:
                if isinstance(entry, dict):
                    return entry
    tracks = data.get("tracks")
    if isinstance(tracks, list):
        for track in tracks:
            if not isinstance(track, dict):
                continue
            samples = track.get("samples")
            if isinstance(samples, list):
                for entry in samples:
                    if isinstance(entry, dict):
                        return entry
    return None


def _clear_effects(track_like: Any) -> None:
    """Очистить insert-FX у track/program-подобного объекта."""
    if not isinstance(track_like, dict):
        return
    program = track_like.get("program")
    target = program if isinstance(program, dict) else track_like
    mixable = target.get("mixable")
    if not isinstance(mixable, dict):
        return
    inserts = mixable.get("inserts")
    if isinstance(inserts, dict):
        inserts["effects"] = []


def _find_blank_instrument(instruments: list[Any]) -> dict[str, Any] | None:
    for instrument in instruments:
        if not isinstance(instrument, dict):
            continue
        layers = instrument.get("layersv")
        if not isinstance(layers, list) or not layers:
            continue
        first = layers[0]
        if isinstance(first, dict) and not first.get("sampleFile"):
            return instrument
    return None


def _clear_instrument(instrument: dict[str, Any]) -> None:
    instrument["coarseTune"] = 0
    instrument["fineTune"] = 0
    layers = instrument.get("layersv")
    if not isinstance(layers, list) or not layers:
        require_reference("instruments[].layersv")
    for layer in layers:
        if not isinstance(layer, dict):
            continue
        layer["active"] = False
        layer["sampleName"] = ""
        layer["sampleFile"] = ""
        layer["sampleStart"] = 0
        layer["sampleEnd"] = 0
        layer["pitch"] = 0.0
        slice_info = layer.get("sliceInfo")
        if isinstance(slice_info, dict):
            slice_info["Start"] = 0
            slice_info["End"] = 0
            slice_info["LoopStart"] = 0


def _tune_parts(tune: float) -> tuple[int, int]:
    """Разложить дробные полутона в coarseTune/fineTune."""
    coarse = int(tune)
    fine = int(round((tune - coarse) * 100.0))
    if fine >= 100:
        coarse += 1
        fine -= 100
    elif fine <= -100:
        coarse -= 1
        fine += 100
    return coarse, fine


def _assign_layer(layer: dict[str, Any], binding: PadBinding) -> None:
    # В реальных MPC Sample-проектах sampleEnd = 0, а длина задаётся
    # sliceInfo.End (последний фрейм, frames - 1).
    sample = binding.sample
    layer["active"] = True
    layer["sampleName"] = sample.display_name
    layer["sampleFile"] = sample.output_name
    layer["sampleStart"] = 0
    layer["sampleEnd"] = 0
    layer["sliceIndex"] = 129
    loop_enabled = bool(binding.loop) if binding.loop is not None else False
    layer["loop"] = loop_enabled
    layer["loopMode"] = 1 if loop_enabled else 0
    layer["layerLoopModeOverridesSliceLoopMode"] = loop_enabled

    if binding.tune is not None:
        coarse, fine = _tune_parts(binding.tune)
        layer["coarseTune"] = coarse
        layer["fineTune"] = fine
        layer["pitch"] = float(binding.tune)
    else:
        layer["coarseTune"] = 0
        layer["fineTune"] = 0
        layer["pitch"] = 0.0

    if binding.gain is not None:
        volume = layer.get("volume")
        if not isinstance(volume, dict):
            volume = {"law": 1}
            layer["volume"] = volume
        volume["gainCoefficient"] = float(binding.gain)
        volume["controlValue"] = float(binding.gain)

    if binding.pan is not None:
        layer["pan"] = float(binding.pan)

    slice_info = layer.get("sliceInfo")
    if not isinstance(slice_info, dict):
        slice_info = {}
        layer["sliceInfo"] = slice_info
    slice_info["Start"] = 0
    slice_info["End"] = max(0, sample.info.frames - 1)
    slice_info["LoopStart"] = 0
    slice_info["LoopMode"] = 1 if loop_enabled else 0
    if loop_enabled:
        layer["loopStart"] = 0
        layer["loopEnd"] = max(0, sample.info.frames - 1)
    else:
        layer["loopStart"] = 0
        layer["loopEnd"] = 0
    slice_info.setdefault("PulsePosition", 0)
    slice_info.setdefault("LoopCrossfadeLength", 0)
    slice_info.setdefault("LoopCrossfadeType", 0)
    slice_info.setdefault("TailLength", 0.0)
    slice_info.setdefault("TailLoopPosition", 0.5)


def _new_note_event() -> dict[str, Any]:
    note: dict[str, Any] = {
        "version": 1,
        "note": 36,
        "velocity": 1.0,
        "length": 1,
        "probability": 100,
        "ratchet": 1,
        "articulation": 197,
    }
    for index in range(16):
        if index in (0, 1, 5):
            note[f"modifierValue{index}"] = 0.5
        elif index == 6:
            note[f"modifierValue{index}"] = 1.0
        else:
            note[f"modifierValue{index}"] = 0.0
        note[f"modifierActiveState{index}"] = False
    note["EnumCerealisationWrapper(selectedModifierType)"] = "Tuning (coarse)"
    return {
        "version": 2,
        "time": 0,
        "type": 3,
        "channel": 0,
        "selected": False,
        "muted": False,
        "invented": False,
        "note": note,
    }


def _build_note_events(
    midi: MidiFileData,
    prototype: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    # TODO: калибровать articulation и note modifiers по эталону; сейчас
    # используются документированные значения по умолчанию.
    events: list[dict[str, Any]] = []
    for note in midi.notes:
        event = copy.deepcopy(prototype) if prototype is not None else _new_note_event()
        start = to_pulses(note.start_tick, midi.ppq, PPQ)
        end = max(start + 1, to_pulses(note.end_tick, midi.ppq, PPQ))
        event["version"] = 2
        event["time"] = start
        event["type"] = 3
        event["channel"] = 0
        event["selected"] = False
        event["muted"] = False
        event["invented"] = False

        note_obj = event.get("note")
        if not isinstance(note_obj, dict):
            note_obj = _new_note_event()["note"]
            event["note"] = note_obj
        note_obj["version"] = 1
        note_obj["note"] = note.pitch
        note_obj["velocity"] = max(0.0, min(1.0, note.velocity / 127.0))
        note_obj["length"] = max(1, end - start)
        note_obj["probability"] = 100
        note_obj["ratchet"] = 1
        note_obj["articulation"] = 197
        for index in range(16):
            default = 0.5 if index in (0, 1, 5) else (1.0 if index == 6 else 0.0)
            note_obj[f"modifierValue{index}"] = note_obj.get(
                f"modifierValue{index}", default
            )
            note_obj[f"modifierActiveState{index}"] = False
        note_obj["EnumCerealisationWrapper(selectedModifierType)"] = "Tuning (coarse)"
        events.append(event)

    events.sort(key=lambda event: (int(event["time"]), int(event["note"]["note"])))
    return events


def _build_event_list(
    prototype: dict[str, Any] | None,
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    event_list = copy.deepcopy(prototype) if prototype is not None else {}
    event_list["length"] = INT64_MAX
    event_list["events"] = events
    event_list["version"] = 2
    if not isinstance(event_list.get("quantisation"), dict):
        event_list["quantisation"] = {
            "version": 1,
            "pulses": 0,
            "swing": 0.0,
            "strength": 1.0,
        }
    event_list["numFilterTypes"] = 30
    return event_list


def _build_clip(
    prototype: dict[str, Any] | None,
    event_list_prototype: dict[str, Any] | None,
    name: str,
    end_pulses: int,
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    clip = copy.deepcopy(prototype) if prototype is not None else {}
    clip["version"] = 2
    clip["launchQuantisation"] = 1
    clip["startPulses"] = 0
    clip["endPulses"] = end_pulses
    clip["loopStartPulses"] = 0
    clip["loopEndPulses"] = end_pulses
    clip["loop"] = True
    clip["legato"] = True
    clip["launch"] = 0
    clip["name"] = name
    clip["colour"] = 0
    clip["eventList"] = _build_event_list(event_list_prototype, events)
    if not isinstance(clip.get("perClipParameterValues"), dict):
        clip["perClipParameterValues"] = {"perClipParameterValues": []}
    return clip


def _make_sample_entry(
    prototype: dict[str, Any] | None,
    sample: PoolSample,
    bpm: float,
    project_key: str,
) -> dict[str, Any]:
    entry = copy.deepcopy(prototype) if prototype is not None else {
        "version": 1,
        "name": sample.display_name,
        "path": sample.output_name,
        "loadImpl": 1,
        "metadata": {},
    }
    entry["version"] = 1
    entry["name"] = sample.display_name
    entry["path"] = sample.output_name
    entry.setdefault("loadImpl", 1)
    metadata = entry.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
        entry["metadata"] = metadata
    # TODO: подтвердить loadImpl и metadata (tempo/rootNote/tune/key) на
    # эталонном проекте целевой прошивки.
    # tempo относится к новому семплу; остальные поля сохраняем из эталона.
    metadata["tempo"] = float32(bpm)
    metadata.setdefault("rootNote", 60)
    metadata.setdefault("tune", 0.0)
    metadata.setdefault("key", project_key)
    return entry


def _build_sequence(
    sequence_prototype: dict[str, Any],
    event_list_prototype: dict[str, Any] | None,
    clip_prototype: dict[str, Any] | None,
    note_event_prototype: dict[str, Any] | None,
    plan: BuildPlan,
    track_names: tuple[str, ...],
    drum_track_index: int,
    clip_order: tuple[str, ...],
) -> dict[str, Any]:
    sequence = copy.deepcopy(sequence_prototype)
    sequence["version"] = sequence.get("version", 5)
    sequence["name"] = plan.project_name
    sequence["bpm"] = float32(plan.bpm)
    sequence["lengthBars"] = plan.sequence_bars
    sequence["loopStartBar"] = 0
    sequence["loopEndBar"] = plan.sequence_bars
    sequence["loop"] = True
    sequence["tempoEnable"] = True
    sequence["transposition"] = 0
    sequence["lengthPulses"] = plan.sequence_pulses
    sequence["loopStartPulses"] = 0
    sequence["loopEndPulses"] = plan.sequence_pulses
    sequence["autoSelectTrackIndex"] = -1

    numerator, denominator = plan.time_signature
    beat_length = (PPQ * 4) // denominator
    sequence["timeSignatureTrack"] = {
        "timeSignatures": [
            {
                "beatsPerBar": numerator,
                "beatLength": beat_length,
                "barStart": 0,
            }
        ]
    }

    # В реальных проектах trackClipMaps — это ровно одна строка, внутри
    # которой лежит по одному клипу на каждый трек.
    note_events = _build_note_events(plan.midi, note_event_prototype)
    clip_by_name: dict[str, dict[str, Any]] = {}
    for index, track_name in enumerate(track_names):
        clip_by_name[track_name] = _build_clip(
            prototype=clip_prototype,
            event_list_prototype=event_list_prototype,
            name=track_name,
            end_pulses=plan.sequence_pulses,
            events=note_events if index == drum_track_index else [],
        )
    ordered_names = [
        name for name in clip_order if name in clip_by_name
    ]
    ordered_names.extend(name for name in track_names if name not in ordered_names)
    clips = [
        {"key": track_name, "value": clip_by_name[track_name]}
        for track_name in ordered_names
    ]
    sequence["trackClipMaps"] = [clips]
    sequence["seqEventList"] = _build_event_list(
        sequence.get("seqEventList") if isinstance(sequence.get("seqEventList"), dict) else None,
        [],
    )
    if not isinstance(sequence.get("smpteStart"), dict):
        sequence["smpteStart"] = {
            "hours": 0,
            "mins": 0,
            "secs": 0,
            "frames": 0,
            "subframes": 0,
        }
    return sequence


def build_from_template(
    template_payload: dict[str, Any],
    plan: BuildPlan,
) -> dict[str, Any]:
    """Собрать новый payload, модифицируя только известные поля эталона."""
    payload = copy.deepcopy(template_payload)
    data = _require_dict(payload.get("data"), "data")
    validate_template_payload(payload)

    old_tracks = _require_list(data.get("tracks"), "data.tracks")
    drum_index = find_drum_track_index(data)
    drum_track = _require_dict(old_tracks[drum_index], "data.tracks[]")
    program = _require_dict(drum_track.get("program"), "program")
    drum = _require_dict(program.get("drum"), "program.drum")
    instruments = _require_list(drum.get("instruments"), "program.drum.instruments")

    prototype_instrument = _find_blank_instrument(instruments)
    if prototype_instrument is None:
        prototype_instrument = instruments[0]
    blank = copy.deepcopy(_require_dict(prototype_instrument, "instruments[]"))
    _clear_instrument(blank)
    for index in range(PAD_COUNT):
        instruments[index] = copy.deepcopy(blank)

    for binding in plan.bindings:
        instrument = _require_dict(instruments[binding.pad_index], "instrument")
        layers = instrument.get("layersv")
        if not isinstance(layers, list) or not layers:
            require_reference(f"instruments[{binding.pad_index}].layersv")
        layer = _require_dict(layers[0], "layersv[0]")
        if binding.tune is not None:
            coarse, fine = _tune_parts(binding.tune)
            instrument["coarseTune"] = coarse
            instrument["fineTune"] = fine
        else:
            instrument["coarseTune"] = 0
            instrument["fineTune"] = 0
        _assign_layer(layer, binding)

    sample_prototype = _find_sample_entry_prototype(data)
    project_key = data.get("key")
    if not isinstance(project_key, str) or not project_key:
        project_key = "C Major"
    sample_entries = [
        _make_sample_entry(sample_prototype, sample, plan.bpm, project_key)
        for sample in plan.wavs
    ]
    data["samples"] = sample_entries
    drum_track["samples"] = sample_entries
    old_track_name = drum_track.get("name")
    drum_track["name"] = plan.project_name
    program["name"] = plan.project_name

    clip_player = data.get("clipPlayerData")
    if isinstance(clip_player, dict) and isinstance(old_track_name, str):
        transport_map = clip_player.get("trackClipTransportMap")
        if isinstance(transport_map, list):
            for entry in transport_map:
                if isinstance(entry, dict) and entry.get("key") == old_track_name:
                    entry["key"] = plan.project_name

    kept_tracks: list[dict[str, Any]] = []
    new_drum_index = -1
    content_types = {0, 1, 2, 3, 4, 5, 6}
    for index, track in enumerate(old_tracks):
        if index == drum_index:
            new_drum_index = len(kept_tracks)
            kept_tracks.append(track)
            continue
        if not isinstance(track, dict):
            continue
        track_program = track.get("program")
        track_type = (
            track_program.get("type") if isinstance(track_program, dict) else None
        )
        if track_type in content_types:
            continue
        kept_tracks.append(track)

    if new_drum_index < 0:
        require_reference("data.tracks[] (drum track)")
    for track in kept_tracks:
        track["arrangementClipMap"] = []
        track["sharedClipMap"] = []
        _clear_effects(track)
    data["tracks"] = kept_tracks

    mixer = data.get("mixer")
    if isinstance(mixer, dict):
        _clear_effects(mixer.get("input"))
        for key in ("submixes", "outputs"):
            entries = mixer.get(key)
            if isinstance(entries, list):
                for entry in entries:
                    _clear_effects(entry)

    kept_names = {
        track.get("name") for track in kept_tracks if isinstance(track.get("name"), str)
    }
    clip_player = data.get("clipPlayerData")
    if isinstance(clip_player, dict):
        transport_map = clip_player.get("trackClipTransportMap")
        if isinstance(transport_map, list):
            transport_map[:] = [
                entry
                for entry in transport_map
                if isinstance(entry, dict) and entry.get("key") in kept_names
            ]

    track_names = tuple(
        str(track.get("name") or f"Track {index + 1}")
        for index, track in enumerate(kept_tracks)
    )
    rename_map = (
        {old_track_name: plan.project_name}
        if isinstance(old_track_name, str)
        else {}
    )
    clip_order = _template_clip_order(data, rename_map)
    sequence_prototype = _find_sequence_value(data)
    new_sequence = _build_sequence(
        sequence_prototype=sequence_prototype,
        event_list_prototype=_find_event_list_prototype(data),
        clip_prototype=_find_clip_prototype(data),
        note_event_prototype=_find_note_event_prototype(data),
        plan=plan,
        track_names=track_names,
        drum_track_index=new_drum_index,
        clip_order=clip_order,
    )
    data["sequences"] = [{"key": 0, "value": new_sequence}]
    data["currentSequence"] = 0
    data["currentTrackIndex"] = new_drum_index
    data["masterTempo"] = float32(plan.bpm)
    data["masterTempoEnabled"] = False
    data["sharedClipMatrixData"] = []

    songs = data.get("songs")
    if isinstance(songs, list):
        for song in songs:
            if isinstance(song, dict):
                song["items"] = []

    info = data.get("info")
    if isinstance(info, dict):
        info["title"] = plan.project_name

    return payload
