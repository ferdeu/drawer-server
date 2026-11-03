"""Tests for termux/panel/motion.py. Run on the phone: bash tests/run-on-phone.sh -k MotionTest"""
import random
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "termux" / "panel"))
from motion import W, H, Detector, Obstruction, brightness, changed_share  # noqa: E402


def flat(v):
    return bytes([v]) * (W * H)


def ramp():
    return bytes(i % 231 for i in range(W * H))


def plus(frame, n):
    return bytes(min(255, v + n) for v in frame)


def square(x, y, size=40, bg=90, fg=230):
    rows = bytearray(flat(bg))
    for r in range(y, y + size):
        rows[r * W + x:r * W + x + size] = bytes([fg]) * size
    return bytes(rows)


def run(obs, start, seconds, share_pct, frame, step=0.5):
    """Looks every `step` s from start to start + seconds (included); returns (time, answer) of the last."""
    out = None
    for i in range(int(seconds / step) + 1):
        t = start + i * step
        out = (t, obs.update(t, (i % 100) < share_pct, frame))
    return out


class MotionTest(unittest.TestCase):
    def test_changed_share_exact(self):
        r = ramp()
        self.assertEqual(changed_share(r, plus(r, 25), 25), 1.0)
        self.assertEqual(changed_share(r, plus(r, 12), 25), 0.0)
        self.assertEqual(changed_share(plus(r, 25), r, 25), 1.0)
        self.assertEqual(changed_share(flat(100), flat(100), 25), 0.0)

    def test_changed_share_part(self):
        b = bytearray(flat(100))
        b[:576] = bytes([160]) * 576
        self.assertEqual(changed_share(flat(100), bytes(b), 25), 0.01)

    def looks(self, d, frames):
        return [d.look(f) for f in frames]

    def test_moving_square(self):
        frames = [square(x, 20) for x in (0, 20, 40, 60)]
        self.assertEqual(self.looks(Detector(5, 2), frames), [False, False, True, True])

    def test_sensitivity_changes_outcome(self):
        frames = [square(x, 20) for x in (0, 20, 40, 60)]
        self.assertEqual(self.looks(Detector(1, 2), frames), [False] * 4)

    def test_sensitivity_changed_in_place(self):
        d = Detector(1, 1)
        frames = [square(x, 20) for x in (0, 20, 40, 60)]
        self.assertEqual(self.looks(d, frames[:2]), [False, False])
        d.sensitivity = 5
        self.assertEqual(self.looks(d, frames[2:]), [True, True])

    def test_still_image(self):
        rnd = random.Random(1)
        d = Detector(5, 2)
        frames = [bytes(100 + rnd.randint(-3, 3) for _ in range(W * H)) for _ in range(20)]
        self.assertEqual(self.looks(d, frames), [False] * 20)

    def test_lighting_change(self):
        d = Detector(5, 2)
        self.assertEqual(self.looks(d, [flat(90), flat(150), flat(150)]), [False] * 3)
        got = self.looks(d, [square(x, 20, bg=150) for x in (0, 20, 40)])
        self.assertEqual(got, [False, True, True])  # first square already differs from the flat frame

    def test_lighting_change_is_not_motion(self):
        # one look is enough to count as motion, but a light jump must not
        self.assertEqual(self.looks(Detector(5, 1), [flat(90), flat(150)]), [False, False])
        # the jump resets the counter and the new frame is the reference
        d = Detector(5, 2)
        frames = [square(0, 20), square(20, 20), flat(200), square(0, 20, bg=200), square(20, 20, bg=200)]
        self.assertEqual(self.looks(d, frames), [False, False, False, False, True])

    def test_brightness(self):
        self.assertEqual(brightness(flat(0)), (0.0, 0.0))
        self.assertAlmostEqual(brightness(ramp())[0], 115, delta=1)

    def test_obstruction_moving(self):
        o = Obstruction()
        r = ramp()
        self.assertEqual(run(o, 0, 600, 60, r)[1], "moving")
        self.assertEqual(run(o, 600.5, 600, 40, r)[1], "moving")
        self.assertIsNone(run(o, 1201, 600, 20, r)[1])

    def test_obstruction_needs_full_window(self):
        self.assertIsNone(run(Obstruction(), 0, 30, 100, ramp())[1])

    def test_obstruction_flat(self):
        o = Obstruction()
        self.assertEqual(run(o, 0, 61, 0, flat(0), 1)[1], "flat")
        self.assertEqual(run(o, 62, 30, 0, ramp(), 1)[1], "flat")
        self.assertIsNone(run(o, 93, 61, 0, ramp(), 1)[1])

    def test_obstruction_reset(self):
        o = Obstruction()
        self.assertEqual(run(o, 0, 600, 100, ramp())[1], "moving")
        o.reset()
        self.assertIsNone(o.update(700, True, ramp()))

    def test_look_cost(self):
        d = Detector(5, 2)
        a, b = square(0, 20), square(20, 20)
        d.look(a)
        t0 = time.monotonic()
        for i in range(100):
            d.look(b if i % 2 == 0 else a)
        took = time.monotonic() - t0
        print(f"look cost: {took * 10:.2f} ms each")
        self.assertLess(took, 0.5)


if __name__ == "__main__":
    unittest.main()
