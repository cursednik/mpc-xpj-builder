from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from errors import ValidationError
from project_library import scan_projects
from tests.helpers import make_template
from xpj_writer import read_xpj, write_xpj


class ProjectLibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.projects = self.root / "projects"
        self.projects.mkdir()
        make_template(self.projects / "Good.xpj")
        (self.projects / "Broken.xpj").write_bytes(b"not gzip")
        (self.projects / "ignore.txt").write_text("x", encoding="utf-8")

    def tearDown(self) -> None:
        self._temp.cleanup()

    def test_scan_projects(self) -> None:
        items = scan_projects(self.projects)
        self.assertEqual(len(items), 2)
        by_name = {item.path.name: item for item in items}
        self.assertEqual(by_name["Good.xpj"].bpm, 120.0)
        self.assertEqual(by_name["Good.xpj"].bars, 1)
        self.assertEqual(by_name["Good.xpj"].tracks, 2)
        self.assertIsNotNone(by_name["Broken.xpj"].error)
        self.assertIn("202", by_name["Good.xpj"].modified_text)

    def test_missing_folder(self) -> None:
        with self.assertRaises(ValidationError):
            scan_projects(self.root / "missing")

    def test_title_preferred_over_sequence_name(self) -> None:
        path = self.projects / "Titled.xpj"
        make_template(path)
        header, payload, _ = read_xpj(path)
        payload["data"]["info"]["title"] = "Custom Title"
        write_xpj(path, header, payload)
        items = scan_projects(self.projects)
        item = next(item for item in items if item.path.name == "Titled.xpj")
        self.assertEqual(item.name, "Custom Title")


if __name__ == "__main__":
    unittest.main()
