"""Сгенерировать набор проектов для ручного теста на MPC Sample."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import struct
import sys
import tempfile
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main as cli  # noqa: E402


def varlen(value: int) -> bytes:
    if value < 0:
        raise ValueError(value)
    out = [value & 0x7F]
    value >>= 7
    while value:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    return bytes(reversed(out))


def write_wav(path: Path, seconds: float, frequency: float) -> None:
    rate = 44100
    frames = int(rate * seconds)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        data = bytearray()
        for index in range(frames):
            position = index / rate
            fade_in = min(1.0, index / max(1, int(rate * 0.002)))
            fade_out = min(1.0, (frames - index) / max(1, int(rate * 0.02)))
            value = int(
                18000
                * fade_in
                * fade_out
                * math.sin(2 * math.pi * frequency * position)
            )
            data += struct.pack("<h", value)
        handle.writeframes(bytes(data))


def midi_to_freq(note: int) -> float:
    return 440.0 * (2.0 ** ((note - 69) / 12.0))


def build_midi(events: list[tuple[int, bytes]], end_tick: int, bpm: int = 120) -> bytes:
    ordered = sorted(enumerate(events), key=lambda item: (item[1][0], item[0]))
    body = bytearray()
    body += varlen(0) + b"\xff\x51\x03" + (60_000_000 // bpm).to_bytes(3, "big")
    body += varlen(0) + b"\xff\x58\x04\x04\x02\x18\x08"
    body += varlen(0) + b"\xff\x03" + varlen(len(b"XPJ Hardware Test")) + b"XPJ Hardware Test"

    last = 0
    for _index, (tick, payload) in ordered:
        body += varlen(tick - last)
        body += payload
        last = tick
    body += varlen(max(0, end_tick - last)) + b"\xff\x2f\x00"
    track = b"MTrk" + struct.pack(">I", len(body)) + body
    header = b"MThd" + struct.pack(">IHHH", 6, 0, 1, 960)
    return header + track


def note_events(notes: list[tuple[int, int, int, int]]) -> list[tuple[int, bytes]]:
    events: list[tuple[int, bytes]] = []
    for tick, pitch, velocity, duration in notes:
        events.append((tick, bytes([0x99, pitch, velocity])))
        events.append((tick + max(1, duration), bytes([0x89, pitch, 40])))
    return events


def write_map(path: Path, entries: list[dict]) -> None:
    path.write_text(
        json.dumps({"samples": entries}, indent=2),
        encoding="utf-8",
    )


def run_project(
    *,
    samples: Path,
    midi_path: Path,
    project_name: str,
    bpm: int,
    output: Path,
    template: Path,
    map_path: Path | None = None,
) -> None:
    arguments = [
        "--samples",
        str(samples),
        "--midi",
        str(midi_path),
        "--name",
        project_name,
        "--bpm",
        str(bpm),
        "--output",
        str(output),
        "--template",
        str(template),
    ]
    if map_path is not None:
        arguments.extend(["--map", str(map_path)])
    rc = cli.main(arguments)
    if rc != 0:
        raise SystemExit(f"Не удалось создать {project_name}: exit={rc}")


def make_kit(template: Path, output: Path, bpm: int) -> None:
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"Целевая папка уже не пуста: {output}")
    output.mkdir(parents=True, exist_ok=True)
    docs = ROOT / "docs" / "HARDWARE_TEST.md"

    with tempfile.TemporaryDirectory(
        prefix="xpj-hardware-test-", dir=Path(tempfile.gettempdir())
    ) as temp_name:
        work = Path(temp_name)

        # 1. Notes 35..51.
        notes_dir = work / "notes"
        notes_map: list[dict] = []
        notes_events: list[tuple[int, int, int, int]] = []
        for index, pitch in enumerate(range(35, 52)):
            name = f"{index + 1:02d}_note_{pitch}.wav"
            write_wav(notes_dir / name, 0.35, midi_to_freq(pitch))
            notes_map.append({"file": name, "note": pitch, "gain": 1.0, "pan": 0.5})
            notes_events.append((index * 960, pitch, 100, 480))
        notes_map_path = work / "notes-map.json"
        write_map(notes_map_path, notes_map)
        notes_midi = work / "notes.mid"
        notes_midi.write_bytes(build_midi(note_events(notes_events), 17 * 960, bpm))
        run_project(
            samples=notes_dir,
            midi_path=notes_midi,
            project_name="XPJ Test Notes",
            bpm=bpm,
            output=output,
            template=template,
            map_path=notes_map_path,
        )

        # 2. Loop sample.
        loop_dir = work / "loop"
        write_wav(loop_dir / "loop_440.wav", 2.0, 440.0)
        loop_map_path = work / "loop-map.json"
        write_map(
            loop_map_path,
            [{"file": "loop_440.wav", "note": 36, "loop": True}],
        )
        loop_midi = work / "loop.mid"
        loop_midi.write_bytes(
            build_midi(note_events([(0, 36, 100, 4 * 3840)]), 4 * 3840, bpm)
        )
        run_project(
            samples=loop_dir,
            midi_path=loop_midi,
            project_name="XPJ Test Loop",
            bpm=bpm,
            output=output,
            template=template,
            map_path=loop_map_path,
        )

        # 3. Long one-shot.
        long_dir = work / "long"
        write_wav(long_dir / "long_5s.wav", 5.0, 330.0)
        long_map_path = work / "long-map.json"
        write_map(
            long_map_path,
            [{"file": "long_5s.wav", "note": 36}],
        )
        long_midi = work / "long.mid"
        long_midi.write_bytes(
            build_midi(note_events([(0, 36, 100, 120)]), 3 * 3840, bpm)
        )
        run_project(
            samples=long_dir,
            midi_path=long_midi,
            project_name="XPJ Test Long",
            bpm=bpm,
            output=output,
            template=template,
            map_path=long_map_path,
        )

        # 4. 128 samples, no map: first 17 go to notes 35..51.
        pool_dir = work / "pool128"
        # note 35 -> pad 128; sample_001 -> pad A1, ... sample_016 -> A16.
        write_wav(pool_dir / "00_note_35.wav", 0.18, midi_to_freq(35))
        for index in range(1, 128):
            frequency = 80.0 + (index - 1) * 7.0
            write_wav(pool_dir / f"sample_{index:03d}.wav", 0.18, frequency)
        pool_midi = work / "pool128.mid"
        pool_events = [
            (index * 960, 35 + index, 100, 480)
            for index in range(17)
        ]
        pool_midi.write_bytes(build_midi(note_events(pool_events), 17 * 960, bpm))
        run_project(
            samples=pool_dir,
            midi_path=pool_midi,
            project_name="XPJ Test 128",
            bpm=bpm,
            output=output,
            template=template,
        )

    if docs.is_file():
        shutil.copy2(docs, output / "README-HARDWARE-TEST.md")

    print("\nHardware test kit created:")
    for path in sorted(output.iterdir()):
        print(f"  {path}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Создать набор проектов для ручного теста MPC Sample."
    )
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--bpm", type=int, default=120)
    args = parser.parse_args()

    if not args.template.is_file():
        print(f"Эталон не найден: {args.template}", file=sys.stderr)
        return 2
    if not 20 <= args.bpm <= 300:
        print("BPM вне диапазона 20..300", file=sys.stderr)
        return 2

    make_kit(args.template, args.output, args.bpm)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
