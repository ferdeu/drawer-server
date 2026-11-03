"""Tests for termux/panel/system.py. Run on the phone: bash tests/run-on-phone.sh -k SystemTest"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "termux" / "panel"))
import system  # noqa: E402


class SystemTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def policy(self, name, cur, top, cpus):
        d = self.root / name
        d.mkdir()
        if cur is not None:
            (d / "scaling_cur_freq").write_text(f"{cur}\n")
        (d / "cpuinfo_max_freq").write_text(f"{top}\n")
        (d / "related_cpus").write_text(" ".join(map(str, cpus)) + "\n")

    def test_cpu_pct_weighted(self):
        self.policy("policy0", 1000000, 2000000, [0, 1, 2, 3])
        self.policy("policy4", 2600000, 2600000, [4, 5, 6])
        self.policy("policy7", 650000, 2600000, [7])
        self.assertEqual(system.cpu_pct(self.root), 66)  # (4*50 + 3*100 + 1*25) / 8 = 65.6

    def test_cpu_pct_missing_policy(self):
        self.policy("policy0", 1000000, 2000000, [0, 1, 2, 3])
        self.policy("policy4", 2600000, 2600000, [4, 5, 6])
        self.policy("policy7", None, 2600000, [7])
        self.assertEqual(system.cpu_pct(self.root), 71)  # (4*50 + 3*100) / 7 = 71.4

    def test_cpu_pct_none(self):
        self.assertIsNone(system.cpu_pct(self.root))
        self.assertIsNone(system.cpu_pct(self.root / "missing"))

    def test_load_word(self):
        self.assertEqual(system.load_word(7.9, 8), "calm")
        self.assertEqual(system.load_word(8.0, 8), "busy")
        self.assertEqual(system.load_word(16.0, 8), "very_busy")

    def test_watts_microamps(self):
        self.assertEqual(system.battery_watts({"voltage": 3847, "current_average": -78000}), 0.3)

    def test_watts_small_current_is_microamps(self):
        # plugged in and holding the charge: a few mA, never read as amps
        self.assertEqual(system.battery_watts({"voltage": 4200, "current": 250000}), 1.1)
        self.assertIsNone(system.battery_watts({"voltage": 4200, "current": 3000}))  # 0.01 W: too small to show

    def test_watts_missing(self):
        self.assertIsNone(system.battery_watts({}))
        self.assertIsNone(system.battery_watts({"voltage": 3800, "current": 0}))

    def proc(self, pid, ppid, name, args, ticks, rss_kb=1000, stat=True):
        d = self.root / str(pid)
        d.mkdir()
        (d / "cmdline").write_bytes("\0".join(args).encode() + b"\0")
        if stat:  # fields after the name: state ppid pgrp session tty tpgid flags minflt cminflt majflt cmajflt utime stime
            (d / "stat").write_text(f"{pid} ({name}) S {ppid} 1 1 0 -1 0 0 0 0 0 {ticks - ticks // 2} {ticks // 2} 0 0\n")
        (d / "status").write_text(f"Name:\t{name}\nVmRSS:\t   {rss_kb} kB\n")

    def test_child_inherits_service(self):
        self.proc(10, 1, "python", ["python", "/home/recorder.py"], 100, 5000)
        self.proc(11, 10, "ffmpeg", ["ffmpeg", "-i", "x"], 300, 20000)
        self.proc(12, 1, "sleep", ["sleep", "300"], 7)
        (self.root / "self").mkdir()  # not a pid
        table = system.proc_table(self.root)
        self.assertEqual(table[10], (1, "Recorder", 100, 5000))
        self.assertEqual(system.by_service(table), {"Recorder": (400, 25000), "Other": (7, 1000)})

    def test_panel_stills_count_as_cameras(self):
        self.proc(10, 1, "python", ["python", "/home/panel/panel.py"], 100, 50000)
        self.proc(11, 10, "ffmpeg", ["ffmpeg", "-i", "rtsp://127.0.0.1:8554/cam1", "-update", "1", "-y",
                                     "/home/.cache/drawer-server/cams/1.jpg"], 300, 55000)
        self.assertEqual(system.by_service(system.proc_table(self.root)), {"Panel": (100, 50000), "Cameras": (300, 55000)})

    def test_usage_share_of_phone(self):
        self.proc(10, 1, "go2rtc", ["/home/go2rtc/go2rtc"], 40, 30000)
        before = system.proc_table(self.root)
        after = {10: (1, "Cameras", 200, 30720)}
        self.assertEqual(system.usage(before, after, 2, 8), [{"name": "Cameras", "cpu_pct": 10.0, "mem_mb": 30}])

    def test_proc_vanishes(self):
        self.proc(10, 1, "sshd", ["sshd"], 5, stat=False)
        self.assertEqual(system.proc_table(self.root), {})

    def test_pid_reused(self):
        before = {10: (1, "Panel", 500, 1024)}
        after = {10: (1, "Panel", 20, 1024), 11: (1, "SSH", 10, 2048)}  # 11 is new: no delta yet
        self.assertEqual(system.usage(before, after, 2, 8),
                         [{"name": "SSH", "cpu_pct": 0.0, "mem_mb": 2}, {"name": "Panel", "cpu_pct": 0.0, "mem_mb": 1}])

    def test_name_with_spaces(self):
        self.proc(10, 1, "my proc) x", ["luantiserver"], 50)
        self.assertEqual(system.proc_table(self.root)[10], (1, "Luanti", 50, 1000))

    def test_sampler_snapshot(self):
        self.policy("policy0", 1000000, 2000000, [0, 1])
        times = iter([0.0, 2.0])
        tables = iter([{10: (1, "Panel", 0, 2048)}, {10: (1, "Panel", 100, 2048)}])
        s = system.Sampler(cpufreq=self.root, ncpu=2, clock=lambda: next(times), table=lambda: next(tables))
        s.sample()
        s.sample()
        self.assertEqual(s.snapshot(), {"cpu_pct": 50, "ncpu": 2, "services": [{"name": "Panel", "cpu_pct": 25.0, "mem_mb": 2}]})

    def test_sampler_empty(self):
        s = system.Sampler(cpufreq=self.root / "none", ncpu=2)
        self.assertEqual(s.snapshot(), {"cpu_pct": None, "ncpu": 2, "services": []})

    @unittest.skipIf(sys.platform == "win32", "sysinfo() is Linux and Android only")
    def test_sysinfo_shape(self):
        s = system.sysinfo()
        self.assertGreater(s["uptime_s"], 0)
        self.assertEqual(len(s["load"]), 3)


if __name__ == "__main__":
    unittest.main()
