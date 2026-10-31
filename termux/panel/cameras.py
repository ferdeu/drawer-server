"""Camera stills for the status panel.

One ffmpeg per camera, started when someone asks for its picture and stopped when nobody has asked
for a while. It reads the camera's small stream through go2rtc (scripts/11-cameras.sh) and decodes
only full frames, so a new still lands every ~2.5 s for little CPU.
"""
import ipaddress
import os
import signal
import subprocess
import threading
import time
from pathlib import Path

TAILSCALE = ipaddress.ip_network("100.64.0.0/10")


def load_names(path):
    """Camera names, one per line, in go2rtc order (cam1, cam2, ...)."""
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text().splitlines() if line.strip()]


def is_home(ip):
    """True when the request comes from the home network (Tailscale addresses are 'away')."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if getattr(addr, "ipv4_mapped", None):
        addr = addr.ipv4_mapped
    return (addr.is_private or addr.is_loopback) and addr not in TAILSCALE


def default_url(n):
    return f"rtsp://127.0.0.1:8554/cam{n}"  # go2rtc's RTSP, only on this phone


def ffmpeg_cmd(url, out):
    # -timeout: give up on a stream that stalls (microseconds); -atomic_writing: never a half-written still
    return ["ffmpeg", "-nostdin", "-loglevel", "error", "-skip_frame", "nokey", "-rtsp_transport", "tcp",
            "-timeout", "10000000", "-i", url, "-fps_mode", "passthrough", "-q:v", "5",
            "-update", "1", "-atomic_writing", "1", "-y", str(out)]


def kill_leftovers(folder):
    """Stop ffmpeg processes a previous panel left writing into the stills folder."""
    subprocess.run(["pkill", "-f", f"ffmpeg .*{folder}/"], capture_output=True)


def _stop(proc):
    # kill the whole group: a hung ffmpeg must not pile up (the panel once left 1921 termux-api behind)
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
    except ProcessLookupError:
        pass


class Stills:
    def __init__(self, count, folder, url_for=default_url, idle_s=30, stale_s=15, retry_s=10, cmd=ffmpeg_cmd):
        self.count, self.folder, self.url_for, self.cmd = count, Path(folder), url_for, cmd
        self.idle_s, self.stale_s, self.retry_s = idle_s, stale_s, retry_s
        self.procs, self.asked, self.started = {}, {}, {}
        self.lock = threading.Lock()
        self.folder.mkdir(parents=True, exist_ok=True)

    def path(self, n):
        return self.folder / f"cam{n}.jpg"

    def age(self, n, now):
        try:
            return now - self.path(n).stat().st_mtime
        except OSError:
            return float("inf")

    def get(self, n):
        """Latest still of camera n (1-based) as JPEG bytes, or None while there's no fresh one."""
        if not 1 <= n <= self.count:
            raise IndexError(n)
        now = time.time()
        stuck = None
        with self.lock:
            self.asked[n] = now
            proc = self.procs.get(n)
            if proc and proc.poll() is not None:  # ffmpeg died (camera or go2rtc down)
                del self.procs[n]
                proc = None
            elif proc and self.age(n, now) > self.stale_s and now - self.started.get(n, 0) >= self.stale_s + self.retry_s:
                stuck = self.procs.pop(n)  # alive but no new stills: replace it
                proc = None
            if not proc and now - self.started.get(n, 0) >= self.retry_s:
                self.started[n] = now
                self.procs[n] = subprocess.Popen(self.cmd(self.url_for(n), self.path(n)), start_new_session=True,
                                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                                 stderr=subprocess.DEVNULL)
        if stuck:
            _stop(stuck)
        if self.age(n, now) > self.stale_s:
            return None
        try:
            return self.path(n).read_bytes()
        except OSError:
            return None

    def reap(self):
        """Stop the cameras nobody looked at for idle_s seconds."""
        now = time.time()
        with self.lock:
            idle = [n for n in self.procs if now - self.asked.get(n, 0) > self.idle_s]
            procs = [self.procs.pop(n) for n in idle]
        for proc in procs:
            _stop(proc)

    def stop_all(self):
        with self.lock:
            procs = list(self.procs.values())
            self.procs.clear()
        for proc in procs:
            _stop(proc)

    def start_reaper(self):
        def loop():
            while True:
                time.sleep(5)
                self.reap()
        threading.Thread(target=loop, daemon=True).start()
