"""Тесты MIDI Clock без реального MIDI-оборудования."""

from __future__ import annotations

import time
import unittest

from errors import ValidationError
from midi_clock import (
    CLOCK,
    START,
    STOP,
    ClockEngine,
    ClockMonitor,
    MidiInput,
    MidiOutput,
)


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


class FakeOutput:
    def __init__(self, fail_on_clock: bool = False) -> None:
        self.messages: list[int] = []
        self.fail_on_clock = fail_on_clock
        self.closed = False

    def send(self, status: int) -> None:
        if self.fail_on_clock and status == CLOCK:
            raise RuntimeError("fake MIDI failure")
        self.messages.append(status)

    def close(self) -> None:
        self.closed = True


class MidiClockTests(unittest.TestCase):
    def test_interval_for_bpm(self) -> None:
        self.assertAlmostEqual(
            ClockEngine.interval_for_bpm(120),
            60.0 / (120 * 24),
        )
        self.assertAlmostEqual(
            ClockEngine.interval_for_bpm(174),
            60.0 / (174 * 24),
        )

    def test_start_sends_start_and_clock_then_stop(self) -> None:
        output = FakeOutput()
        engine = ClockEngine(output, 120)
        engine.start()
        time.sleep(0.15)
        engine.stop()

        self.assertFalse(engine.running)
        self.assertEqual(output.messages[0], START)
        self.assertEqual(output.messages[-1], STOP)
        self.assertIn(CLOCK, output.messages)
        self.assertGreaterEqual(engine.pulses, 1)

    def test_invalid_bpm_rejected(self) -> None:
        output = FakeOutput()
        with self.assertRaises(ValidationError):
            ClockEngine(output, 0)
        with self.assertRaises(ValidationError):
            ClockEngine(output, 9999)

    def test_bpm_can_change_live(self) -> None:
        output = FakeOutput()
        engine = ClockEngine(output, 120)
        engine.set_bpm(174)
        self.assertEqual(engine.bpm, 174.0)
        engine.start()
        time.sleep(0.05)
        engine.stop()
        self.assertIn(CLOCK, output.messages)

    def test_send_error_stops_engine(self) -> None:
        output = FakeOutput(fail_on_clock=True)
        engine = ClockEngine(output, 120)
        engine.start()
        time.sleep(0.1)
        engine.stop()
        self.assertIsNotNone(engine.last_error)
        self.assertFalse(engine.running)

    def test_list_devices_returns_tuple(self) -> None:
        self.assertIsInstance(MidiOutput.list_devices(), tuple)

    def test_open_invalid_device_fails(self) -> None:
        if not MidiOutput.available():
            self.skipTest("Windows only")
        output = MidiOutput()
        with self.assertRaises(RuntimeError):
            output.open(9999)

    def test_clock_monitor_computes_bpm(self) -> None:
        clock = FakeClock()
        monitor = ClockMonitor(clock=clock)
        monitor.feed(START)
        interval = 60.0 / (120 * 24)
        for _ in range(25):
            clock.value += interval
            monitor.feed(CLOCK)
        self.assertIsNotNone(monitor.bpm)
        self.assertAlmostEqual(monitor.bpm or 0.0, 120.0, places=1)
        self.assertEqual(monitor.pulses, 25)
        self.assertTrue(monitor.running)

    def test_clock_monitor_stop_and_stale(self) -> None:
        clock = FakeClock()
        monitor = ClockMonitor(clock=clock)
        monitor.feed(START)
        clock.value += 0.1
        monitor.feed(CLOCK)
        monitor.feed(STOP)
        self.assertFalse(monitor.running)

        monitor.feed(START)
        self.assertTrue(monitor.running)
        clock.value += 2.0
        self.assertFalse(monitor.running)

    def test_list_input_devices_returns_tuple(self) -> None:
        self.assertIsInstance(MidiInput.list_devices(), tuple)

    def test_open_invalid_input_fails(self) -> None:
        if not MidiInput.available():
            self.skipTest("Windows only")
        input_device = MidiInput()
        with self.assertRaises(RuntimeError):
            input_device.open(9999, lambda status: None)


if __name__ == "__main__":
    unittest.main()
