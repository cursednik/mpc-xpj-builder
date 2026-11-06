from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import kit_map
from tests.helpers import make_template, write_wav


class KitMapTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.samples = self.root / "samples"
        self.samples.mkdir()
        for name, frequency in (
            ("36_kick.wav", 60.0),
            ("snare.wav", 180.0),
            ("open_hat.wav", 8000.0),
            ("random.wav", 440.0),
        ):
            write_wav(self.samples / name, frequency=frequency)

    def tearDown(self) -> None:
        self._temp.cleanup()

    def test_scan_wav_items(self) -> None:
        items = kit_map.scan_wav_items(self.samples)
        self.assertEqual(len(items), 4)
        self.assertEqual(items[0].relative, "36_kick.wav")
        self.assertGreater(items[0].duration, 0)
        self.assertIn("Hz", items[0].info)

    def test_pad_helpers(self) -> None:
        self.assertEqual(kit_map.global_pad_index("A", 1), 0)
        self.assertEqual(kit_map.global_pad_index("H", 16), 127)
        self.assertEqual(kit_map.bank_pad_label(0), "A1")
        self.assertEqual(kit_map.bank_pad_label(127), "H16")
        with self.assertRaises(ValueError):
            kit_map.global_pad_index("Z", 1)

    def test_default_pad_to_note(self) -> None:
        mapping = kit_map.default_pad_to_note()
        self.assertEqual(mapping[0], 36)
        self.assertEqual(mapping[15], 51)
        self.assertEqual(mapping[16], 52)
        self.assertEqual(mapping[127], 35)
        self.assertEqual(len(mapping), 128)

    def test_template_pad_map_covers_all_pads(self) -> None:
        template = self.root / "template.xpj"
        make_template(template)
        mapping, error = kit_map.pad_to_note_from_template(template)
        self.assertIsNone(error)
        self.assertEqual(len(mapping), 128)
        self.assertEqual(mapping[0], 36)
        self.assertEqual(mapping[16], 52)
        self.assertEqual(mapping[127], 35)

    def test_auto_assign_numeric_and_keywords(self) -> None:
        items = kit_map.scan_wav_items(self.samples)
        result = kit_map.auto_assign(items, {}, kit_map.default_note_to_pad())
        self.assertEqual(len(result), 3)
        files = {assignment.file: pad for pad, assignment in result.items()}
        self.assertEqual(files["36_kick.wav"], 0)
        self.assertEqual(files["snare.wav"], 2)
        self.assertEqual(files["open_hat.wav"], 10)
        self.assertNotIn("random.wav", files)

    def test_auto_assign_does_not_override(self) -> None:
        existing = {
            0: kit_map.PadAssignment(pad_index=0, file="36_kick.wav", gain=0.5)
        }
        items = kit_map.scan_wav_items(self.samples)
        result = kit_map.auto_assign(items, existing, kit_map.default_note_to_pad())
        self.assertEqual(result[0].gain, 0.5)
        self.assertIn(2, result)

    def test_fill_free_pads(self) -> None:
        items = kit_map.scan_wav_items(self.samples)
        result = kit_map.auto_assign(
            items,
            {},
            kit_map.default_note_to_pad(),
            fill_free=True,
        )
        self.assertEqual(len(result), 4)
        self.assertEqual(len({assignment.file for assignment in result.values()}), 4)

    def test_save_load_roundtrip(self) -> None:
        assignments = {
            0: kit_map.PadAssignment(
                pad_index=0,
                file="36_kick.wav",
                gain=0.8,
                pan=0.3,
                tune=1.5,
                loop=True,
            ),
            16: kit_map.PadAssignment(pad_index=16, file="snare.wav"),
        }
        path = self.root / "map.json"
        kit_map.save_kit_map(path, assignments)
        loaded = kit_map.load_kit_map(path)
        self.assertEqual(loaded[0].gain, 0.8)
        self.assertEqual(loaded[0].pan, 0.3)
        self.assertEqual(loaded[0].tune, 1.5)
        self.assertTrue(loaded[0].loop)
        self.assertEqual(loaded[16].file, "snare.wav")


if __name__ == "__main__":
    unittest.main()
