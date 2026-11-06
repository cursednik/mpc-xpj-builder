from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gui import build_cli_args
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
        args = self._args(sample_map=str(self.map_path), dry_run=True, verbose=True)
        self.assertIn("--map", args)
        self.assertIn("--dry-run", args)
        self.assertIn("--verbose", args)
        self.assertEqual(args[args.index("--name") + 1], "Gui Kit")

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


if __name__ == "__main__":
    unittest.main()
