"""Тесты безопасного редактирования существующего .xpj."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from errors import ValidationError
from project_editor import (
    apply_metadata,
    data_dir_for,
    read_project,
    save_project_copy,
    save_project_in_place,
)
from tests.helpers import make_template
from xpj_writer import read_xpj, write_xpj


class ProjectEditorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name)
        self.source = self.root / "Kit.xpj"
        make_template(self.source)
        header, payload, _ = read_xpj(self.source)
        payload["customRoot"] = {"keep": [1, 2, 3]}
        payload["data"]["customData"] = "unchanged"
        payload["data"]["info"]["title"] = "Original Title"
        write_xpj(self.source, header, payload)

        self.source_data = data_dir_for(self.source)
        self.source_data.mkdir()
        (self.source_data / "kick.wav").write_bytes(b"RIFF")

    def test_summary(self) -> None:
        header, payload, summary = read_project(self.source)
        self.assertEqual(header.version, "1.3.0.12")
        self.assertEqual(summary.title, "Original Title")
        self.assertEqual(summary.bpm, 120.0)
        self.assertEqual(len(summary.sequences), 1)
        self.assertEqual(summary.sequences[0].name, "Sequence 01")
        self.assertEqual(summary.sequences[0].bars, 1)
        self.assertEqual(summary.tracks, 2)
        self.assertEqual(summary.pads, 0)
        self.assertEqual(summary.data_dir, self.source_data)
        self.assertEqual(summary.data_wavs, 1)
        self.assertEqual(payload["customRoot"]["keep"], [1, 2, 3])

    def test_apply_metadata_only_changes_title_and_bpm(self) -> None:
        _header, payload, _summary = read_project(self.source)
        updated = apply_metadata(payload, "New Title", 174)
        self.assertEqual(updated["data"]["info"]["title"], "New Title")
        self.assertEqual(updated["data"]["masterTempo"], 174.0)
        for sequence in updated["data"]["sequences"]:
            self.assertEqual(sequence["value"]["bpm"], 174.0)
        self.assertEqual(updated["customRoot"], payload["customRoot"])
        self.assertEqual(
            updated["data"]["customData"], payload["data"]["customData"]
        )
        # Исходный payload не мутируется.
        self.assertEqual(payload["data"]["info"]["title"], "Original Title")
        self.assertEqual(payload["data"]["masterTempo"], 120.0)

    def test_apply_metadata_rejects_bad_values(self) -> None:
        _header, payload, _summary = read_project(self.source)
        with self.assertRaises(ValidationError):
            apply_metadata(payload, "   ", 120)
        with self.assertRaises(ValidationError):
            apply_metadata(payload, "Title", 999)

    def test_apply_metadata_renames_sequence_only_when_it_matches_title(self) -> None:
        _header, payload, _summary = read_project(self.source)
        sequence = payload["data"]["sequences"][0]["value"]
        sequence["name"] = "Original Title"
        updated = apply_metadata(payload, "Renamed", 150)
        self.assertEqual(
            updated["data"]["sequences"][0]["value"]["name"], "Renamed"
        )

        sequence["name"] = "Custom Sequence"
        updated = apply_metadata(payload, "Renamed Again", 150)
        self.assertEqual(
            updated["data"]["sequences"][0]["value"]["name"], "Custom Sequence"
        )

    def test_save_copy_copies_resources_and_preserves_unknown_fields(self) -> None:
        header, payload, _summary = read_project(self.source)
        updated = apply_metadata(payload, "Copy Title", 150)
        target = self.root / "Copy.xpj"

        xpj_path, data_path = save_project_copy(
            self.source, target, header, updated
        )
        self.assertEqual(xpj_path, target)
        self.assertEqual(data_path, data_dir_for(target))
        self.assertTrue((data_path / "kick.wav").is_file())

        new_header, new_payload, _ = read_xpj(target)
        self.assertEqual(new_header.version, header.version)
        self.assertEqual(new_payload["data"]["info"]["title"], "Copy Title")
        self.assertEqual(new_payload["data"]["masterTempo"], 150.0)
        self.assertEqual(new_payload["customRoot"], {"keep": [1, 2, 3]})
        self.assertEqual(new_payload["data"]["customData"], "unchanged")

        _old_header, old_payload, _ = read_xpj(self.source)
        self.assertEqual(old_payload["data"]["info"]["title"], "Original Title")

    def test_save_copy_refuses_existing_target(self) -> None:
        header, payload, _summary = read_project(self.source)
        target = self.root / "Copy.xpj"
        target.write_bytes(b"exists")
        with self.assertRaises(ValidationError):
            save_project_copy(self.source, target, header, payload)

    def test_save_copy_refuses_existing_resource_dir(self) -> None:
        header, payload, _summary = read_project(self.source)
        target = self.root / "Copy.xpj"
        data_dir_for(target).mkdir()
        with self.assertRaises(ValidationError):
            save_project_copy(self.source, target, header, payload)

    def test_save_in_place_creates_backup_and_updates_file(self) -> None:
        header, payload, _summary = read_project(self.source)
        updated = apply_metadata(payload, "Updated Title", 160)

        xpj_path, backup = save_project_in_place(
            self.source, header, updated
        )
        self.assertEqual(xpj_path, self.source)
        self.assertTrue(backup.is_file())

        _old_header, old_payload, _ = read_xpj(backup)
        self.assertEqual(old_payload["data"]["info"]["title"], "Original Title")
        self.assertEqual(old_payload["data"]["masterTempo"], 120.0)

        _new_header, new_payload, _ = read_xpj(self.source)
        self.assertEqual(new_payload["data"]["info"]["title"], "Updated Title")
        self.assertEqual(new_payload["data"]["masterTempo"], 160.0)
        self.assertEqual(new_payload["customRoot"], {"keep": [1, 2, 3]})

    def test_save_in_place_requires_existing_file(self) -> None:
        header, payload, _summary = read_project(self.source)
        with self.assertRaises(ValidationError):
            save_project_in_place(self.root / "missing.xpj", header, payload)


if __name__ == "__main__":
    unittest.main()
