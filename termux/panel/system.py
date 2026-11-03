"""How hard the phone works, from what Android 15 still lets an app read. Used by panel.py.

Android refuses /proc/stat, /proc/loadavg, /proc/uptime and the thermal sensors to apps like Termux,
so there is no real CPU use %. Still readable: each core cluster's clock (cpufreq), the sysinfo()
syscall (uptime and load) and our own processes in /proc.
"""
import collections
import ctypes
import os
import threading
import time
from pathlib import Path

CPUFREQ = Path("/sys/devices/system/cpu/cpufreq")
PROC = Path("/proc")
LOAD_BUSY = 1.0  # load per core from which the phone counts as busy
LOAD_VERY = 2.0  # ...and as very busy
CPU_SAMPLE_S = 2  # seconds between samples
CPU_WINDOW = 5    # samples averaged: the figure covers the last ~10 s
# which of our services a process belongs to, by its name or command line; first match wins.
# A process with no match (ffmpeg, a shell, proot) belongs to its nearest ancestor's service.
# The panel's camera stills (an ffmpeg writing to ~/.cache/drawer-server/cams/) count as Cameras.
SERVICE_RULES = [("drawer-server/cams/", "Cameras"), ("panel.py", "Panel"), ("recorder.py", "Recorder"), ("go2rtc", "Cameras"),
                 ("syncthing", "Syncthing"), ("luanti", "Luanti"), ("sshd", "SSH"), ("nextdns", "NextDNS")]


def sysinfo():
    """{"uptime_s", "load": [1, 5, 15 min]} from libc's sysinfo(), or None if it can't be called."""
    buf = ctypes.create_string_buffer(256)  # struct sysinfo is ~112 bytes on 64-bit
    try:
        if ctypes.CDLL(None, use_errno=True).sysinfo(buf) != 0:
            return None
    except (OSError, AttributeError, TypeError):
        return None
    words = (ctypes.c_long * 4).from_buffer(buf)  # long uptime; unsigned long loads[3]
    return {"uptime_s": int(words[0]), "load": [round((w & (2 ** 64 - 1)) / 65536, 2) for w in words[1:]]}


def _read_int(path):
    try:
        return int(path.read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def cpu_pct(root=CPUFREQ):
    """Clock now against top clock, 0..100, averaged over the clusters and weighted by their cores."""
    total = weight = 0
    try:
        policies = sorted(root.glob("policy*"))
    except OSError:
        return None
    for p in policies:
        cur, top = _read_int(p / "scaling_cur_freq"), _read_int(p / "cpuinfo_max_freq")
        if not cur or not top:
            continue
        try:
            cores = len((p / "related_cpus").read_text().split()) or 1
        except OSError:
            cores = 1
        total += min(cur / top, 1) * cores
        weight += cores
    return round(total * 100 / weight) if weight else None


def load_word(load1, ncpu):
    per_core = load1 / max(ncpu, 1)
    return "very_busy" if per_core >= LOAD_VERY else "busy" if per_core >= LOAD_BUSY else "calm"


def battery_watts(b):
    """Watts going in or out of the battery, from termux-battery-status: voltage in mV, current in µA
    (Android's unit; guessing mA from small values misread a phone holding its charge as 12 W).
    Under 0.05 W it is None: too small to show, and what a phone that reports mA would give."""
    volts, amps = b.get("voltage"), b.get("current_average") or b.get("current")
    if not volts or not amps:
        return None
    watts = volts / 1000 * abs(amps) / 1_000_000
    return round(watts, 1) if watts >= 0.05 else None


def _service(name, cmdline):
    for needle, service in SERVICE_RULES:
        if needle in name or needle in cmdline:
            return service
    return ""


def proc_table(proc=PROC):
    """Our own processes: pid -> (ppid, service or "", CPU ticks used so far, RSS in kB).
    Other apps' processes can't be read and are left out; so is a process that exits meanwhile."""
    table = {}
    try:
        pids = [p for p in proc.iterdir() if p.name.isdigit()]
    except OSError:
        return table
    for p in pids:
        try:
            stat = (p / "stat").read_text()
            name, rest = stat[stat.index("(") + 1:stat.rindex(")")], stat[stat.rindex(")") + 2:].split()
            cmdline = (p / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
            rss = next((int(line.split()[1]) for line in (p / "status").read_text().splitlines()
                        if line.startswith("VmRSS:")), 0)
            table[int(p.name)] = (int(rest[1]), _service(name, cmdline), int(rest[11]) + int(rest[12]), rss)
        except (OSError, ValueError, IndexError):
            continue
    return table


def _resolve(table):
    """pid -> service, a process without a rule taking its nearest ancestor's."""
    out = {}
    for pid in table:
        seen, cur = set(), pid
        while cur in table and cur not in seen and not table[cur][1]:
            seen.add(cur)
            cur = table[cur][0]
        out[pid] = table[cur][1] if cur in table and table[cur][1] else "Other"
    return out


def by_service(table):
    """service -> (CPU ticks, RSS kB) summed over its processes."""
    sums = {}
    for pid, service in _resolve(table).items():
        ticks, rss = sums.get(service, (0, 0))
        sums[service] = (ticks + table[pid][2], rss + table[pid][3])
    return sums


def usage(before, after, seconds, ncpu, hz=100):
    """[{"name", "cpu_pct", "mem_mb"}] per service, busiest first. CPU % is a share of the whole phone
    (all cores = 100%). A pid new since `before`, or reused (fewer ticks), adds no CPU this round."""
    cpu, mem = {}, {}
    for pid, service in _resolve(after).items():
        old = before.get(pid)
        delta = after[pid][2] - old[2] if old and after[pid][2] >= old[2] else 0
        cpu[service] = cpu.get(service, 0) + delta
        mem[service] = mem.get(service, 0) + after[pid][3]
    rows = [{"name": s, "cpu_pct": round(cpu[s] * 100 / (hz * max(seconds, 0.001) * max(ncpu, 1)), 1),
             "mem_mb": mem[s] // 1024} for s in cpu]
    return sorted(rows, key=lambda r: (r["cpu_pct"], r["mem_mb"]), reverse=True)


class Sampler(threading.Thread):
    """Samples the CPU clock and our processes every CPU_SAMPLE_S, keeping the last CPU_WINDOW,
    so the status page only reads a ready result."""

    def __init__(self, cpufreq=CPUFREQ, ncpu=None, clock=time.monotonic, table=proc_table):
        super().__init__(daemon=True)
        self.cpufreq, self.ncpu = cpufreq, ncpu or os.cpu_count() or 1
        self.clock, self.table = clock, table
        self.samples = collections.deque(maxlen=CPU_WINDOW)
        self.lock = threading.Lock()

    def sample(self):
        entry = (self.clock(), cpu_pct(self.cpufreq), self.table())
        with self.lock:
            self.samples.append(entry)

    def run(self):
        while True:
            try:
                self.sample()
            except Exception:  # one bad read never stops the sampling
                pass
            time.sleep(CPU_SAMPLE_S)

    def snapshot(self):
        with self.lock:
            samples = list(self.samples)
        pcts = [p for _, p, _ in samples if p is not None]
        services = usage(samples[0][2], samples[-1][2], samples[-1][0] - samples[0][0], self.ncpu) \
            if len(samples) >= 2 else []
        return {"cpu_pct": round(sum(pcts) / len(pcts)) if pcts else None, "ncpu": self.ncpu, "services": services}
