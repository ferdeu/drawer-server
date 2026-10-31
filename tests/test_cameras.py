"""Tests for termux/panel/cameras.py. They need Linux (process groups), so run them on the phone:
bash tests/run-on-phone.sh
"""
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "termux" / "panel"))
import cameras  # noqa: E402

# stand-ins for ffmpeg: one keeps writing a still, one writes once and hangs, one dies at once
WRITER = "import sys,time\nwhile True:\n    open(sys.argv[1],'wb').write(b'\\xff\\xd8jpeg')\n    time.sleep(0.2)"
STUCK = "import sys,time\nopen(sys.argv[1],'wb').write(b'\\xff\\xd8jpeg')\ntime.sleep(60)"
DIES = "raise SystemExit(1)"


def fake(script, launches):
    def cmd(url, out):
        launches.append(url)
        return [sys.executable, "-c", script, str(out)]
    return cmd


class CamerasTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.launches = []
        self.stills = None

    def tearDown(self):
        if self.stills:
            self.stills.stop_all()
        self.tmp.cleanup()

    def make(self, script, **kw):
        self.stills = cameras.Stills(3, self.folder, cmd=fake(script, self.launches), **kw)
        return self.stills

    def wait_image(self, n, seconds=3):
        end = time.time() + seconds
        while time.time() < end:
            img = self.stills.get(n)
            if img:
                return img
            time.sleep(0.1)
        return None

    def test_load_names(self):
        f = self.folder / "cameras"
        f.write_text("Entrada\nLateral\n\nFondo\n")
        self.assertEqual(cameras.load_names(f), ["Entrada", "Lateral", "Fondo"])
        self.assertEqual(cameras.load_names(self.folder / "missing"), [])

    def test_is_home(self):
        for ip in ("192.168.1.20", "10.0.0.5", "172.16.3.4", "127.0.0.1"):
            self.assertTrue(cameras.is_home(ip), ip)
        for ip in ("100.101.102.103", "100.64.0.1", "8.8.8.8"):
            self.assertFalse(cameras.is_home(ip), ip)

    def test_default_url_and_command(self):
        self.assertEqual(cameras.default_url(2), "rtsp://127.0.0.1:8554/cam2")
        cmd = cameras.ffmpeg_cmd("rtsp://x", Path("/o/cam1.jpg"))
        self.assertEqual(cmd[0], "ffmpeg")
        self.assertIn("-skip_frame", cmd)
        self.assertEqual(cmd[cmd.index("-i") + 1], "rtsp://x")
        self.assertEqual(cmd[-1], "/o/cam1.jpg")
        # whole files only (never a half-written still), and give up on a stream that stalls
        self.assertEqual(cmd[cmd.index("-atomic_writing") + 1], "1")
        self.assertLess(cmd.index("-timeout"), cmd.index("-i"))

    def test_get_starts_once(self):
        s = self.make(WRITER)
        threads = [threading.Thread(target=s.get, args=(1,)) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(self.launches, ["rtsp://127.0.0.1:8554/cam1"])
        self.assertEqual(self.wait_image(1), b"\xff\xd8jpeg")
        self.assertEqual(len(self.launches), 1)

    def test_out_of_range(self):
        s = self.make(WRITER)
        for n in (0, 4):
            with self.assertRaises(IndexError):
                s.get(n)

    def test_idle_stop(self):
        s = self.make(WRITER, idle_s=0.5)
        self.assertIsNotNone(self.wait_image(1))
        proc = s.procs[1]
        time.sleep(1)
        s.reap()
        self.assertNotIn(1, s.procs)
        proc.wait(timeout=3)  # really gone, not just forgotten

    def test_stale(self):
        s = self.make(STUCK, stale_s=0.5)
        self.assertIsNotNone(self.wait_image(1))
        time.sleep(1)
        self.assertIsNone(s.get(1))

    def test_stuck_restarts(self):
        # ffmpeg alive but no new stills (stream stalled): replaced even while someone keeps looking
        s = self.make(STUCK, stale_s=0.5, retry_s=0.5)
        self.assertIsNotNone(self.wait_image(1))
        first = s.procs[1]
        end = time.time() + 3
        while len(self.launches) < 2 and time.time() < end:
            s.get(1)
            time.sleep(0.1)
        self.assertEqual(len(self.launches), 2)
        first.wait(timeout=3)  # the stuck one was stopped, not left behind

    def test_offline_retry(self):
        s = self.make(DIES, retry_s=1)
        for _ in range(3):
            s.get(1)
            time.sleep(0.15)
        self.assertEqual(len(self.launches), 1)
        time.sleep(1)
        s.get(1)
        self.assertEqual(len(self.launches), 2)

    def test_stop_all_kills_group(self):
        s = self.make(WRITER)
        s.get(1)
        s.get(2)
        procs = list(s.procs.values())
        s.stop_all()
        for p in procs:
            p.wait(timeout=3)
        self.assertEqual(s.procs, {})


if __name__ == "__main__":
    unittest.main()
