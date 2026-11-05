"""CLI mpc_xpj_builder."""

from __future__ import annotations

import argparse
import logging
import sys
import traceback
from pathlib import Path
from typing import Sequence

from errors import InputError, MpcBuilderError
from midi_reader import MidiFileData, read_midi
from project_writer import write_project
from sample_map import prepare_mapped_pool
from validators import (
    MAX_BPM,
    MIN_BPM,
    PPQ,
    validate_bpm,
    validate_export_targets,
    validate_map_path,
    validate_midi_path,
    validate_note_range,
    validate_notes_present,
    validate_output_dir,
    validate_project_name,
    validate_sample_count,
    validate_sample_directory,
    validate_samples_cover_notes,
    validate_template_path,
)
from wav_pool import WavPool, build_wav_pool
from xpj_inspector import inspect_xpj
from xpj_schema import (
    BuildPlan,
    assign_samples_to_pads,
    build_from_template,
    default_note_to_pad,
    extract_note_to_pad,
    require_reference,
    sequence_timing,
    unresolved_fields,
    validate_template_payload,
)
from xpj_writer import XPJHeader, read_xpj


def _logger() -> logging.Logger:
    return logging.getLogger("mpc_xpj_builder")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mpc_xpj_builder",
        description=(
            "Создание минимального drum-проекта Akai MPC Sample (.xpj) "
            "из папки WAV и Standard MIDI File."
        ),
    )
    parser.add_argument(
        "--inspect",
        metavar="XPJ",
        type=Path,
        help="Только прочитать reference.xpj и сохранить reference_pretty.json.",
    )
    parser.add_argument("--samples", type=Path, help="Папка с WAV-семплами.")
    parser.add_argument("--midi", type=Path, help="Standard MIDI File (.mid/.midi).")
    parser.add_argument("--name", help="Имя проекта без пути.")
    parser.add_argument("--bpm", type=float, help=f"BPM ({MIN_BPM:g}..{MAX_BPM:g}).")
    parser.add_argument("--output", type=Path, help="Целевая папка экспорта.")
    parser.add_argument(
        "--template",
        type=Path,
        help=(
            "Эталонный .xpj от MPC Sample. Обязателен для реального экспорта; "
            "без него доступен только --dry-run."
        ),
    )
    parser.add_argument(
        "--map",
        dest="sample_map",
        type=Path,
        help=(
            "JSON-карта WAV -> MIDI note. Без неё семплы назначаются "
            "позиционно по сортировке имён."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Показать план и калибровочные ограничения, ничего не создавать.",
    )
    parser.add_argument("--verbose", action="store_true", help="Подробный лог.")
    parser.add_argument(
        "--pretty-out",
        type=Path,
        help="Куда сохранить JSON при --inspect (по умолчанию ./reference_pretty.json).",
    )
    return parser


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
    )


def _require_arg(value: object, name: str) -> None:
    if value is None:
        raise InputError(f"Не задан обязательный аргумент {name}.")


def _print_plan(plan: BuildPlan, header_version: str | None) -> None:
    print("MPC XPJ Builder — план экспорта")
    print(f"  Project:       {plan.project_name}")
    print(f"  XPJ:           {plan.xpj_path}")
    print(f"  ProjectData:   {plan.data_dir}")
    print(f"  BPM:           {plan.bpm:g}")
    print(f"  Template:      {plan.template_path or 'НЕ ПРЕДОСТАВЛЕН'}")
    print(f"  Sample map:    {plan.mapping_path or 'нет (позиционное назначение)'}")
    if header_version:
        print(f"  Firmware:      {header_version}")
    print(
        f"  MIDI:          {len(plan.midi.notes)} notes, "
        f"{plan.midi.time_signature[0]}/{plan.midi.time_signature[1]}, "
        f"{plan.sequence_bars} bar(s), {plan.sequence_pulses} pulses @ {PPQ} PPQ"
    )
    if plan.midi.tempo_bpm is not None:
        print(f"  MIDI tempo:    {plan.midi.tempo_bpm:.3f} BPM (используется --bpm)")
    print(f"  WAV samples:   {len(plan.wavs)}")
    for binding in plan.bindings:
        note = (
            f"note {binding.midi_note}"
            if binding.midi_note is not None
            else "без MIDI-ноты"
        )
        extras: list[str] = []
        if binding.gain is not None:
            extras.append(f"gain={binding.gain:g}")
        if binding.pan is not None:
            extras.append(f"pan={binding.pan:g}")
        if binding.tune is not None:
            extras.append(f"tune={binding.tune:g}")
        if binding.loop is not None:
            extras.append(f"loop={binding.loop}")
        suffix = f"  [{', '.join(extras)}]" if extras else ""
        print(
            f"    pad {binding.pad_index + 1:03d}/128  {note:<14}  "
            f"{binding.sample.source.name} -> {binding.sample.output_name}"
            f"{suffix}"
        )
    print("  Events:")
    for note in plan.midi.notes[:20]:
        print(
            f"    t={note.start_tick:>6}..{note.end_tick:<6} "
            f"pitch={note.pitch:<3} vel={note.velocity:<3} ch={note.channel}"
        )
    if len(plan.midi.notes) > 20:
        print(f"    ... ещё {len(plan.midi.notes) - 20} note(s)")


