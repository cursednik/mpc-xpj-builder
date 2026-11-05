from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from midi_reader import read_midi, to_pulses
from tests.helpers import varlen


class MidiReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)

    def tearDown(self) -> None:
        self._temp.cleanup()

    def _write(self, body: bytes) -> Path:
        path = self.root / "test.mid"
        track = b"MTrk" + struct.pack(">I", len(body)) + body
        header = b"MThd" + struct.pack(">IHHH", 6, 0, 1, 480)
        path.write_bytes(header + track)
        return path

    def test_running_status_and_velocity_zero(self) -> None:
        body = bytearray()
        body += varlen(0) + b"\x99\x24\x64"       # note on 36
        body += varlen(0) + b"\x26\x64"           # running: note on 38
        body += varlen(100) + b"\x89\x24\x40"      # note off 36
        body += varlen(0) + b"\x26\x40"            # running: note off 38
        body += varlen(100) + b"\x99\x2a\x50"      # note on 42
        body += varlen(10) + b"\x99\x2a\x00"       # velocity 0 = note off
        body += varlen(0) + b"\xff\x2f\x00"
        data = read_midi(self._write(bytes(body)))

        self.assertEqual(data.ppq, 480)
        self.assertEqual(
            [(note.pitch, note.velocity, note.start_tick, note.end_tick) for note in data.notes],
            [(36, 100, 0, 100), (38, 100, 0, 100), (42, 80, 200, 210)],
        )
        self.assertEqual(to_pulses(480, 480), 960)

    def test_meta_tempo_and_time_signature(self) -> None:
        body = bytearray()
        body += varlen(0) + b"\xff\x51\x03" + (500000).to_bytes(3, "big")
        body += varlen(0) + b"\xff\x58\x04\x03\x02\x18\x08"
        body += varlen(0) + b"\x99\x24\x64"
        body += varlen(480) + b"\x89\x24\x40"
        body += varlen(0) + b"\xff\x2f\x00"
        data = read_midi(self._write(bytes(body)))

        self.assertAlmostEqual(data.tempo_bpm or 0.0, 120.0, places=6)
        self.assertEqual(data.time_signature, (3, 4))

    def test_bad_header_rejected(self) -> None:
        path = self.root / "bad.mid"
        path.write_bytes(b"not a midi file")
        with self.assertRaises(Exception):
            read_midi(path)


if __name__ == "__main__":
    unittest.main()
