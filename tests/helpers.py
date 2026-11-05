"""Тестовые фикстуры без внешних зависимостей."""

from __future__ import annotations

import copy
import json
import math
import struct
import wave
from pathlib import Path

from xpj_schema import INT64_MAX
from xpj_writer import XPJHeader, write_xpj


def write_wav(path: Path, frames: int = 1000, frequency: float = 220.0) -> None:
    rate = 44100
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        data = bytearray()
        for index in range(frames):
            envelope = math.exp(-5.0 * index / max(1, frames))
            value = int(18000 * envelope * math.sin(2 * math.pi * frequency * index / rate))
            data += struct.pack("<h", value)
        handle.writeframes(bytes(data))


def varlen(value: int) -> bytes:
    if value < 0:
        raise ValueError(value)
    out = [value & 0x7F]
    value >>= 7
    while value:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    return bytes(reversed(out))


def write_midi(path: Path, note_events: list[tuple[int, int, int, int]]) -> None:
    """note_events: (tick, pitch, velocity, duration_ticks)."""
    raw_events: list[tuple[int, int, bytes]] = []
    order = 0
    for tick, pitch, velocity, duration in note_events:
        raw_events.append((tick, order, bytes([0x99, pitch, velocity])))
        order += 1
        raw_events.append(
            (tick + max(1, duration), order, bytes([0x89, pitch, 40]))
        )
        order += 1
    raw_events.append(
        (
            max(tick + duration for tick, _pitch, _velocity, duration in note_events),
            order,
            b"\xff\x2f\x00",
        )
    )
    raw_events.sort(key=lambda item: (item[0], item[1]))

    body = bytearray()
    last = 0
    for tick, _order, payload in raw_events:
        body += varlen(tick - last)
        body += payload
        last = tick
    track = b"MTrk" + struct.pack(">I", len(body)) + body
    header = b"MThd" + struct.pack(">IHHH", 6, 0, 1, 480)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + track)


def _layer() -> dict:
    return {
        "active": True,
        "volume": {"gainCoefficient": 1.0, "controlValue": 1.0, "law": 1},
        "pan": 0.5,
        "pitch": 0.0,
        "coarseTune": 0,
        "fineTune": 0,
        "velocityStart": 0,
        "velocityEnd": 127,
        "sampleStart": 0,
        "sampleEnd": 0,
        "loop": False,
        "loopStart": 0,
        "loopEnd": 0,
        "sampleName": "",
        "sampleFile": "",
        "sliceIndex": 129,
        "sliceInfo": {
            "Start": 0,
            "End": 0,
            "LoopStart": 0,
            "LoopMode": 0,
            "PulsePosition": 0,
            "LoopCrossfadeLength": 0,
            "LoopCrossfadeType": 0,
            "TailLength": 0.0,
            "TailLoopPosition": 0.5,
        },
    }


def _instrument() -> dict:
    return {
        "version": 28,
        "coarseTune": 0,
        "fineTune": 0,
        "layersv": [copy.deepcopy(_layer()) for _ in range(8)],
    }


def make_template(path: Path) -> None:
    """Минимальный структурный шаблон для тестов схемы."""
    instruments = [_instrument() for _ in range(128)]

    note_for_pad = {}
    for pad in range(16):
        note_for_pad[f"value{pad}"] = 36 + pad
    for pad in range(16, 127):
        note_for_pad[f"value{pad}"] = 52 + (pad - 16)
    note_for_pad["value127"] = 35

    program = {
        "version": 4,
        "name": "Drum 001",
        "type": 0,
        "padNoteMap": {"noteForPad": note_for_pad},
        "drum": {
            "version": 2,
            "drumVersion": 12,
            "instruments": instruments,
        },
        "mixable": {"inserts": {"effects": []}},
    }
    drum_track = {
        "version": 5,
        "name": "Drum 001",
        "samples": [],
        "program": program,
        "arrangementClipMap": [],
        "sharedClipMap": [],
    }
    submix = {
        "version": 5,
        "name": "Submix 1",
        "program": {
            "version": 4,
            "name": "Submix 1",
            "type": 8,
            "mixable": {"inserts": {"effects": []}},
        },
        "arrangementClipMap": [],
        "sharedClipMap": [],
    }
    sequence = {
        "version": 5,
        "name": "Sequence 01",
        "bpm": 120.0,
        "lengthBars": 1,
        "loopStartBar": 0,
        "loopEndBar": 1,
        "loop": True,
        "tempoEnable": True,
        "transposition": 0,
        "lengthPulses": 3840,
        "loopStartPulses": 0,
        "loopEndPulses": 3840,
        "autoSelectTrackIndex": -1,
        "trackClipMaps": [[]],
        "seqEventList": {
            "length": INT64_MAX,
            "events": [],
            "version": 2,
            "quantisation": {
                "version": 1,
                "pulses": 240,
                "swing": 0.0,
                "strength": 1.0,
            },
            "numFilterTypes": 30,
        },
        "smpteStart": {
            "hours": 0,
            "mins": 0,
            "secs": 0,
            "frames": 0,
            "subframes": 0,
        },
        "timeSignatureTrack": {
            "timeSignatures": [
                {"beatsPerBar": 4, "beatLength": 960, "barStart": 0}
            ]
        },
    }
    payload = {
        "data": {
            "version": 28,
            "key": "C Major",
            "masterTempo": 120.0,
            "masterTempoEnabled": False,
            "tracks": [drum_track, submix],
            "sequences": [{"key": 0, "value": sequence}],
            "samples": [],
            "songs": [],
            "sharedClipMatrixData": [],
            "mixer": {},
            "info": {"title": ""},
            "clipPlayerData": {
                "version": 1,
                "trackClipTransportMap": [
                    {"key": "Drum 001", "value": [{"key": 0, "value": 0}]},
                    {"key": "Submix 1", "value": [{"key": 0, "value": 0}]},
                ],
            },
        }
    }
    write_xpj(path, XPJHeader(version="1.3.0.12", platform="Linux"), payload)


def write_map(path: Path, entries: dict) -> None:
    path.write_text(json.dumps(entries, indent=2), encoding="utf-8")