def _print_calibration() -> None:
    print("Калибровочные ограничения (без эталона нельзя гарантировать загрузку):")
    for item in unresolved_fields():
        print(f"  - {item.path}: {item.reason}")


def _make_plan(
    args: argparse.Namespace,
) -> tuple[BuildPlan, XPJHeader | None, dict | None]:
    _require_arg(args.samples, "--samples")
    _require_arg(args.midi, "--midi")
    _require_arg(args.name, "--name")
    _require_arg(args.bpm, "--bpm")
    _require_arg(args.output, "--output")

    project_name = validate_project_name(args.name)
    bpm = validate_bpm(args.bpm)
    samples_dir = validate_sample_directory(args.samples)
    midi_path = validate_midi_path(args.midi)
    output_dir = validate_output_dir(args.output)
    template_path = validate_template_path(args.template)
    mapping_path = validate_map_path(args.sample_map)
    xpj_path, data_dir = validate_export_targets(output_dir, project_name)

    midi: MidiFileData = read_midi(midi_path)
    _logger().debug(
        "MIDI: ppq=%d notes=%d end_tick=%d tempo=%s",
        midi.ppq,
        len(midi.notes),
        midi.end_tick,
        midi.tempo_bpm,
    )
    validate_notes_present(len(midi.notes))
    validate_note_range({note.pitch for note in midi.notes})

    template_header: XPJHeader | None = None
    template_payload: dict | None = None
    if template_path is not None:
        template_header, template_payload, _ = read_xpj(template_path)
        validate_template_payload(template_payload)
        note_to_pad = extract_note_to_pad(template_payload)
        _logger().debug(
            "Шаблон прочитан: версия %s, platform=%s",
            template_header.version,
            template_header.platform,
        )
    else:
        note_to_pad = default_note_to_pad()
        _logger().warning(
            "Эталонный .xpj не указан: карта нот используется только для "
            "планирования; реальный экспорт будет заблокирован."
        )

    if mapping_path is not None:
        pool, bindings = prepare_mapped_pool(
            mapping_path, samples_dir, note_to_pad
        )
        _logger().debug("Карта семплов: %s", mapping_path)
    else:
        pool = build_wav_pool(samples_dir)
        validate_sample_count(pool.count)
        unique_notes = len({note.pitch for note in midi.notes})
        validate_samples_cover_notes(pool.count, unique_notes)
        bindings = assign_samples_to_pads(pool.samples, midi, note_to_pad)

    _logger().debug("Семплов в проекте: %d", pool.count)
    for sample in pool.samples:
        _logger().debug(
            "WAV %s: %d frames, %d Hz, %d ch, %d bit, %s",
            sample.source,
            sample.info.frames,
            sample.info.sample_rate,
            sample.info.channels,
            sample.info.bits_per_sample,
            sample.info.codec,
        )

    bars, sequence_pulses, bar_pulses, signature = sequence_timing(midi)

    plan = BuildPlan(
        project_name=project_name,
        bpm=bpm,
        output_dir=output_dir,
        xpj_path=xpj_path,
        data_dir=data_dir,
        wavs=pool.samples,
        midi=midi,
        bindings=bindings,
        sequence_bars=bars,
        sequence_pulses=sequence_pulses,
        bar_pulses=bar_pulses,
        time_signature=signature,
        template_path=template_path,
        mapping_path=mapping_path,
    )
    return plan, template_header, template_payload


def _run_export(args: argparse.Namespace) -> int:
    plan, template_header, template_payload = _make_plan(args)
    header_version = template_header.version if template_header else None

    if args.dry_run:
        _print_plan(plan, header_version)
        if template_payload is None:
            _print_calibration()
            print("Dry-run: реальный экспорт без --template заблокирован.")
        else:
            print("Dry-run: файлы не создавались.")
        return 0

    if template_payload is None or template_header is None:
        _print_plan(plan, header_version)
        require_reference("data.tracks[].program.drum (полная структура проекта)")

    new_payload = build_from_template(template_payload, plan)
    xpj_path, data_dir = write_project(plan, template_header, new_payload)

    print("Проект создан.")
    print(f"  XPJ:         {xpj_path}")
    print(f"  ProjectData: {data_dir}")
    print(f"  Samples:     {len(plan.wavs)}")
    print(f"  Notes:       {len(plan.midi.notes)}")
    print(f"  Bars:        {plan.sequence_bars}")
    print(
        "  Schema:      неизвестные поля сохранены из --template; "
        "см. unresolved_fields() в xpj_schema.py"
    )
    return 0


def _run_inspect(args: argparse.Namespace) -> int:
    _require_arg(args.inspect, "--inspect")
    pretty_path = args.pretty_out or (Path.cwd() / "reference_pretty.json")
    inspect_xpj(args.inspect, pretty_path)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)

    try:
        if args.inspect is not None:
            return _run_inspect(args)
        return _run_export(args)
    except MpcBuilderError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        if exc.details:
            print(exc.details, file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        print("Прервано пользователем.", file=sys.stderr)
        return 130
    except Exception as exc:  # pragma: no cover - защита CLI от трейсбеков
        _logger().error("Неожиданная ошибка: %s", exc)
        if args.verbose:
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
