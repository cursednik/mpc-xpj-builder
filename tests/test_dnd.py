from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dnd import route_dropped
from gui_projects import route_project_drop


class DropRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.samples = self.root / "samples"
        self.samples.mkdir()
        self.wav = self.samples / "kick.wav"
        self.wav.write_bytes(b"RIFF")
        self.midi = self.root / "drums.mid"
        self.midi.write_bytes(b"MThd")
        self.template = self.root / "reference.xpj"
        self.template.write_bytes(b"gzip")
        self.map_path = self.root / "map.json"
        self.map_path.write_text("{}", encoding="utf-8")

    def tearDown(self) -> None:
        self._temp.cleanup()

    def test_route_folder_and_files(self) -> None:
        result = route_dropped(
            [
                str(self.samples),
                str(self.midi),
                str(self.template),
                str(self.map_path),
            ]
        )
        self.assertEqual(result.samples, self.samples)
        self.assertEqual(result.midi, self.midi)
        self.assertEqual(result.template, self.template)
        self.assertEqual(result.sample_map, self.map_path)
        self.assertTrue(result.has_any)

    def test_wav_uses_parent_folder(self) -> None:
        result = route_dropped([str(self.wav)])
        self.assertEqual(result.samples, self.samples)

    def test_unsupported(self) -> None:
        path = self.root / "archive.zip"
        path.write_bytes(b"PK")
        result = route_dropped([str(path)])
        self.assertIn(path, result.unsupported)
        self.assertFalse(result.has_any)

    def test_multiple_midi_are_kept_in_order(self) -> None:
        midi2 = self.root / "other.mid"
        midi2.write_bytes(b"MThd")
        result = route_dropped([str(self.midi), str(midi2)])
        self.assertEqual(result.midi, self.midi)
        self.assertEqual(result.midi_files, (self.midi, midi2))

    def test_project_browser_drop_folder(self) -> None:
        folder, project = route_project_drop([str(self.samples)])
        self.assertEqual(folder, self.samples)
        self.assertIsNone(project)

    def test_project_browser_drop_xpj(self) -> None:
        folder, project = route_project_drop([str(self.template)])
        self.assertEqual(folder, self.root)
        self.assertEqual(project, self.template)

    def test_project_browser_drop_prefers_folder(self) -> None:
        folder, project = route_project_drop(
            [str(self.template), str(self.samples)]
        )
        self.assertEqual(folder, self.samples)
        self.assertIsNone(project)

    def test_project_browser_drop_unsupported(self) -> None:
        self.assertEqual(route_project_drop([str(self.wav)]), (None, None))


if __name__ == "__main__":
    unittest.main()
