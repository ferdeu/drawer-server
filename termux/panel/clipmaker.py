"""Turns the HD fragment stream of one camera into clips on disk (see clips.py for the layout).
read_box/pump split ffmpeg's fragmented mp4 into pieces; ClipMaker decides what goes into a clip
(a few seconds before the motion, until a few seconds after); finish/recover make the .part file
into the final +faststart .mp4 with a thumbnail. Standard library plus Termux ffmpeg/ffprobe.
"""
import os
import signal
import struct
import subprocess
import threading
import time
from pathlib import Path

import clips

REMUX = ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", "{part}", "-c", "copy",
         "-movflags", "+faststart", "-f", "mp4", "{out}"]
HVC1 = ["-tag:v", "hvc1"]  # H.265 only (an H.264 clip can't take it): the tag Safari needs to play it
THUMB = ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-ss", "{at:.1f}", "-i", "{clip}", "-frames:v", "1",
         "-vf", "scale=320:-2", "-q:v", "5", "{out}"]
PROBE = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", "{path}"]
CODEC = ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name",
         "-of", "csv=p=0", "{path}"]
TIMEOUT_S = 120
MAX_BOX = 64_000_000  # a real fragment is about 0.5 MB; a bigger size is garbage
RING_SLACK_S = 15  # keyframes can be far apart; keep this much more than "before" in the ring


# --- reading the stream ---

def _read_exact(read, n):
    """n bytes, or None if the stream ends first (pipes may return short reads)."""
    chunks = []
    while n > 0:
        chunk = read(min(n, 1 << 20))
        if not chunk:
            return None
        chunks.append(chunk)
        n -= len(chunk)
    return b"".join(chunks)


def read_box(read):
    """One top-level box as (type, whole box bytes); None at the end of the stream or on a short read."""
    head = _read_exact(read, 8)
    if head is None:
        return None
    size, kind = struct.unpack(">I4s", head)
    hlen = 8
    if size == 1:
        ext = _read_exact(read, 8)
        if ext is None:
            return None
        head += ext
        size, hlen = struct.unpack(">Q", ext)[0], 16
    if size == 0 or size < hlen:
        raise ValueError(f"bad box size {size}")
    if size > MAX_BOX:
        raise ValueError(f"box too big: {size}")
    body = _read_exact(read, size - hlen)
    if body is None:
        return None
    return kind.decode("latin-1"), head + body


def pump(read, maker, clock=time.time):
    """Feed boxes from read() to the maker until the stream ends."""
    ftyp, moof = b"", None
    while True:
        box = read_box(read)
        if box is None:
            return
        kind, data = box
        if kind == "ftyp":
            ftyp = data
        elif kind == "moov":
            maker.header(ftyp + data, clock())
        elif kind == "moof":
            moof = data
        elif kind == "mdat" and moof is not None:
            maker.fragment(moof + data, clock())
            moof = None


# --- deciding what goes into a clip ---

class _Clip:
    def __init__(self, fh, part, start, thumb_at):
        self.fh, self.part, self.start, self.thumb_at = fh, part, start, thumb_at
        self.end = start


