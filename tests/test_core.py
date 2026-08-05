import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.capture import CaptureManager
from core.firebase_client import firebase_safe_payload
from core.models import SessionSpec, firebase_safe_key, minutes_to_seconds
from core.parsers import Board3AutoParser, FramedKeyValueParser, JsonLineParser, LibeliumParser
from core.registry import BoardRegistry
from core.storage import SessionStore


class _OfflineFirebase:
    message = "offline test"

    def write_session_metadata(self, _spec):
        return False

    def write_reading(self, *_args):
        return False

    def queue_count(self, _path):
        return 0


class _SlowFirebase(_OfflineFirebase):
    def write_reading(self, *_args):
        import time
        time.sleep(0.5)
        return True


class _NoopWorker:
    def __init__(self, *_args, **_kwargs):
        pass

    def start(self):
        pass

    def stop(self):
        pass

    def join(self, timeout=None):
        pass


class ParserTests(unittest.TestCase):
    def test_json_line_parser(self):
        parser = JsonLineParser("B3")
        reading = parser.feed('{"CO2":{"value":451.2,"unit":"ppm"},"Temperature":{"value":24.1,"unit":"C"}}')
        self.assertIsNotNone(reading)
        self.assertEqual(reading.board_id, "B3")
        self.assertAlmostEqual(reading.sensors["CO2"].value, 451.2)
        self.assertEqual(reading.sensors["Temperature"].unit, "C")

    def test_framed_parser(self):
        parser = FramedKeyValueParser("B1")
        self.assertIsNone(parser.feed("new data"))
        self.assertIsNone(parser.feed("CO: 1.25 ppm"))
        reading = parser.feed("*")
        self.assertIsNotNone(reading)
        self.assertAlmostEqual(reading.sensors["CO"].value, 1.25)

    def test_libelium_battery_is_attached_to_reading(self):
        parser = LibeliumParser("LB1")
        self.assertIsNone(parser.feed("Battery Level: 82% | Battery (Volts): 3.91"))
        self.assertIsNone(parser.feed("new data"))
        self.assertIsNone(parser.feed("SO2: 0.11 ppm"))
        reading = parser.feed("new data")
        self.assertIsNotNone(reading)
        self.assertEqual(reading.battery_percent, 82.0)
        self.assertEqual(reading.battery_volts, 3.91)

    def test_libelium_accepts_actual_waspmote_output(self):
        parser = LibeliumParser("LB1")
        self.assertIsNone(parser.feed("Battery Level: 82 % | Battery (Volts): 3.91 V"))
        self.assertIsNone(parser.feed("New Data..."))
        self.assertIsNone(parser.feed("NO: 0.12 ppm"))
        self.assertIsNone(parser.feed("CO: 0.34 ppm"))
        self.assertIsNone(parser.feed("NO2: 0.56 ppm"))
        reading = parser.feed("NH3: 0.78 ppm")
        self.assertIsNotNone(reading)
        self.assertEqual(reading.sensors["NO"].value, 0.12)
        self.assertEqual(reading.battery_percent, 82.0)

    def test_lb2_emits_first_complete_waspmote_cycle(self):
        parser = LibeliumParser("LB2")
        lines = ["New Data...", "SO2: 0.1 ppm", "O3: 0.2 ppm", "H2S: 0.3 ppm", "O2: 20.4 ppm"]
        for line in lines:
            self.assertIsNone(parser.feed(line))
        reading = parser.feed("CH4: 0.5 ppm")
        self.assertIsNotNone(reading)
        self.assertEqual(len(reading.sensors), 5)

    def test_board3_current_sectioned_report(self):
        parser = Board3AutoParser("B3")
        lines = [
            "---------------------------------------------",
            "[ Grove - Air Quality Sensor v1.3 ]",
            "Raw AQ Value: 10",
            "---------------------------------------------",
            "[ Grove - Multichannel Gas Sensor v1.0 ]",
            "NH3 (Ammonia)       : 0.04 ppm",
            "CO (Carbon Mon.)    : 0.03 ppm",
            "NO2 (Nitrogen Dio.) : 0.82 ppm",
            "---------------------------------------------",
            "[ Grove - CO2 / Temperature / Humidity (SCD30) ]",
            "CO2 (Carbon Dioxide): 524.7 ppm",
            "Temperature: 21.63 °C",
            "Humidity: 35.5 %",
            "---------------------------------------------",
            "[ Grove - All-in-One Environmental Sensor (SEN55) ]",
            "PM2.5: 0.00 ľg/mł",
            "VOC Index: 0.0",
            "=============================================",
        ]
        reading = None
        for line in lines:
            reading = parser.feed(line) or reading
        self.assertIsNotNone(reading)
        self.assertEqual(reading.board_id, "B3")
        self.assertAlmostEqual(reading.sensors["CO2 (Carbon Dioxide)"].value, 524.7)
        self.assertEqual(reading.sensors["Temperature"].unit, "C")
        self.assertEqual(reading.sensors["PM2.5"].unit, "ug/m3")

    def test_board3_auto_still_accepts_json(self):
        parser = Board3AutoParser("B3")
        reading = parser.feed('{"CO2":{"value":500,"unit":"ppm"}}')
        self.assertIsNotNone(reading)
        self.assertEqual(reading.sensors["CO2"].value, 500)

    def test_board3_accepts_short_separators_and_heading_start(self):
        parser = Board3AutoParser("B3")
        self.assertIsNone(parser.feed("[ Grove sensor ]"))
        self.assertIsNone(parser.feed("CO2: 501 ppm"))
        reading = parser.feed("=====")
        self.assertIsNotNone(reading)
        self.assertEqual(reading.sensors["CO2"].value, 501)


