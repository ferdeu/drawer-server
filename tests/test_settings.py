"""Tests for termux/panel/settings.py. Run on the phone: bash tests/run-on-phone.sh -k SettingsTest"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "termux" / "panel"))
import settings  # noqa: E402
from settings import DiskSettings, RecorderSettings  # noqa: E402

CAMS = ["Entrada", "Lateral", "Fondo"]


class SettingsTest(unittest.TestCase):
    def test_read_kv(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "recorder"
            f.write_text("cameras = Entrada, Fondo\n# note\nbad line\nbefore=7\n")
            self.assertEqual(settings.read_kv(f), {"cameras": "Entrada, Fondo", "before": "7"})
            self.assertEqual(settings.read_kv(Path(d) / "nope"), {})

    def test_recorder_defaults(self):
        self.assertEqual(settings.recorder_settings({}, CAMS),
                         RecorderSettings(("Entrada", "Lateral", "Fondo"), 5, 10, 5, "fast", "keep"))

    def test_recorder_cameras(self):
        got = settings.recorder_settings({"cameras": "Fondo, Nope ,Entrada"}, CAMS)
        self.assertEqual(got.cameras, ("Entrada", "Fondo"))

    def test_recorder_clamps(self):
        def rs(**kv):
            return settings.recorder_settings(kv, CAMS)
        self.assertEqual(rs(before="99").before_s, 30)
        self.assertEqual(rs(before="-3").before_s, 5)
        self.assertEqual(rs(after="1").after_s, 2)
        self.assertEqual(rs(sensitivity="0").sensitivity, 1)
        self.assertEqual(rs(sensitivity="x").sensitivity, 5)
        self.assertEqual(rs(check="turbo").check, "fast")
        self.assertEqual(rs(check="light").check, "light")
        self.assertEqual(rs(check="LIGHT").check, "light")
        self.assertEqual(rs(check="careful").check, "fast")
        self.assertEqual(rs(obstructed="PAUSE").obstructed, "pause")

    def test_disk_defaults(self):
        self.assertEqual(settings.disk_settings({}, 108_000_000_000),
                         DiskSettings(10_800_000_000, None, False, 5_000_000_000))

    def test_disk_values(self):
        got = settings.disk_settings({"recordings_gb": "20", "backup_gb": "50.5",
                                      "backup_pause": "yes", "keep_free_gb": "0.2"}, 108_000_000_000)
        self.assertEqual(got, DiskSettings(20_000_000_000, 50_500_000_000, True, 1_000_000_000))
        self.assertIsInstance(got.backup_bytes, int)
        self.assertEqual(settings.disk_settings({"recordings_gb": "500"}, 108_000_000_000).recordings_bytes,
                         108_000_000_000)
        self.assertEqual(settings.disk_settings({"recordings_gb": "0"}, 108_000_000_000).recordings_bytes,
                         1_000_000_000)

    def test_shows_recordings(self):
        self.assertTrue(settings.shows_recordings({}))
        self.assertFalse(settings.shows_recordings({"show": "no"}))
        self.assertTrue(settings.shows_recordings({"show": "yes"}))
