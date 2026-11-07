"""Тесты именованных пресетов карт."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from errors import ValidationError
from kit_map import PadAssignment
from map_presets import (
    MapPreset,
    delete_preset,
    list_presets,
    load_preset,
    save_preset,
)


class MapPresetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name) / "presets"
        self.addCleanup(self.temp.cleanup)

    def _assignments(self) -> dict[int, PadAssignment]:
        return {
            0: PadAssignment(
                pad_index=0,
                file="kick.wav",
                gain=0.9,
                pan=0.4,
                tune=-2.0,
                loop=False,
            ),
            17: PadAssignment(
                pad_index=17,
                file="snare.wav",
                gain=1.0,
                pan=0.5,
                tune=0.0,
                loop=True,
            ),
        }

    def test_save_list_and_load_roundtrip(self) -> None:
        save_preset("PSX Kit", self._assignments(), self.base)
        save_preset("alpha", {0: PadAssignment(pad_index=0, file="a.wav")}, self.base)

        names = [preset.name for preset in list_presets(self.base)]
        self.assertEqual(names, ["alpha", "PSX Kit"])

        preset = next(item for item in list_presets(self.base) if item.name == "PSX Kit")
        loaded = load_preset(preset)
        self.assertEqual(loaded[0].file, "kick.wav")
        self.assertAlmostEqual(loaded[0].gain, 0.9)
        self.assertAlmostEqual(loaded[0].tune, -2.0)
        self.assertEqual(loaded[17].file, "snare.wav")
        self.assertTrue(loaded[17].loop)

    def test_overwrite_replaces_file(self) -> None:
        save_preset("Kit", {0: PadAssignment(pad_index=0, file="a.wav")}, self.base)
        save_preset("Kit", {1: PadAssignment(pad_index=1, file="b.wav")}, self.base)

        presets = list_presets(self.base)
        self.assertEqual(len(presets), 1)
        loaded = load_preset(presets[0])
        self.assertEqual(loaded[1].file, "b.wav")

    def test_invalid_names_rejected(self) -> None:
        for name in ("", "   ", ".", "..", "a/b", "a:b", "a*b", "name."):
            with self.subTest(name=name):
                with self.assertRaises(ValidationError):
                    save_preset(name, self._assignments(), self.base)

    def test_delete_preset(self) -> None:
        save_preset("Kit", self._assignments(), self.base)
        preset = list_presets(self.base)[0]
        self.assertTrue(delete_preset(preset))
        self.assertFalse(delete_preset(preset))
        self.assertEqual(list_presets(self.base), ())

    def test_list_ignores_unrelated_files(self) -> None:
        self.base.mkdir(parents=True)
        (self.base / "notes.txt").write_text("x", encoding="utf-8")
        (self.base / "broken.json").write_text("{}", encoding="utf-8")
        self.assertEqual(
            [preset.name for preset in list_presets(self.base)],
            ["broken"],
        )

    def test_missing_preset_load_fails(self) -> None:
        missing = MapPreset("Missing", self.base / "Missing.json")
        with self.assertRaises(ValidationError):
            load_preset(missing)


if __name__ == "__main__":
    unittest.main()
