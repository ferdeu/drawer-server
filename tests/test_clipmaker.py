"""Tests for termux/panel/clipmaker.py. Run on the phone: bash tests/run-on-phone.sh -k ClipMakerTest"""
import io
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "termux" / "panel"))
import clipmaker  # noqa: E402
from clipmaker import ClipMaker  # noqa: E402
from clips import ClipStore  # noqa: E402

HDR = b"HDR-ftyp-moov"
FFMPEG_STREAM = ["ffmpeg", "-nostdin", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=10",
                 "-t", "12", "-c:v", "libx265", "-x265-params", "keyint=10:log-level=error", "-tag:v", "hvc1",
                 "-f", "mp4", "-movflags", "frag_keyframe+empty_moov+default_base_moof", "pipe:1"]

# what go2rtc may send instead: H.264, or H.265 that carries ffmpeg's default hev1 tag
H264_STREAM = ["ffmpeg", "-nostdin", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=10",
               "-t", "12", "-c:v", "libx264", "-g", "10", "-pix_fmt", "yuv420p",
               "-f", "mp4", "-movflags", "frag_keyframe+empty_moov+default_base_moof", "pipe:1"]
HEV1_STREAM = [a for a in FFMPEG_STREAM if a not in ("-tag:v", "hvc1")]


def probe(path, entry):
    return subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", entry,
                           "-of", "csv=p=0", str(path)], capture_output=True, text=True, timeout=60).stdout.strip()


def box(kind, payload):
    return struct.pack(">I4s", 8 + len(payload), kind) + payload


def stream(n):
    out = box(b"ftyp", b"isom0000") + box(b"moov", b"movie")
    for i in range(n):
        out += box(b"moof", b"m%03d" % i) + box(b"mdat", b"data%03d" % i)
    return out


def frag(t):
    return b"[%05d]" % t  # same size for every fragment


class FakeMaker:
    def __init__(self):
        self.calls = []

    def header(self, data, now):
        self.calls.append(("header", data, now))

    def fragment(self, data, now):
        self.calls.append(("fragment", data, now))


class ClipMakerTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = ClipStore(Path(self._tmp.name) / "recordings")
        self.done = []
        self.opened = []

    def make(self, **kw):
        def new_part(start):
            self.opened.append(start)
            return self.store.new_part("cam", start)
        args = dict(before_s=5, after_s=10)
        args.update(kw)
        maker = ClipMaker(new_part, lambda *a: self.done.append(a), **args)
        maker.header(HDR, 0)
        self.addCleanup(maker.stop, False)
        return maker

    def feed(self, maker, times):
        for t in times:
            maker.fragment(frag(t), t)

    def content(self, part):
        return Path(part).read_bytes()

    def test_read_box(self):
        data = box(b"free", b"abc")
        self.assertEqual(clipmaker.read_box(io.BytesIO(data).read), ("free", data))
        big = struct.pack(">I4sQ", 1, b"mdat", 16 + 3) + b"xyz"
        self.assertEqual(clipmaker.read_box(io.BytesIO(big).read), ("mdat", big))
        self.assertIsNone(clipmaker.read_box(io.BytesIO(b"").read))
        self.assertIsNone(clipmaker.read_box(io.BytesIO(b"\x00\x00\x00").read))
        self.assertIsNone(clipmaker.read_box(io.BytesIO(data[:-1]).read))
        with self.assertRaises(ValueError):
            clipmaker.read_box(io.BytesIO(struct.pack(">I4s", 4, b"free")).read)
        with self.assertRaises(ValueError):
            clipmaker.read_box(io.BytesIO(struct.pack(">I4s", 0, b"free")).read)

    def test_read_box_too_big(self):
        data = struct.pack(">I4sQ", 1, b"mdat", 2 ** 40) + b"xyz"
        with self.assertRaises(ValueError):
            clipmaker.read_box(io.BytesIO(data).read)

    def test_write_error_still_reports(self):
        maker = self.make()
        self.feed(maker, [4])
        maker.motion(5)
        real_open = open

        class Full:
            def __init__(self, fh):
                self.fh = fh

            def write(self, data):
                raise OSError(28, "No space left on device")

            def flush(self):
                raise OSError(28, "No space left on device")

            def close(self):
                self.fh.close()

        clipmaker.open = lambda path, mode: Full(real_open(path, mode))
        self.addCleanup(lambda: delattr(clipmaker, "open"))
        self.feed(maker, [8])  # must not raise
        self.assertFalse(maker.recording)
        self.assertEqual(len(self.done), 1)
        self.assertEqual(self.done[0][0], self.store.parts()[0])
        maker.motion(9)
        self.feed(maker, [12])
        self.assertEqual(len(self.done), 2)

    def test_pump(self):
        fake = FakeMaker()
        clipmaker.pump(io.BytesIO(stream(3)).read, fake, clock=iter([1.0, 2.0, 3.0, 4.0]).__next__)
        self.assertEqual(fake.calls, [
            ("header", box(b"ftyp", b"isom0000") + box(b"moov", b"movie"), 1.0),
            ("fragment", box(b"moof", b"m000") + box(b"mdat", b"data000"), 2.0),
            ("fragment", box(b"moof", b"m001") + box(b"mdat", b"data001"), 3.0),
            ("fragment", box(b"moof", b"m002") + box(b"mdat", b"data002"), 4.0),
        ])

    def test_preroll(self):
        maker = self.make()
        self.feed(maker, range(4, 21, 4))
        maker.motion(21)
        self.feed(maker, [24])
        self.assertTrue(maker.recording)
        self.assertEqual(self.content(self.store.parts()[0]), HDR + frag(20) + frag(24))

    def test_ends_after(self):
        maker = self.make()
        self.feed(maker, range(4, 21, 4))
        maker.motion(21)
        self.feed(maker, range(24, 41, 4))
        self.assertFalse(maker.recording)
        self.assertEqual(len(self.done), 1)
        part, length, thumb_at = self.done[0]
        self.assertEqual((length, thumb_at), (16.0, 5.0))
        self.assertEqual(self.content(part), HDR + b"".join(frag(t) for t in (20, 24, 28, 32)))
        self.assertEqual(self.opened, [21])

    def test_motion_extends(self):
        maker = self.make()
        self.feed(maker, range(4, 21, 4))
        maker.motion(21)
        self.feed(maker, range(24, 29, 4))
        maker.motion(30)
        self.feed(maker, range(32, 49, 4))
        self.assertEqual(len(self.done), 1)
        self.assertTrue(self.content(self.done[0][0]).endswith(frag(40)))
        self.assertNotIn(frag(44), self.content(self.done[0][0]))

    def test_before_zero(self):
        maker = self.make(before_s=0)
        self.feed(maker, range(4, 21, 4))
        maker.motion(21)
        self.feed(maker, [24])
        self.assertEqual(self.content(self.store.parts()[0]), HDR + frag(24))

    def test_split_no_gap(self):
        maker = self.make()
        events = [(t, 0, "m") for t in range(2, 701, 2)] + [(t, 1, "f") for t in range(4, 761, 4)]
        for t, _, kind in sorted(events):
            if kind == "m":
                maker.motion(t)
            else:
                maker.fragment(frag(t), t)
        self.assertEqual(len(self.done), 3)
        got = []
        for part, length, _ in self.done:
            self.assertLessEqual(length, 304)
            body = self.content(part)
            self.assertTrue(body.startswith(HDR))
            body = body[len(HDR):]
            got += [body[i:i + 7] for i in range(0, len(body), 7)]
        self.assertEqual(got, [frag(t) for t in range(4, 713, 4)])

    def test_header_mid_clip(self):
        maker = self.make()
        self.feed(maker, range(4, 21, 4))
        maker.motion(21)
        self.feed(maker, [24, 28])
        maker.header(b"NEW-HDR", 29)
        self.assertEqual(len(self.done), 1)
        self.assertFalse(maker.recording)
        maker.motion(30)
        self.feed(maker, [33])
        self.assertEqual(len(self.done), 1)
        parts = sorted(self.store.parts())
        self.assertEqual(len(parts), 2)
        self.assertEqual(self.content(parts[1]), b"NEW-HDR" + frag(33))

    def test_ring_bytes(self):
        maker = self.make(before_s=30, ring_max_bytes=2 * len(frag(0)))
        self.feed(maker, range(1, 11))
        maker.motion(10.5)
        self.feed(maker, [11])
        self.assertEqual(self.content(self.store.parts()[0]), HDR + frag(9) + frag(10) + frag(11))

    def test_no_motion_no_file(self):
        maker = self.make()
        self.feed(maker, range(4, 201, 4))
        self.assertEqual(self.opened, [])
        self.assertEqual(self.store.parts(), [])

    def test_stop_without_finish(self):
        maker = self.make()
        maker.motion(1)
        self.feed(maker, [4])
        self.assertTrue(maker.recording)
        maker.stop(finish=False)
        self.assertFalse(maker.recording)
        self.assertEqual(self.done, [])
        self.assertEqual(self.content(self.store.parts()[0]), HDR + frag(4))

    def test_part_dir_removed_before_open(self):
        maker = self.make()
        self.feed(maker, [4])
        maker.motion(5)
        orig = maker.new_part

        def racy(start):
            part = orig(start)
            part.parent.rmdir()  # the recorder's cleanup removed the empty day
            return part
        maker.new_part = racy
        self.feed(maker, [8])
        self.assertTrue(maker.recording)
        self.assertEqual(len(self.store.parts()), 1)

    def test_real_stream_two_sessions(self):
        both = b""
        for _ in range(2):
            both += subprocess.run(FFMPEG_STREAM, stdin=subprocess.DEVNULL, capture_output=True,
                                   timeout=120, check=True).stdout
        clock = iter(range(1_700_000_000, 1_700_001_000)).__next__
        maker = self.make()

        class Always:
            # motion in every fragment, so each session is one clip
            header = staticmethod(maker.header)

            @staticmethod
            def fragment(data, now):
                maker.motion(now)
                maker.fragment(data, now)

        clipmaker.pump(io.BytesIO(both).read, Always, clock=clock)
        maker.stop()
        self.assertEqual(len(self.done), 2)
        for part, length, thumb_at in self.done:
            final = clipmaker.finish(self.store, part, length, thumb_at)
            self.assertTrue(final and final.is_file())
            self.assertTrue(final.with_suffix(".jpg").is_file())
            self.assertFalse(part.exists())
            self.assertFalse(self.store.remux_path(part).exists())
            self.assertTrue(4 <= clipmaker.duration(final) <= 15)
            codec = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                    "stream=codec_name", "-of", "csv=p=0", str(final)],
                                   capture_output=True, text=True, timeout=60).stdout.strip()
            self.assertEqual(codec, "hevc")
        self.assertEqual(len(self.store.clips("cam", self.store.cameras()[0]["days"][0])), 2)

    def one_clip(self, cmd):
        """A real stream through pump -> ClipMaker -> finish, with motion all along: the final clip."""
        data = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, timeout=120, check=True).stdout
        maker = self.make()

        class Always:
            header = staticmethod(maker.header)

            @staticmethod
            def fragment(data, now):
                maker.motion(now)
                maker.fragment(data, now)

        clipmaker.pump(io.BytesIO(data).read, Always, clock=iter(range(1_700_000_000, 1_700_001_000)).__next__)
        maker.stop()
        self.assertEqual(len(self.done), 1)
        final = clipmaker.finish(self.store, *self.done[0])
        self.assertTrue(final and final.is_file())
        self.assertTrue(final.with_suffix(".jpg").is_file())
        self.assertTrue(4 <= clipmaker.duration(final) <= 15)
        return final

    def test_h264_camera(self):
        # many cameras send H.264: the clip must be made too, and play in any browser
        final = self.one_clip(H264_STREAM)
        self.assertEqual(probe(final, "stream=codec_name,codec_tag_string"), "h264,avc1")

    def test_h265_gets_browser_tag(self):
        # H.265 is tagged hvc1 in the final clip (Safari plays only that), whatever the camera sent
        final = self.one_clip(HEV1_STREAM)
        self.assertEqual(probe(final, "stream=codec_name,codec_tag_string"), "hevc,hvc1")

    def test_stale_motion_dropped_after_reconnect(self):
        # motion seen while the HD stream was down for minutes: no clip named back then
        maker = self.make()
        self.feed(maker, [4])
        maker.motion(5)
        maker.header(b"NEW-HDR", 300)
        self.feed(maker, [304, 308])
        self.assertEqual(self.opened, [])
        self.assertFalse(maker.recording)
        maker.motion(309)
        self.feed(maker, [312])
        self.assertEqual(self.opened, [309])

    def test_motion_through_reconnect_named_at_video_start(self):
        # motion that went on while the HD stream was down: the clip is named when its video starts
        maker = self.make()
        self.feed(maker, [4])
        for t in (5, 150, 299):
            maker.motion(t)
        maker.header(b"NEW-HDR", 300)
        self.feed(maker, [304])
        self.assertEqual(self.opened, [300])
        self.assertEqual(self.content(self.store.parts()[0]), b"NEW-HDR" + frag(304))

    def test_recover_cut_part(self):
        full = subprocess.run(FFMPEG_STREAM, stdin=subprocess.DEVNULL, capture_output=True,
                              timeout=120, check=True).stdout
        part = self.store.new_part("cam", 1_700_000_000)
        part.write_bytes(full[:int(len(full) * 0.7)])
        bad = self.store.new_part("cam", 1_700_000_100)
        bad.write_bytes(b"x" * 100)
        stale = self.store.remux_path(bad)
        stale.write_bytes(b"old")
        self.assertEqual(clipmaker.recover(self.store), 1)
        self.assertEqual(self.store.parts(), [])
        self.assertFalse(stale.exists())
        day = self.store.cameras()[0]["days"][0]
        rows = self.store.clips("cam", day)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["thumb"])


if __name__ == "__main__":
    unittest.main()
