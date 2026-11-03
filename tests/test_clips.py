"""Tests for termux/panel/clips.py. Run on the phone: bash tests/run-on-phone.sh -k ClipsTest"""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "termux" / "panel"))
import clips  # noqa: E402
from clips import ClipStore  # noqa: E402


def touch(path, size=1):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


class ClipsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "recordings"
        self.root.mkdir()
        self.store = ClipStore(self.root)

    def test_folder_names(self):
        self.assertEqual(clips.folder_for("Entrada"), "Entrada")
        self.assertEqual(clips.folder_for("Patio trasero"), "Patio%20trasero")
        self.assertEqual(clips.folder_for(".."), "%2E%2E")
        self.assertEqual(clips.camera_for(clips.folder_for("Ñandú 2.0")), "Ñandú 2.0")
        for name in ("Entrada", "Patio trasero", "..", "Ñandú 2.0", "a/b"):
            self.assertTrue(clips.FOLDER.fullmatch(clips.folder_for(name)))

    def test_folder_names_long_and_empty(self):
        a = "Ñ" * 60
        b = "Ñ" * 59 + "Ú"
        for name in (a, b, "", "x" * 300):
            f = clips.folder_for(name)
            self.assertTrue(clips.FOLDER.fullmatch(f), name)
            self.assertLessEqual(len(f), 200)
        self.assertNotEqual(clips.folder_for(a), clips.folder_for(b))
        head = clips.folder_for(a).split("~")[0]
        self.assertRegex(head, r"(?:%[0-9A-F]{2}|[^%])*")  # no cut inside a %XX
        part = self.store.new_part(a, time.time())
        touch(part, 3)
        self.assertEqual(self.store.parts(), [part])
        self.assertEqual(self.store.total_bytes(), 3)

    def test_new_part(self):
        start = time.mktime((2026, 10, 31, 14, 30, 5, 0, 0, -1))
        p = self.store.new_part("Entrada", start)
        self.assertEqual(p, self.root / "Entrada" / "2026-10-31" / "143005.part.mp4")
        self.assertTrue(p.parent.is_dir())
        touch(p.parent / "143005-42.mp4")
        self.assertEqual(self.store.new_part("Entrada", start).name, "143006.part.mp4")

    def test_part_day_is_start_day(self):
        start = time.mktime((2026, 10, 31, 23, 59, 50, 0, 0, -1))
        p = self.store.new_part("Entrada", start)
        self.assertEqual(p.parent.name, "2026-10-31")
        self.assertEqual(self.store.remux_path(p).name, "235950.remux.mp4")
        clip, thumb = self.store.final_paths(p, 42)
        self.assertEqual(clip, p.parent / "235950-42.mp4")
        self.assertEqual(thumb, p.parent / "235950-42.jpg")

    def test_clips_listing(self):
        d = self.root / "Entrada" / "2026-10-31"
        for n in ("143005-42.mp4", "143005-42.jpg", "150000-8.mp4", "junk.txt", "160000.part.mp4"):
            touch(d / n)
        self.assertEqual(self.store.clips("Entrada", "2026-10-31"), [
            {"file": "150000-8.mp4", "time": "15:00:00", "len": 8, "thumb": False},
            {"file": "143005-42.mp4", "time": "14:30:05", "len": 42, "thumb": True}])
        self.assertEqual(self.store.clips("..", "2026-10-31"), [])
        self.assertEqual(self.store.clips("Entrada", "../x"), [])
        self.assertEqual(self.store.count("Entrada", "2026-10-31"), 2)
        self.assertEqual(self.store.count("Nope", "2026-10-31"), 0)

    def test_old_camera_folder_listed(self):
        touch(self.root / "Viejo" / "2026-10-30" / "090000-5.mp4", 7)
        touch(self.root / "Entrada" / "2026-10-30" / "090000-5.mp4")
        touch(self.root / "Entrada" / "2026-10-31" / "090000-5.mp4")
        touch(self.root / "Vacia" / "2026-10-31" / "notes.txt")
        self.assertEqual(self.store.cameras(), [
            {"folder": "Entrada", "name": "Entrada", "days": ["2026-10-31", "2026-10-30"]},
            {"folder": "Viejo", "name": "Viejo", "days": ["2026-10-30"]}])
        self.assertEqual(self.store.total_bytes(), 9)

    def test_file_fenced(self):
        d = self.root / "Entrada" / "2026-10-31"
        ok = touch(d / "143005-42.mp4")
        self.assertEqual(self.store.file("Entrada", "2026-10-31", "143005-42.mp4"), ok)
        self.assertIsNone(self.store.file("..", "2026-10-31", "143005-42.mp4"))
        self.assertIsNone(self.store.file("Entrada", "../x", "143005-42.mp4"))
        self.assertIsNone(self.store.file("Entrada", "2026-10-31", "../../etc"))
        self.assertIsNone(self.store.file("Entrada", "2026-10-31", "143005-43.mp4"))
        outside = touch(Path(self._tmp.name) / "secret.txt")
        try:
            os.symlink(outside, d / "120000-5.mp4")
            os.symlink(self.root / "Entrada" / "2026-10-31", self.root / "Entrada" / "2026-10-29")
        except (OSError, NotImplementedError):
            self.skipTest("no symlinks here")
        self.assertIsNone(self.store.file("Entrada", "2026-10-31", "120000-5.mp4"))
        self.assertIsNone(self.store.file("Entrada", "2026-10-29", "143005-42.mp4"))

    def test_enforce_oldest_first_across_cameras(self):
        touch(self.root / "Entrada" / "2026-10-30" / "090000-10.mp4", 100)
        touch(self.root / "Entrada" / "2026-10-30" / "090000-10.jpg", 10)
        touch(self.root / "Fondo" / "2026-10-30" / "080000-10.mp4", 100)
        touch(self.root / "Fondo" / "2026-10-31" / "070000-10.mp4", 100)
        self.assertEqual(self.store.enforce(150, 0, lambda: 10**12), (100, True))
        self.assertTrue((self.root / "Fondo" / "2026-10-31" / "070000-10.mp4").exists())
        self.assertFalse((self.root / "Fondo" / "2026-10-30").exists())
        self.assertFalse((self.root / "Entrada").exists())

    def test_enforce_never_touches_others(self):
        d = self.root / "Entrada" / "2026-10-31"
        notes = touch(d / "notes.txt")
        part = touch(d / "090000.part.mp4")
        outside = touch(Path(self._tmp.name) / "photo.mp4", 5)
        try:
            os.symlink(outside, d / "100000-5.mp4")
        except (OSError, NotImplementedError):
            self.skipTest("no symlinks here")
        self.store.enforce(0, 0, lambda: 10**12)
        self.assertTrue(notes.exists())
        self.assertTrue(part.exists())
        self.assertTrue(os.path.islink(d / "100000-5.mp4"))
        self.assertTrue(outside.exists())

    def test_never_deletes_through_symlinked_folders(self):
        # a camera folder and a day folder that are symlinks to outside folders full of clip-like names
        outside = Path(self._tmp.name) / "outside"
        names = ("090000-10.mp4", "090000-10.jpg", "100000.part.mp4", "110000.remux.mp4")
        cam_target, day_target = outside / "cam", outside / "day"
        files = [touch(cam_target / "2026-10-30" / n) for n in names] + [touch(day_target / n) for n in names]
        try:
            os.symlink(cam_target, self.root / "Fondo")
            (self.root / "Entrada").mkdir()
            os.symlink(day_target, self.root / "Entrada" / "2026-10-31")
        except (OSError, NotImplementedError):
            self.skipTest("no symlinks here")
        self.store.enforce(0, 0, lambda: 10**12)
        for f in files:
            self.store.discard(f)
        for folder, day in (("Fondo", "2026-10-30"), ("Entrada", "2026-10-31")):
            for n in names:
                self.store.discard(self.root / folder / day / n)
        for f in files:
            self.assertTrue(f.exists(), f)
        self.assertTrue(os.path.islink(self.root / "Fondo"))
        self.assertTrue(os.path.islink(self.root / "Entrada" / "2026-10-31"))

    def test_has_clips(self):
        self.assertFalse(self.store.has_clips())
        touch(self.root / "Entrada" / "2026-10-31" / "090000.part.mp4")
        touch(self.root / "Entrada" / "2026-10-31" / "notes.txt")
        self.assertFalse(self.store.has_clips())
        outside = touch(Path(self._tmp.name) / "elsewhere" / "2026-10-31" / "090000-5.mp4")
        try:
            os.symlink(outside.parent.parent, self.root / "Fondo")
        except (OSError, NotImplementedError):
            self.skipTest("no symlinks here")
        self.assertFalse(self.store.has_clips())
        touch(self.root / "Entrada" / "2026-10-30" / "090000-5.mp4")
        self.assertTrue(self.store.has_clips())
        calls = []
        real = self.store._files
        self.store._files = lambda *a: calls.append(a) or real(*a)
        touch(self.root / "Viejo" / "2026-10-30" / "090000-5.mp4")
        self.assertTrue(self.store.has_clips())
        self.assertEqual(len(calls), 1)  # stops at the first clip it finds

    def test_floor(self):
        touch(self.root / "Entrada" / "2026-10-31" / "090000-10.mp4", 50)
        touch(self.root / "Entrada" / "2026-10-31" / "090000-10.jpg", 5)
        touch(self.root / "Fondo" / "2026-10-31" / "080000-10.mp4", 50)
        self.assertEqual(self.store.enforce(10**12, 5 * 10**9, lambda: 1), (0, False))
        self.assertEqual(self.store.cameras(), [])

    def test_total_bytes(self):
        d = self.root / "Entrada" / "2026-10-31"
        touch(d / "090000-10.mp4", 10)
        touch(d / "090000-10.jpg", 2)
        touch(d / "100000.part.mp4", 4)
        touch(d / "110000.remux.mp4", 8)
        touch(d / "notes.txt", 100)
        self.assertEqual(self.store.total_bytes(), 24)

    def test_discard_fenced(self):
        d = self.root / "Entrada" / "2026-10-31"
        part = touch(d / "100000.part.mp4")
        clip = touch(d / "090000-10.mp4")
        self.store.discard(part)
        self.store.discard(clip)
        self.store.discard(d / "nope.part.mp4")
        self.assertFalse(part.exists())
        self.assertTrue(clip.exists())
        self.assertEqual(self.store.parts(), [])


if __name__ == "__main__":
    unittest.main()
