from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from errors import ValidationError
from sample_map import load_sample_map, prepare_mapped_pool
from tests.helpers import write_map, write_wav


class SampleMapTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.samples = self.root / "samples"
        self.samples.mkdir()
        for name in ("kick.wav", "snare.wav", "extra.wav"):
            write_wav(self.samples / name)
        self.note_to_pad = {36: 0, 38: 2, 42: 6}

    def tearDown(self) -> None:
        self._temp.cleanup()

    def test_list_form_and_extra_files_are_ignored(self) -> None:
        map_path = self.root / "map.json"
        write_map(
            map_path,
            {
                "samples": [
                    {
                        "file": "kick.wav",
                        "note": 36,
                        "gain": 0.75,
                        "pan": 0.25,
                        "tune": 1.5,
                        "loop": True,
                    },
                    {"file": "snare.wav", "note": 38},
                ]
            },
        )

        pool, bindings = prepare_mapped_pool(
            map_path, self.samples, self.note_to_pad
        )

        self.assertEqual(pool.count, 2)
        self.assertEqual(len(bindings), 2)
        self.assertEqual(bindings[0].pad_index, 0)
        self.assertEqual(bindings[0].gain, 0.75)
        self.assertEqual(bindings[0].pan, 0.25)
        self.assertEqual(bindings[0].tune, 1.5)
        self.assertIs(bindings[0].loop, True)
        self.assertEqual(bindings[1].pad_index, 2)

    def test_compact_object_form(self) -> None:
        map_path = self.root / "map.json"
        write_map(
            map_path,
            {
                "kick": {"file": "kick.wav", "note": 36},
                "snare": {"file": "snare.wav", "note": 38},
            },
        )
        pool, bindings = prepare_mapped_pool(
            map_path, self.samples, self.note_to_pad
        )
        self.assertEqual(pool.count, 2)
        self.assertEqual([binding.midi_note for binding in bindings], [36, 38])

    def test_same_file_can_feed_two_notes(self) -> None:
        map_path = self.root / "map.json"
        write_map(
            map_path,
            {
                "samples": [
                    {"file": "kick.wav", "note": 36, "tune": 0},
                    {"file": "kick.wav", "note": 38, "tune": 12},
                ]
            },
        )
        pool, bindings = prepare_mapped_pool(
            map_path, self.samples, self.note_to_pad
        )
        self.assertEqual(pool.count, 1)
        self.assertEqual(len(bindings), 2)
        self.assertIs(bindings[0].sample, bindings[1].sample)

    def test_duplicate_note_rejected(self) -> None:
        map_path = self.root / "map.json"
        write_map(
            map_path,
            {
                "samples": [
                    {"file": "kick.wav", "note": 36},
                    {"file": "snare.wav", "note": 36},
                ]
            },
        )
        with self.assertRaisesRegex(ValidationError, "дважды"):
            load_sample_map(map_path)

    def test_unknown_field_rejected(self) -> None:
        map_path = self.root / "map.json"
        write_map(
            map_path,
            {"samples": [{"file": "kick.wav", "note": 36, "velocity": 100}]},
        )
        with self.assertRaisesRegex(ValidationError, "Неизвестные поля"):
            load_sample_map(map_path)

    def test_missing_file_rejected(self) -> None:
        map_path = self.root / "map.json"
        write_map(
            map_path,
            {"samples": [{"file": "missing.wav", "note": 36}]},
        )
        with self.assertRaisesRegex(ValidationError, "не найден"):
            prepare_mapped_pool(map_path, self.samples, self.note_to_pad)

    def test_invalid_note_rejected(self) -> None:
        map_path = self.root / "map.json"
        write_map(
            map_path,
            {"samples": [{"file": "kick.wav", "note": 60}]},
        )
        with self.assertRaisesRegex(ValidationError, "допустимо 35..51"):
            load_sample_map(map_path)

    def test_traversal_rejected(self) -> None:
        map_path = self.root / "map.json"
        write_map(
            map_path,
            {"samples": [{"file": "../kick.wav", "note": 36}]},
        )
        with self.assertRaisesRegex(ValidationError, "'..'"):
            prepare_mapped_pool(map_path, self.samples, self.note_to_pad)

    def test_bad_json_rejected(self) -> None:
        map_path = self.root / "map.json"
        map_path.write_text("{broken", encoding="utf-8")
        with self.assertRaisesRegex(ValidationError, "Не удалось прочитать"):
            load_sample_map(map_path)


if __name__ == "__main__":
    unittest.main()
