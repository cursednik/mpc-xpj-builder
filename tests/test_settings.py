from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from settings import GuiSettings, load_settings, remember_recent, save_settings


class SettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.path = self.root / "nested" / "settings.json"

    def tearDown(self) -> None:
        self._temp.cleanup()

    def test_missing_file_returns_defaults(self) -> None:
        settings = load_settings(self.path)
        self.assertEqual(settings.name, "My Kit")
        self.assertEqual(settings.bpm, "120")
        self.assertTrue(settings.verbose)

    def test_roundtrip(self) -> None:
        original = GuiSettings(
            samples=r"C:\Samples",
            midi=r"C:\drums.mid",
            name="Kit",
            bpm="174",
            output=r"D:\Projects",
            template=r"D:\ref.xpj",
            sample_map=r"D:\map.json",
            extended_notes=True,
            verbose=False,
        )
        save_settings(original, self.path)
        loaded = load_settings(self.path)
        self.assertEqual(loaded, original)

    def test_recent_projects_roundtrip_and_dedupe(self) -> None:
        projects = remember_recent((), r"D:\Projects\Kit.xpj")
        projects = remember_recent(projects, r"D:\Projects\Other.xpj")
        projects = remember_recent(projects, r"D:\Projects\Kit.xpj")
        self.assertEqual(
            projects,
            (r"D:\Projects\Kit.xpj", r"D:\Projects\Other.xpj"),
        )
        original = GuiSettings(recent_projects=projects)
        save_settings(original, self.path)
        self.assertEqual(load_settings(self.path).recent_projects, projects)

    def test_malformed_json_falls_back(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{broken", encoding="utf-8")
        self.assertEqual(load_settings(self.path), GuiSettings())

    def test_wrong_types_fall_back(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_text(
            '{"name": 5, "bpm": null, "verbose": "yes"}',
            encoding="utf-8",
        )
        loaded = load_settings(self.path)
        self.assertEqual(loaded.name, "My Kit")
        self.assertEqual(loaded.bpm, "120")
        self.assertTrue(loaded.verbose)


if __name__ == "__main__":
    unittest.main()
