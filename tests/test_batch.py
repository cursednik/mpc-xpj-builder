from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import main as cli
from batch import load_batch_manifest, save_batch_manifest
from errors import ValidationError
from tests.helpers import make_template, write_map, write_midi, write_wav


class BatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.template = self.root / "template.xpj"
        make_template(self.template)
        self.output = self.root / "out"

        self.samples_a = self.root / "samples_a"
        self.samples_a.mkdir()
        write_wav(self.samples_a / "kick.wav")
        write_wav(self.samples_a / "snare.wav")
        self.midi_a = self.root / "a.mid"
        write_midi(self.midi_a, [(0, 36, 100, 100), (240, 38, 90, 100)])
        self.map_a = self.root / "a-map.json"
        write_map(
            self.map_a,
            {
                "samples": [
                    {"file": "kick.wav", "note": 36},
                    {"file": "snare.wav", "note": 38},
                ]
            },
        )

        self.samples_b = self.root / "samples_b"
        self.samples_b.mkdir()
        write_wav(self.samples_b / "kick.wav")
        write_wav(self.samples_b / "snare.wav")
        self.midi_b = self.root / "b.mid"
        write_midi(self.midi_b, [(0, 36, 110, 100), (240, 38, 80, 100)])

    def tearDown(self) -> None:
        self._temp.cleanup()

    def _write_manifest(self, payload: dict, name: str = "batch.json") -> Path:
        path = self.root / name
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    def _manifest(self) -> dict:
        return {
            "template": "template.xpj",
            "output": "out",
            "bpm": 150,
            "jobs": [
                {
                    "name": "Batch A",
                    "samples": "samples_a",
                    "midi": "a.mid",
                    "map": "a-map.json",
                },
                {
                    "name": "Batch B",
                    "samples": "samples_b",
                    "midi": "b.mid",
                    "bpm": 160,
                },
            ],
        }

    def test_relative_paths_and_global_defaults(self) -> None:
        manifest = self._write_manifest(self._manifest())
        spec = load_batch_manifest(manifest)
        self.assertEqual(spec.source, manifest.resolve())
        self.assertEqual(len(spec.jobs), 2)
        self.assertEqual(spec.jobs[0].samples, (self.root / "samples_a").resolve())
        self.assertEqual(spec.jobs[0].bpm, 150.0)
        self.assertEqual(spec.jobs[1].bpm, 160.0)
        self.assertEqual(spec.jobs[0].template, self.template.resolve())
        self.assertEqual(spec.jobs[0].output, self.output.resolve())

    def test_duplicate_target_rejected(self) -> None:
        payload = self._manifest()
        payload["jobs"][1]["name"] = "Batch A"
        payload["jobs"][1]["output"] = "out"
        manifest = self._write_manifest(payload)
        with self.assertRaisesRegex(ValidationError, "повторяется"):
            load_batch_manifest(manifest)

    def test_missing_bpm_rejected(self) -> None:
        payload = self._manifest()
        del payload["bpm"]
        manifest = self._write_manifest(payload)
        with self.assertRaisesRegex(ValidationError, "не задан bpm"):
            load_batch_manifest(manifest)

    def test_unknown_job_field_rejected(self) -> None:
        payload = self._manifest()
        payload["jobs"][0]["velocity"] = 100
        manifest = self._write_manifest(payload)
        with self.assertRaisesRegex(ValidationError, "Неизвестные поля"):
            load_batch_manifest(manifest)

    def test_batch_export(self) -> None:
        manifest = self._write_manifest(self._manifest())
        with contextlib.redirect_stdout(io.StringIO()):
            rc = cli.main(["--batch", str(manifest)])
        self.assertEqual(rc, 0)
        for name in ("Batch A", "Batch B"):
            self.assertTrue((self.output / f"{name}.xpj").is_file())
            self.assertTrue((self.output / f"{name}_[ProjectData]").is_dir())

    def test_batch_dry_run_creates_nothing(self) -> None:
        manifest = self._write_manifest(self._manifest())
        with contextlib.redirect_stdout(io.StringIO()):
            rc = cli.main(["--batch", str(manifest), "--dry-run"])
        self.assertEqual(rc, 0)
        self.assertFalse(self.output.exists())

    def test_preflight_failure_creates_no_partial_projects(self) -> None:
        payload = self._manifest()
        payload["jobs"][1]["midi"] = "missing.mid"
        manifest = self._write_manifest(payload)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
            io.StringIO()
        ):
            rc = cli.main(["--batch", str(manifest)])
        self.assertEqual(rc, 3)
        self.assertFalse(self.output.exists())

    def test_batch_rejects_single_project_flags(self) -> None:
        manifest = self._write_manifest(self._manifest())
        with contextlib.redirect_stderr(io.StringIO()):
            rc = cli.main(
                ["--batch", str(manifest), "--samples", str(self.samples_a)]
            )
        self.assertEqual(rc, 2)

    def test_batch_rejects_inspect(self) -> None:
        manifest = self._write_manifest(self._manifest())
        with contextlib.redirect_stderr(io.StringIO()):
            rc = cli.main(["--batch", str(manifest), "--inspect", str(self.template)])
        self.assertEqual(rc, 2)

    def test_midi_list_manifest(self) -> None:
        second = self.root / "second.mid"
        write_midi(second, [(0, 36, 100, 100)])
        payload = self._manifest()
        payload["jobs"] = [
            {
                "name": "Batch Multi",
                "samples": "samples_a",
                "midi": ["a.mid", "second.mid"],
            }
        ]
        manifest = self._write_manifest(payload)
        spec = load_batch_manifest(manifest)
        self.assertEqual(len(spec.jobs), 1)
        self.assertEqual(
            spec.jobs[0].midi_files,
            (
                (self.root / "a.mid").resolve(),
                (self.root / "second.mid").resolve(),
            ),
        )

    def test_save_manifest_roundtrip(self) -> None:
        target = self.root / "nested" / "saved-batch.json"
        save_batch_manifest(target, self._manifest())
        spec = load_batch_manifest(target)
        self.assertEqual(len(spec.jobs), 2)
        self.assertEqual(spec.jobs[0].name, "Batch A")
        self.assertEqual(spec.jobs[1].bpm, 160.0)

    def test_save_manifest_keeps_existing_file_on_invalid_payload(self) -> None:
        target = self.root / "saved-batch.json"
        target.write_text('{"old": true}', encoding="utf-8")
        payload = self._manifest()
        del payload["bpm"]
        with self.assertRaises(ValidationError):
            save_batch_manifest(target, payload)
        self.assertEqual(target.read_text(encoding="utf-8"), '{"old": true}')

    def test_save_manifest_requires_json_suffix(self) -> None:
        with self.assertRaises(ValidationError):
            save_batch_manifest(self.root / "batch.txt", self._manifest())


if __name__ == "__main__":
    unittest.main()
