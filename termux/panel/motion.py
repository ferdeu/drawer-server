"""Motion detection on small gray frames (320x180, one byte per pixel). Standard library only."""
from collections import deque

W, H = 320, 180

# Sensitivity level -> (gray levels a pixel must change, % of the image that must change).
# Starting values, to tune on real footage.
SENSITIVITY = {1: (40, 3.0), 2: (36, 2.0), 3: (32, 1.3), 4: (28, 0.8), 5: (25, 0.5),
               6: (22, 0.35), 7: (19, 0.25), 8: (16, 0.18), 9: (13, 0.12), 10: (10, 0.08)}
LIGHTING_SHARE = 0.6   # more than this share changed in one look = lights, not motion
FLAT_SPREAD = 6        # brightness spread under this = covered or blank picture
DARK_MEAN = 10         # mean brightness under this = dark picture

NONZERO = bytes([0] + [1] * 255)
_tables_cache = {}


def _tables(levels):
    t = _tables_cache.get(levels)
    if t is None:
        t = _tables_cache[levels] = (
            bytes(v // levels for v in range(256)),
            bytes(min(255, (v + levels // 2) // levels) for v in range(256)))
    return t


def _differs(qa, qb, n):  # 1 where the bucket changed, else 0
    x = int.from_bytes(qa) ^ int.from_bytes(qb)
    return int.from_bytes(x.to_bytes(n).translate(NONZERO))


def _quant(frame, levels):
    q1, q2 = _tables(levels)
    return frame.translate(q1), frame.translate(q2)


def _share(qa, qb, n):
    # A pixel counts only if it changed bucket in both quantizations: a change of `levels`
    # or more always does, a change of `levels // 2` or less never does.
    both = _differs(qa[0], qb[0], n) & _differs(qa[1], qb[1], n)
    return both.to_bytes(n).count(1) / n


def changed_share(a, b, levels):
    """Share (0-1) of pixels that changed between two frames."""
    return _share(_quant(a, levels), _quant(b, levels), len(a))


class Detector:
    def __init__(self, sensitivity, looks_needed):
        self.sensitivity = sensitivity      # both may be changed between looks
        self.looks_needed = looks_needed
        self._frame = None                  # last frame
        self._ref = None                    # (levels, its quantized pair)
        self._count = 0                     # looks in a row that saw motion

    def look(self, frame):
        """True when this look and the looks_needed - 1 before it all saw motion."""
        levels, pct = SENSITIVITY[self.sensitivity]
        q = _quant(frame, levels)
        last, self._frame = self._frame, frame
        if last is None:
            self._ref = (levels, q)
            return False
        if self._ref[0] != levels:          # sensitivity changed: quantize the last frame again
            self._ref = (levels, _quant(last, levels))
        share = _share(self._ref[1], q, len(frame))
        self._ref = (levels, q)
        if share > LIGHTING_SHARE:
            self._count = 0
            return False
        self._count = self._count + 1 if share * 100 >= pct else 0
        return self._count >= self.looks_needed


def brightness(frame):
    """Mean and standard deviation of every 16th pixel."""
    s = frame[::16]
    mean = sum(s) / len(s)
    var = sum(map(int.__mul__, s, s)) / len(s) - mean * mean
    return mean, max(var, 0.0) ** 0.5


class Obstruction:
    """Tells when a camera is covered: motion nearly all the time, or a flat/dark picture."""

    def __init__(self, window_s=600, on_share=0.5, off_share=0.25, flat_s=60):
        self.window_s, self.on_share, self.off_share, self.flat_s = window_s, on_share, off_share, flat_s
        self.reset()

    def reset(self):
        self._looks = deque()       # (time, motion) inside the window
        self._start = None
        self._moving = False
        self._bad_since = None      # start of the current run of flat frames
        self._good_since = None     # start of the current run of normal frames
        self._flat = False

    def update(self, now, motion, frame):
        """None, "moving" or "flat" (flat wins when both apply)."""
        if self._start is None:
            self._start = now
        self._looks.append((now, motion))
        while self._looks[0][0] <= now - self.window_s:
            self._looks.popleft()
        if now - self._start >= self.window_s:
            share = sum(m for _, m in self._looks) / len(self._looks)
            if share > self.on_share:
                self._moving = True
            elif share < self.off_share:
                self._moving = False
        mean, spread = brightness(frame)
        if spread < FLAT_SPREAD or mean < DARK_MEAN:
            self._good_since = None
            if self._bad_since is None:
                self._bad_since = now
            if now - self._bad_since >= self.flat_s:
                self._flat = True
        else:
            self._bad_since = None
            if self._good_since is None:
                self._good_since = now
            if now - self._good_since >= self.flat_s:
                self._flat = False
        return "flat" if self._flat else "moving" if self._moving else None