class DurationTests(unittest.TestCase):
    def test_minutes_are_converted_exactly(self):
        self.assertEqual(minutes_to_seconds(5), 300)
        self.assertEqual(minutes_to_seconds(0.5), 30)
        self.assertEqual(minutes_to_seconds(0.1), 6)

    def test_missing_or_invalid_duration_is_rejected(self):
        for value in (None, "", 0, -1, float("nan")):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    minutes_to_seconds(value)


class FirebaseKeyTests(unittest.TestCase):
    def test_b3_labels_are_firebase_safe_and_reversible(self):
        parser = JsonLineParser("B3")
        reading = parser.feed('{"PM2.5":{"value":3.2,"unit":"ug/m3"}}')
        payload = reading.firebase_payload()
        safe_label = next(iter(payload["readings"]))
        self.assertNotRegex(safe_label, r"[.#$\[\]/]")
        self.assertEqual(payload["sensor_labels"][safe_label], "PM2.5 (ug/m3)")

    def test_existing_queued_payloads_are_sanitized_recursively(self):
        payload = {"readings": {"CO (Carbon Mon.) (ppm)": 0.03, "PM2.5 (ug/m3)": 1.0}}
        safe = firebase_safe_payload(payload)
        self.assertEqual(len(safe["readings"]), 2)
        for key in safe["readings"]:
            self.assertEqual(key, firebase_safe_key(key))
            self.assertNotRegex(key, r"[.#$\[\]/]")


class StorageTests(unittest.TestCase):
    def test_board_files_are_independent_and_expand_safely(self):
        with tempfile.TemporaryDirectory() as temporary:
            spec = SessionSpec(
                stage="Testing",
                substance="Air",
                session_id="T-Air-test",
                selected_boards={"B1": "COM1", "B3": "COM3"},
                flowrate=1.0,
                interval_seconds=1.0,
                duration_seconds=60,
            )
            store = SessionStore(Path(temporary), spec)
            p1 = JsonLineParser("B1")
            p3 = JsonLineParser("B3")
            store.append(p1.feed('{"CO":{"value":1,"unit":"ppm"}}'))
            store.append(p3.feed('{"CO2":{"value":450,"unit":"ppm"}}'))
            store.append(p3.feed('{"CO2":{"value":451,"unit":"ppm"},"PM2.5":{"value":4,"unit":"ug/m3"}}'))
            store.complete()

            self.assertTrue((store.path / "B1_Readings.csv").exists())
            self.assertTrue((store.path / "B3_Readings.csv").exists())
            with (store.path / "B3_Readings.csv").open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 2)
            self.assertNotIn("Timestamp_ms", rows[0])
            self.assertIn("PM2.5 (ug/m3)", rows[0])
            summary = json.loads((store.path / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["B3"]["sample_count"], 2)


class CaptureTimerTests(unittest.TestCase):
    def test_slow_firebase_does_not_block_live_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            registry = BoardRegistry(Path(__file__).parents[1] / "config" / "boards.json")
            manager = CaptureManager(registry, Path(temporary), _SlowFirebase())
            spec = SessionSpec(
                stage="Testing", substance="Air", session_id="responsive-ui-test",
                selected_boards={"B1": "COM1"}, flowrate=1.0,
                interval_seconds=1.0, duration_seconds=10,
            )
            with patch("core.capture.BoardWorker", _NoopWorker):
                manager.start(spec)
                reading = JsonLineParser("B1").feed('{"CO":{"value":1,"unit":"ppm"}}')
                started = __import__("time").monotonic()
                manager.accept(reading, registry.get("B1"))
                snapshot = manager.snapshot()
                elapsed = __import__("time").monotonic() - started
                self.assertLess(elapsed, 0.2)
                self.assertEqual(len(snapshot["live"]["B1"]), 1)
    def test_libelium_does_not_block_timer_start(self):
        with tempfile.TemporaryDirectory() as temporary:
            registry = BoardRegistry(Path(__file__).parents[1] / "config" / "boards.json")
            manager = CaptureManager(registry, Path(temporary), _OfflineFirebase())
            spec = SessionSpec(
                stage="Testing", substance="Air", session_id="timer-test",
                selected_boards={"B1": "COM1", "LB1": "COM2"},
                flowrate=1.0, interval_seconds=0.0, duration_seconds=0,
            )
            with patch("core.capture.BoardWorker", _NoopWorker):
                manager.start(spec)
                self.assertFalse(manager.capture_clock_started)
                lb_reading = JsonLineParser("LB1").feed('{"CO":{"value":1,"unit":"ppm"}}')
                manager.accept(lb_reading, registry.get("LB1"))
                self.assertFalse(manager.capture_clock_started)
                b1_reading = JsonLineParser("B1").feed('{"CO":{"value":1,"unit":"ppm"}}')
                manager.accept(b1_reading, registry.get("B1"))
                self.assertTrue(manager.capture_clock_started)
                manager.stop()

    def test_libelium_only_capture_starts_timer_immediately(self):
        with tempfile.TemporaryDirectory() as temporary:
            registry = BoardRegistry(Path(__file__).parents[1] / "config" / "boards.json")
            manager = CaptureManager(registry, Path(temporary), _OfflineFirebase())
            spec = SessionSpec(
                stage="Testing", substance="Air", session_id="libelium-timer-test",
                selected_boards={"LB1": "COM2"}, flowrate=1.0,
                interval_seconds=1.0, duration_seconds=0,
            )
            with patch("core.capture.BoardWorker", _NoopWorker):
                manager.start(spec)
                self.assertTrue(manager.capture_clock_started)
                self.assertGreater(manager.started_monotonic, 0)
                manager.stop()


if __name__ == "__main__":
    unittest.main()