class ClipMaker:
    def __init__(self, new_part, finished, before_s, after_s, split_s=300, ring_max_bytes=8_000_000):
        self.new_part, self.finished = new_part, finished
        self.before_s, self.after_s, self.split_s = before_s, after_s, split_s
        self.ring_max_bytes = ring_max_bytes
        self.lock = threading.Lock()
        self._header = None
        self._last_end = 0.0
        self._ring = []  # (start, end, data)
        self._first_motion = None  # motion waiting for a clip
        self._last_motion = None
        self._clip = None
        self._continue = False  # a split clip is followed by one with no gap

    @property
    def recording(self):
        return self._clip is not None

    def header(self, data, now):
        """A new ffmpeg session starts: end the open clip, forget the ring."""
        with self.lock:
            done = []
            self._end(done)
            self._header, self._last_end, self._ring, self._continue = data, now, [], False
        self._report(done)

    def fragment(self, data, now):
        with self.lock:
            done = []
            if self._header is not None:
                self._add(data, now, done)
        self._report(done)

    def motion(self, now):
        with self.lock:
            if self._clip is None and self._first_motion is None:
                self._first_motion = now
            self._last_motion = now

    def stop(self, finish=True):
        with self.lock:
            done = []
            self._end(done, finish)
            self._first_motion, self._continue = None, False
        self._report(done)

    def _report(self, done):
        for args in done:  # outside the lock: finished may call back in
            self.finished(*args)

    def _add(self, data, now, done):
        start, self._last_end = self._last_end, now
        if self._clip is None:
            if self._first_motion is not None and self._last_motion + self.after_s < start:
                self._first_motion = None  # seen while the HD stream was down, and over long ago
            if self._first_motion is None and not self._continue:
                self._ring_add(start, now, data)
                return
            if self._continue:
                items, motion_at = [(start, now, data)], start
            else:
                motion_at = self._first_motion
                items = [r for r in self._ring if r[1] > motion_at - self.before_s] + [(start, now, data)]
                motion_at = max(motion_at, items[0][0])  # motion from before a reconnect: named when the video starts
            self._first_motion, self._continue, self._ring = None, False, []
            if not self._open(items, motion_at, done):
                return
        else:
            try:
                self._clip.fh.write(data)
                self._clip.fh.flush()
            except OSError:
                self._end(done)  # keep what was written; finish() saves it or discards it
                return
            self._clip.end = now
        last = self._last_motion
        if last is not None and now >= last + self.after_s:
            self._end(done)
        elif now - self._clip.start >= self.split_s:
            self._end(done)
            self._continue = True

    def _open(self, items, motion_at, done):
        part = Path(self.new_part(motion_at))
        try:
            part.parent.mkdir(parents=True, exist_ok=True)  # the recorder may have just removed an empty day
            fh = open(part, "wb")
        except OSError:
            return False
        self._clip = clip = _Clip(fh, part, items[0][0], max(0.0, motion_at - items[0][0]))
        try:
            fh.write(self._header)
            for _, end, data in items:
                fh.write(data)
                clip.end = end
            fh.flush()
        except OSError:
            self._end(done)  # the part exists: report it so it is saved or discarded, never orphaned
            return False
        return True

    def _end(self, done, finish=True):
        clip, self._clip = self._clip, None
        if clip is None:
            return
        try:
            clip.fh.close()
        except OSError:
            pass
        if finish:
            done.append((clip.part, clip.end - clip.start, clip.thumb_at))

    def _ring_add(self, start, now, data):
        self._ring.append((start, now, data))
        horizon = now - self.before_s - RING_SLACK_S
        while self._ring and self._ring[0][1] <= horizon:
            self._ring.pop(0)
        while self._ring and sum(len(r[2]) for r in self._ring) > self.ring_max_bytes:
            self._ring.pop(0)


# --- ffmpeg helpers ---

def _run(cmd, **fields):
    """Run a command in its own process group: (return code, stdout), or (None, "") on timeout."""
    argv = [a.format(**fields) for a in cmd]
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, start_new_session=True)
    except OSError:
        return None, ""
    try:
        out, _ = proc.communicate(timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.communicate()
        return None, ""
    return proc.returncode, out.decode("utf-8", "replace")


def codec(path):
    """The video codec's name ("hevc", "h264"...), or None if ffprobe can't tell."""
    code, out = _run(CODEC, path=str(path))
    return (out.strip() or None) if code == 0 else None


def remux(part, out):
    cmd = REMUX
    if codec(part) == "hevc":
        i = REMUX.index("-movflags")
        cmd = REMUX[:i] + HVC1 + REMUX[i:]
    code, _ = _run(cmd, part=str(part), out=str(out))
    return code == 0 and Path(out).is_file()


def thumbnail(clip, at_s, out):
    code, _ = _run(THUMB, clip=str(clip), at=at_s, out=str(out))
    return code == 0 and Path(out).is_file()


def duration(path):
    code, out = _run(PROBE, path=str(path))
    if code != 0:
        return None
    try:
        value = float(out.strip())
    except ValueError:
        return None
    return value if 0 < value < 1e6 else None


def finish(store, part, length_s, thumb_at_s):
    """.part -> final +faststart .mp4 with a thumbnail; the part goes away. None if the remux failed."""
    tmp = store.remux_path(part)
    final, thumb = store.final_paths(part, length_s)
    if not remux(part, tmp):
        store.discard(part)
        store.discard(tmp)
        return None
    try:
        os.replace(tmp, final)
    except OSError:
        store.discard(part)
        store.discard(tmp)
        return None
    thumbnail(final, min(thumb_at_s, max(0.0, length_s - 1)), thumb)  # a missing thumbnail is no reason to lose the clip
    store.discard(part)
    return final


def recover(store):
    """After a crash or power cut: save what the leftover parts hold. Returns how many clips."""
    for folder, day, name, _, _ in store._walk((clips.REMUX,)):
        store.discard(store.root / folder / day / name)
    saved = 0
    for part in store.parts():
        length = duration(part)
        if length is not None and finish(store, part, length, 0.0):
            saved += 1
        else:
            store.discard(part)
    return saved
