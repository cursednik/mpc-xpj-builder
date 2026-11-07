from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from audio_preview import AudioPreview
from gui import build_cli_args
from gui_map import pad_number_at, preview_source
from kit_map import PadAssignment, scan_wav_items
from tests.helpers import make_template, write_map, write_wav


class GuiArgsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.samples = self.root / "samples"
        self.samples.mkdir()
        write_wav(self.samples / "kick.wav")
        self.midi = self.root / "drums.mid"
        self.midi.write_bytes(b"MThd" + b"\x00" * 10)
        self.template = self.root / "template.xpj"
        make_template(self.template)
        self.map_path = self.root / "map.json"
        write_map(self.map_path, {"samples": [{"file": "kick.wav", "note": 36}]})
        self.output = self.root / "out"

    def tearDown(self) -> None:
        self._temp.cleanup()

    def _args(self, **overrides: str | bool) -> list[str]:
        values = {
            "samples": str(self.samples),
            "midi": str(self.midi),
            "name": "Gui Kit",
            "bpm": "174",
            "output": str(self.output),
            "template": str(self.template),
            "sample_map": "",
            "dry_run": False,
            "verbose": False,
        }
        values.update(overrides)
        return build_cli_args(**values)

    def test_basic_args(self) -> None:
        args = self._args(
            sample_map=str(self.map_path),
            dry_run=True,
            verbose=True,
            extended_notes=True,
        )
        self.assertIn("--map", args)
        self.assertIn("--dry-run", args)
        self.assertIn("--verbose", args)
        self.assertIn("--extended-notes", args)
        self.assertEqual(args[args.index("--name") + 1], "Gui Kit")

    def test_midi_optional(self) -> None:
        args = self._args(midi="")
        self.assertNotIn("--midi", args)

    def test_multiple_midi_args(self) -> None:
        midi2 = self.root / "drums2.mid"
        midi2.write_bytes(b"MThd")
        args = self._args(midi=f"{self.midi};{midi2}")
        self.assertEqual(args.count("--midi"), 2)
        self.assertIn(str(self.midi), args)
        self.assertIn(str(midi2), args)

    def test_empty_name_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "имя проекта"):
            self._args(name="   ")

    def test_bad_bpm_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "BPM"):
            self._args(bpm="999")

    def test_missing_map_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "карта"):
            self._args(sample_map=str(self.root / "missing.json"))

    def test_missing_output_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "папку экспорта"):
            self._args(output="")


class MapGridLayoutTests(unittest.TestCase):
    def test_a1_is_bottom_left(self) -> None:
        self.assertEqual(pad_number_at(3, 0), 1)
        self.assertEqual(pad_number_at(3, 3), 4)
        self.assertEqual(pad_number_at(2, 0), 5)
        self.assertEqual(pad_number_at(0, 0), 13)
        self.assertEqual(pad_number_at(0, 3), 16)

    def test_grid_covers_every_pad_once(self) -> None:
        numbers = [
            pad_number_at(row, column)
            for row in range(4)
            for column in range(4)
        ]
        self.assertEqual(sorted(numbers), list(range(1, 17)))


class PreviewSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.samples = Path(self._temp.name) / "samples"
        write_wav(self.samples / "kick.wav")
        write_wav(self.samples / "snare.wav")
        self.items = scan_wav_items(self.samples)
        self.assignments = {
            0: PadAssignment(pad_index=0, file="kick.wav"),
        }

    def test_selected_wav_wins(self) -> None:
        path, label = preview_source(
            self.items,
            self.assignments,
            "snare.wav",
            0,
            self.samples,
        )
        self.assertEqual(path, self.samples / "snare.wav")
        self.assertEqual(label, "snare.wav")

    def test_pad_assignment_is_fallback(self) -> None:
        path, label = preview_source(
            self.items,
            self.assignments,
            None,
            0,
            self.samples,
        )
        self.assertEqual(path, self.samples / "kick.wav")
        self.assertEqual(label, "kick.wav")

    def test_missing_assigned_file_returns_none(self) -> None:
        assignments = {0: PadAssignment(pad_index=0, file="missing.wav")}
        self.assertEqual(
            preview_source(self.items, assignments, None, 0, self.samples),
            (None, None),
        )

    def test_nothing_selected(self) -> None:
        self.assertEqual(
            preview_source(self.items, {}, None, None, self.samples),
            (None, None),
        )


class AudioPreviewTests(unittest.TestCase):
    def test_stop_without_play_is_safe(self) -> None:
        preview = AudioPreview()
        preview.stop()
        preview.stop()

    def test_available_is_bool(self) -> None:
        self.assertIsInstance(AudioPreview().available, bool)


if __name__ == "__main__":
    unittest.main()
