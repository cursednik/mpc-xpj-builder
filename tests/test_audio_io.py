"""Тесты USB Audio без реального аудиоустройства."""

from __future__ import annotations

import struct
import unittest

import audio_io
from audio_io import (
    AudioDevice,
    AudioSession,
    friendly_error,
    is_blocking_compatible,
    peak_percent,
    pick_mpc_input,
)


class AudioHelpersTests(unittest.TestCase):
    def test_peak_percent_silence(self) -> None:
        self.assertEqual(peak_percent(b"\x00\x00\x00\x00"), 0.0)

    def test_peak_percent_half_scale(self) -> None:
        data = struct.pack("<hh", 0, 16384)
        self.assertAlmostEqual(peak_percent(data), 50.0, places=1)

    def test_peak_percent_full_scale(self) -> None:
        data = struct.pack("<hh", -32768, 32767)
        self.assertAlmostEqual(peak_percent(data), 100.0, places=1)

    def test_pick_mpc_input_prefers_wasapi(self) -> None:
        devices = (
            AudioDevice(0, "Microphone (MPC Sample Audio)", "Windows DirectSound", 2, 0, 44100),
            AudioDevice(1, "Microphone (MPC Sample Audio)", "Windows WASAPI", 2, 0, 44100),
            AudioDevice(2, "Speakers", "Windows WASAPI", 0, 2, 44100),
        )
        picked = pick_mpc_input(devices)
        self.assertIsNotNone(picked)
        self.assertEqual(picked.index, 1)

    def test_pick_mpc_input_falls_back_to_first_input(self) -> None:
        devices = (
            AudioDevice(0, "Some Input", "MME", 1, 0, 44100),
            AudioDevice(1, "Speakers", "MME", 0, 2, 44100),
        )
        picked = pick_mpc_input(devices)
        self.assertIsNotNone(picked)
        self.assertEqual(picked.index, 0)

    def test_pick_mpc_input_none(self) -> None:
        self.assertIsNone(
            pick_mpc_input(
                (AudioDevice(0, "Speakers", "MME", 0, 2, 44100),)
            )
        )

    def test_session_stop_without_start_is_safe(self) -> None:
        session = AudioSession()
        session.stop()
        self.assertFalse(session.running)
        self.assertEqual(session.seconds, 0.0)

    def test_wdm_ks_is_not_blocking_compatible(self) -> None:
        self.assertFalse(is_blocking_compatible("Windows WDM-KS"))
        self.assertTrue(is_blocking_compatible("Windows WASAPI"))
        self.assertTrue(is_blocking_compatible("MME"))

    def test_friendly_error_for_blocking_api(self) -> None:
        message = friendly_error(
            RuntimeError("Blocking API not supported yet")
        )
        self.assertIn("WASAPI", message)

    def test_friendly_error_for_sample_rate(self) -> None:
        message = friendly_error(RuntimeError("Invalid sample rate"))
        self.assertIn("частоту", message)

    def test_dependency_available_is_bool(self) -> None:
        self.assertIsInstance(audio_io.dependency_available(), bool)

    def test_list_devices_without_dependency_raises(self) -> None:
        if audio_io.dependency_available():
            self.skipTest("sounddevice installed")
        with self.assertRaises(RuntimeError):
            audio_io.list_devices()


if __name__ == "__main__":
    unittest.main()
