from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import main as cli
from tests.helpers import make_template, write_map, write_midi, write_wav
from xpj_writer import read_xpj


class IntegrationExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.samples = self.root / "samples"
        self.samples.mkdir()
        for name in (
            "kick.wav",
            "snare.wav",
            "ride_destroy.wav",
            "ride_trigger.wav",
            "unused.wav",
        ):
            write_wav(self.samples / name, frames=1200)
        self.midi = self.root / "drums.mid"
        write_midi(
            self.midi,
            [
                (0, 36, 120, 120),
                (480, 38, 100, 120),
                (960, 42, 90, 90),
                (1440, 46, 110, 90),
            ],
        )
        self.template = self.root / "template.xpj"
        make_template(self.template)
        self.map_path = self.root / "map.json"
        write_map(
            self.map_path,
            {
                "samples": [
                    {"file": "kick.wav", "note": 36, "gain": 1.0, "pan": 0.5},
                    {"file": "snare.wav", "note": 38, "gain": 0.9, "pan": 0.4},
                    {
                        "file": "ride_destroy.wav",
                        "note": 42,
                        "gain": 0.8,
                        "pan": 0.6,
                        "loop": True,
                    },
                    {
                        "file": "ride_trigger.wav",
                        "note": 46,
                        "tune": 2.5,
                        "loop": False,
                    },
                ]
            },
        )
        self.output = self.root / "out"

    def tearDown(self) -> None:
        self._temp.cleanup()

    def _export(self) -> int:
        with contextlib.redirect_stdout(io.StringIO()):
            return cli.main(
                [
                    "--samples",
                    str(self.samples),
                    "--midi",
                    str(self.midi),
                    "--name",
                    "Mapped Test",
                    "--bpm",
                    "150",
                    "--output",
                    str(self.output),
                    "--template",
                    str(self.template),
                    "--map",
                    str(self.map_path),
                ]
            )

    def test_mapped_export(self) -> None:
        self.assertEqual(self._export(), 0)
        xpj_path = self.output / "Mapped Test.xpj"
        data_dir = self.output / "Mapped Test_[ProjectData]"
        self.assertTrue(xpj_path.is_file())
        self.assertTrue(data_dir.is_dir())
        self.assertEqual(
            sorted(path.name for path in data_dir.glob("*.wav")),
            [
                "kick.wav",
                "ride_destroy.wav",
                "ride_trigger.wav",
                "snare.wav",
            ],
        )
        self.assertFalse((data_dir / "unused.wav").exists())

        _, payload, _ = read_xpj(xpj_path)
        data = payload["data"]
        self.assertEqual(data["masterTempo"], 150.0)
        self.assertEqual(len(data["tracks"]), 2)
        self.assertEqual(len(data["samples"]), 4)

        sequence = data["sequences"][0]["value"]
        self.assertEqual(sequence["bpm"], 150.0)
        self.assertEqual(sequence["lengthBars"], 1)
        self.assertEqual(len(sequence["trackClipMaps"]), 1)
        self.assertEqual(len(sequence["trackClipMaps"][0]), 2)
        drum_clip = sequence["trackClipMaps"][0][0]["value"]
        self.assertEqual(len(drum_clip["eventList"]["events"]), 4)
        self.assertTrue(all(event["type"] == 3 for event in drum_clip["eventList"]["events"]))

        track = data["tracks"][0]
        instruments = track["program"]["drum"]["instruments"]
        kick = instruments[0]["layersv"][0]
        snare = instruments[2]["layersv"][0]
        ride_destroy = instruments[6]["layersv"][0]
        ride_trigger = instruments[10]["layersv"][0]

        self.assertEqual(kick["sampleEnd"], 0)
        self.assertEqual(kick["sliceIndex"], 129)
        self.assertEqual(kick["sliceInfo"]["End"], 1199)
        self.assertEqual(kick["volume"]["gainCoefficient"], 1.0)
        self.assertEqual(kick["pan"], 0.5)
        self.assertEqual(snare["volume"]["gainCoefficient"], 0.9)
        self.assertEqual(snare["pan"], 0.4)
        self.assertEqual(ride_destroy["volume"]["gainCoefficient"], 0.8)
        self.assertTrue(ride_destroy["loop"])
        self.assertEqual(ride_destroy["sliceInfo"]["LoopMode"], 1)
        self.assertEqual(ride_trigger["coarseTune"], 2)
        self.assertEqual(ride_trigger["fineTune"], 50)
        self.assertEqual(ride_trigger["pitch"], 2.5)
        self.assertFalse(ride_trigger["loop"])

        clip_player = data["clipPlayerData"]
        self.assertNotIn("Drum 001", str(clip_player))
        self.assertIn("Mapped Test", str(clip_player))

    def test_positional_export_without_map_still_works(self) -> None:
        output = self.root / "out_no_map"
        with contextlib.redirect_stdout(io.StringIO()):
            rc = cli.main(
                [
                    "--samples",
                    str(self.samples),
                    "--midi",
                    str(self.midi),
                    "--name",
                    "Positional Test",
                    "--bpm",
                    "150",
                    "--output",
                    str(output),
                    "--template",
                    str(self.template),
                ]
            )
        self.assertEqual(rc, 0)
        self.assertTrue((output / "Positional Test.xpj").is_file())
        self.assertTrue((output / "Positional Test_[ProjectData]").is_dir())

    def test_dry_run_mapping_creates_nothing(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            rc = cli.main(
                [
                    "--samples",
                    str(self.samples),
                    "--midi",
                    str(self.midi),
                    "--name",
                    "Dry Mapped",
                    "--bpm",
                    "150",
                    "--output",
                    str(self.output),
                    "--template",
                    str(self.template),
                    "--map",
                    str(self.map_path),
                    "--dry-run",
                ]
            )
        self.assertEqual(rc, 0)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
