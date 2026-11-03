"""Tests for termux/panel/recorder.py. They need Linux (process groups) and Termux ffmpeg, so run them
on the phone: bash tests/run-on-phone.sh -k RecorderTest
"""
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "termux" / "panel"))
import cameras  # noqa: E402
import recorder  # noqa: E402
from clips import ClipStore  # noqa: E402
from settings import RecorderSettings  # noqa: E402

# Stand-ins for the motion ffmpeg (gray 320x180 frames on stdout). Each one first writes its pid
# (= its process group) to the file named in argv[1], so a test can tell whether it is gone.
START = "import os,sys,time\nopen(sys.argv[1],'a').write('%d\\n' % os.getpid())\n"
DRAW = (START + "W, H = 320, 180\n"
        "bg = bytes(60 + (x // 16 + y // 16) % 2 * 20 for y in range(H) for x in range(W))\n"
        "def frame(x):\n"
        "    f = bytearray(bg)\n"
        "    for r in range(70, 110):\n"
        "        f[r * W + x:r * W + x + 40] = b'\\xf0' * 40\n"
        "    return bytes(f)\n"
        "out = sys.stdout.buffer\n")
# a square moving for 3 s, then standing still
FRAMES = DRAW + "i = 0\nwhile True:\n    out.write(frame(10 + 8 * min(i, 30))); out.flush(); i += 1; time.sleep(0.1)"
STILLFRAMES = DRAW + "f = frame(10)\nwhile True:\n    out.write(f); out.flush(); time.sleep(0.1)"
DIES = START + "raise SystemExit(1)"
# one frame and gone; each launch puts the square somewhere else (the pid file counts the launches)
ONEFRAME = DRAW + "k = len(open(sys.argv[1]).read().split())\nout.write(frame(10 + 120 * (k % 2))); out.flush()"
ENDLESS = START + "out = sys.stdout.buffer\nwhile True:\n    out.write(b'x' * 65536)"
# the record source: ffmpeg's test pattern as fragmented H.265, one fragment a second, in real time
REAL = ["ffmpeg", "-nostdin", "-loglevel", "error", "-re", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=10",
        "-c:v", "libx265", "-x265-params", "keyint=10:log-level=error", "-tag:v", "hvc1",
        "-f", "mp4", "-movflags", "frag_keyframe+empty_moov+default_base_moof", "pipe:1"]


def alive(pid):
    try:
        os.killpg(pid, 0)  # signal 0 only asks; a zombie (not waited for) still counts
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class Source:
    """Fake command function: counts launches, and notes when one starts while the last is still there."""

    def __init__(self, folder, label, script=None):
        self.pids = Path(folder) / f"{label}.pids"
        self.script = script
        self.launches = 0
        self.overlaps = 0

    def pid_list(self):
        try:
            return [int(p) for p in self.pids.read_text().split()]
        except OSError:
            return []

    def __call__(self, *args):
        if any(alive(p) for p in self.pid_list()):
            self.overlaps += 1
        self.launches += 1
        if self.script is None:  # real ffmpeg, through sh so its pid is written too (exec keeps it)
            return ["sh", "-c", 'echo $$ >> "$0"; exec "$@"', str(self.pids), *REAL]
        return [sys.executable, "-c", self.script, str(self.pids)]


class FakeCamera:
    def __init__(self, n, name, settings, store, finisher, stills, allow_new):
        self.n, self.name, self.settings = n, name, settings
        self.calls = []

    def start(self):
        self.calls.append("start")

    def stop(self, finish=True):
        self.calls.append(("stop", finish))

    def apply(self, settings):
        self.calls.append("apply")
        self.settings = settings

    def state(self, now):
        return {"name": self.name, "n": self.n, "state": "watching", "obstructed": None,
                "last_motion": None, "last_frame": int(now), "last_fragment": int(now), "today": 0}


class RecorderTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        # never write into the server's real log
        old = recorder.LOG, recorder.LOG_MAX
        recorder.LOG = self.tmp / "recorder.log"
        self.addCleanup(lambda: (setattr(recorder, "LOG", old[0]), setattr(recorder, "LOG_MAX", old[1])))
        self.store = ClipStore(self.tmp / "recordings")
        self.stills = self.tmp / "stills"
        self.stills.mkdir()

    def settings(self, **kw):
        args = dict(cameras=("Entrada",), before_s=1, after_s=2, sensitivity=5, check="fast", obstructed="keep")
        args.update(kw)
        return RecorderSettings(**args)

    def camera(self, motion, record, allow_new=lambda: True, **kw):
        """A started camera; motion/record are Source objects. Stopped at the end even if the test fails."""
        finisher = recorder.Finisher(self.store, lambda: None)
        finisher.start()
        self.addCleanup(finisher.stop)
        self.assertTrue(finisher.recovered.wait(30))
        cam = recorder.Camera(1, "Entrada", self.settings(**kw), self.store, finisher, self.stills, allow_new,
                              motion_cmd=motion, record_cmd=record, backoff=(0.2, 1), offline_s=1.5)
        self.addCleanup(cam.stop, False)
        return cam

    def wait_for(self, check, seconds):
        end = time.time() + seconds
        while time.time() < end:
            if check():
                return True
            time.sleep(0.25)
        return check()

    # --- commands ---

    def test_commands(self):
        p = Path("/x/recorder-stills/cam2.jpg")
        self.assertEqual(recorder.motion_cmd(2, "fast", p), [
            "ffmpeg", "-nostdin", "-loglevel", "error",
            "-rtsp_transport", "tcp", "-timeout", "10000000", "-user_agent", "drawer-recorder",
            "-i", "rtsp://127.0.0.1:8554/cam2", "-filter_complex",
            "[0:v]split=2[m][s];[m]fps=2,scale=320:180,format=gray[mo];[s]select=key[so]",
            "-map", "[mo]", "-fps_mode", "passthrough", "-f", "rawvideo", "pipe:1",
            "-map", "[so]", "-fps_mode", "passthrough", "-q:v", "5", "-update", "1", "-atomic_writing", "1",
            "-y", "/x/recorder-stills/cam2.jpg"])
        light = recorder.motion_cmd(2, "light", p)
        self.assertEqual(light[4:7], ["-skip_frame", "nokey", "-rtsp_transport"])
        self.assertNotIn("fps=2", " ".join(light))
        rec = recorder.record_cmd(3)
        self.assertEqual(rec[rec.index("-i") + 1], "rtsp://127.0.0.1:8554/cam3_hd")
        self.assertEqual(rec[-1], "pipe:1")
        self.assertNotIn("-tag:v", rec)  # an H.264 camera can't take the hvc1 tag; finish() adds it for H.265

    def test_leftover_pattern(self):
        data = Path("/data/data/com.termux/files/home/.cache/drawer-server")
        motion_line = " ".join(recorder.motion_cmd(1, "fast", data / "recorder-stills" / "cam1.jpg"))
        self.assertIn(recorder.LEFTOVER_PATTERN, motion_line)
        self.assertIn(recorder.LEFTOVER_PATTERN, " ".join(recorder.record_cmd(1)))
        panel_line = " ".join(cameras.ffmpeg_cmd(cameras.default_url(1), data / "cams" / "cam1.jpg"))
        self.assertNotIn(recorder.LEFTOVER_PATTERN, panel_line)
        # the panel's kill_leftovers pattern must not catch the recorder's motion ffmpeg
        self.assertIsNotNone(re.search(f"ffmpeg .*{data / 'cams'}/", panel_line))
        self.assertIsNone(re.search(f"ffmpeg .*{data / 'cams'}/", motion_line))

    # --- one camera, real processes ---

    def test_clip_made(self):
        cam = self.camera(Source(self.tmp, "motion", FRAMES), Source(self.tmp, "record"))
        cam.start()

        def made():
            found = self.store.cameras()
            if not found:
                return False
            rows = self.store.clips(found[0]["folder"], found[0]["days"][0])
            return len(rows) == 1 and rows[0]["thumb"]
        self.assertTrue(self.wait_for(made, 20))
        self.assertEqual(self.store.count("Entrada", self.store.cameras()[0]["days"][0]), 1)

    def test_still_image_no_clip(self):
        cam = self.camera(Source(self.tmp, "motion", STILLFRAMES), Source(self.tmp, "record"))
        cam.start()
        time.sleep(8)
        self.assertEqual(self.store.parts(), [])
        self.assertEqual(self.store.cameras(), [])
        state = cam.state(time.time())
        self.assertEqual(state["state"], "watching")
        self.assertEqual((state["name"], state["n"], state["today"]), ("Entrada", 1, 0))
        self.assertIsNone(state["last_motion"])
        self.assertIsNotNone(state["last_frame"])
        self.assertIsNotNone(state["last_fragment"])  # the HD stream arrives too (step 12 waits for it)

    def test_restarts_with_backoff(self):
        motion, record = Source(self.tmp, "motion", DIES), Source(self.tmp, "record", DIES)
        cam = self.camera(motion, record)
        cam.start()
        time.sleep(3)
        for src in (motion, record):
            self.assertTrue(3 <= src.launches <= 10, src.launches)
            self.assertEqual(src.overlaps, 0)

    def test_restart_starts_detection_fresh(self):
        # light mode looks once: comparing a new session's first frame with the last session's would be motion
        motion = Source(self.tmp, "motion", ONEFRAME)
        cam = self.camera(motion, Source(self.tmp, "record", DIES), check="light")
        cam.start()
        self.assertTrue(self.wait_for(lambda: motion.launches >= 3 and cam.state(time.time())["last_frame"], 5))
        time.sleep(0.5)
        self.assertIsNone(cam.state(time.time())["last_motion"])

    def test_offline_state(self):
        cam = self.camera(Source(self.tmp, "motion", DIES), Source(self.tmp, "record", DIES))
        cam.start()
        time.sleep(2)
        self.assertEqual(cam.state(time.time())["state"], "offline")

    def test_stop_does_not_hang(self):
        motion, record = Source(self.tmp, "motion", ENDLESS), Source(self.tmp, "record", ENDLESS)
        cam = self.camera(motion, record)
        cam.start()
        self.assertTrue(self.wait_for(lambda: motion.pid_list() and record.pid_list(), 5))
        time.sleep(0.5)
        began = time.time()
        cam.stop()
        self.assertLess(time.time() - began, 3)
        for pid in motion.pid_list() + record.pid_list():
            self.assertFalse(alive(pid), pid)

    def test_pause_when_obstructed(self):
        cam = self.camera(Source(self.tmp, "motion", FRAMES), Source(self.tmp, "record"), obstructed="pause")
        cam.obstruction.update = lambda now, motion, frame: "moving"
        cam.start()
        time.sleep(8)
        self.assertEqual(self.store.parts(), [])
        self.assertEqual(self.store.cameras(), [])
        state = cam.state(time.time())
        self.assertEqual((state["state"], state["obstructed"]), ("paused", "moving"))
        self.assertIsNotNone(state["last_motion"])  # it did see the motion

    def test_disk_full_blocks_new_clips(self):
        cam = self.camera(Source(self.tmp, "motion", FRAMES), Source(self.tmp, "record"), allow_new=lambda: False)
        cam.start()
        time.sleep(7)
        self.assertEqual(self.store.parts(), [])
        self.assertEqual(self.store.cameras(), [])
        self.assertIsNotNone(cam.state(time.time())["last_motion"])  # it did see the motion

    # --- the whole recorder, fake cameras ---

    def recorder(self, recorded):
        config, data = self.tmp / "config", self.tmp / "data"
        config.mkdir()
        (config / "cameras").write_text("Entrada\nFondo\nLateral\n")
        (config / "recorder").write_text(f"cameras={recorded}\n")
        made = {}

        def factory(*args):
            cam = FakeCamera(*args)
            made[cam.name] = cam
            return cam
        rec = recorder.Recorder(config, data, self.store, camera_factory=factory)
        return rec, made, config, data

    def test_camera_removed(self):
        rec, made, config, data = self.recorder("Entrada,Fondo")
        rec.tick(1000)
        self.assertEqual(sorted(made), ["Entrada", "Fondo"])
        self.assertEqual(made["Fondo"].calls, ["start"])
        (config / "recorder").write_text("cameras=Entrada\n")
        rec.tick(1010)  # not due yet
        self.assertEqual(made["Fondo"].calls, ["start"])
        rec.tick(1031)
        self.assertIn("stop", [c[0] for c in made["Fondo"].calls if isinstance(c, tuple)])
        self.assertNotIn("stop", [c[0] for c in made["Entrada"].calls if isinstance(c, tuple)])
        state = json.loads((data / "recorder.json").read_text())
        by_name = {c["name"]: c for c in state["cameras"]}
        self.assertEqual(by_name["Fondo"]["state"], "off")
        self.assertEqual(by_name["Fondo"]["n"], 2)
        self.assertEqual(by_name["Entrada"]["state"], "watching")
        rec.stop()
        self.assertEqual(made["Entrada"].calls[-1], ("stop", False))

    def test_state_file(self):
        rec, made, config, data = self.recorder("Entrada")
        rec.tick(time.time())
        state = json.loads((data / "recorder.json").read_text())
        self.assertEqual(set(state), {"time", "bytes", "disk_full", "cameras"})
        self.assertIsInstance(state["time"], int)
        self.assertEqual(state["bytes"], 0)
        self.assertIs(state["disk_full"], False)
        self.assertEqual([(c["name"], c["n"], c["state"]) for c in state["cameras"]],
                         [("Entrada", 1, "watching"), ("Fondo", 2, "off"), ("Lateral", 3, "off")])
        self.assertEqual(set(state["cameras"][1]),
                         {"name", "n", "state", "obstructed", "last_motion", "last_frame", "last_fragment", "today"})
        self.assertEqual(list(data.glob("*.tmp")), [])
        self.assertTrue((data / "recorder-stills").is_dir())
        self.assertEqual(list(made), ["Entrada"])

    def test_renamed_camera_shows_not_recording(self):
        # step 11 renamed "Patio" to "Lateral" but the recorder settings still list "Patio": no silent "off"
        rec, made, config, data = self.recorder("Entrada, Patio,Patio")
        touch = self.store.root / "Patio" / time.strftime("%Y-%m-%d") / "090000-5.mp4"
        touch.parent.mkdir(parents=True)
        touch.write_bytes(b"x")
        rec.tick(time.time())
        state = json.loads((data / "recorder.json").read_text())
        self.assertEqual([(c["name"], c["n"], c["state"]) for c in state["cameras"]],
                         [("Entrada", 1, "watching"), ("Fondo", 2, "off"), ("Lateral", 3, "off"),
                          ("Patio", None, "offline")])
        self.assertEqual(state["cameras"][3], {"name": "Patio", "n": None, "state": "offline", "obstructed": None,
                                               "last_motion": None, "last_frame": None, "last_fragment": None,
                                               "today": 1})
        self.assertEqual(list(made), ["Entrada"])
        (config / "recorder").write_text("cameras=\n")  # all cameras: nothing unknown
        rec.tick(time.time() + 31)
        state = json.loads((data / "recorder.json").read_text())
        self.assertEqual([c["name"] for c in state["cameras"]], ["Entrada", "Fondo", "Lateral"])

    def test_recordings_folder_removed(self):
        # the docs say "rm -r ~/recordings" to start over: settings must keep reloading
        rec, made, config, data = self.recorder("Entrada")
        rec.tick(1000)
        shutil.rmtree(self.store.root)
        (config / "recorder").write_text("cameras=Entrada,Fondo\n")
        rec._enforce_now = True
        rec.tick(1031)
        self.assertEqual(sorted(made), ["Entrada", "Fondo"])
        self.assertTrue(self.store.root.is_dir())
        log = recorder.LOG.read_text() if recorder.LOG.exists() else ""
        self.assertNotIn("failed", log)
        shutil.rmtree(self.store.root)
        rec._enforce()  # gone between two reloads: the disk check copes too
        self.assertTrue(rec.floor_ok)

    def test_log_rotates(self):
        recorder.LOG_MAX = 200
        for i in range(10):
            recorder.log(f"camera 1 (Entrada) motion ended, line {i}")
        self.assertTrue(recorder.LOG.with_name("recorder.log.1").exists())
        self.assertLess(recorder.LOG.stat().st_size, 200)
        self.assertIn("line 9", recorder.LOG.read_text())


if __name__ == "__main__":
    unittest.main()
