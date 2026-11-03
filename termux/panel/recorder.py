"""Camera motion recorder (step 12): its own process, started on boot by ~/.termux/boot/70-recorder.sh.

Per recorded camera, two ffmpeg children read go2rtc on this phone: the small stream as gray frames
for motion detection (plus the panel's still, from the same decode), and the HD stream as fragmented
MP4, kept a few seconds in memory and written as a clip when something moves (clipmaker.py).
State for the panel goes to ~/.cache/drawer-server/recorder.json. Standard library plus Termux ffmpeg.
"""
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import cameras
import clipmaker
import motion
import settings
from clips import ClipStore

HOME = Path.home()
CONFIG = HOME / ".config" / "drawer-server"
DATA = HOME / ".cache" / "drawer-server"
RECORDINGS = HOME / "recordings"
LOG = DATA / "recorder.log"
LOG_MAX = 1_000_000

TAG = "drawer-recorder"
LEFTOVER_PATTERN = "-user_agent drawer-recorder"  # in every recorder ffmpeg, so leftovers can be found

RELOAD_S = 30    # re-read the settings files
ENFORCE_S = 300  # check the recordings cap and the free-space floor
STATE_S = 10     # write the state file
LONG_RUN_S = 60  # an ffmpeg that ran this long starts the restart wait from the beginning again

_log_lock = threading.Lock()


def log(msg):
    """One time-stamped line in recorder.log (one old copy kept as recorder.log.1). Never raises."""
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n"
    with _log_lock:
        try:
            if LOG.exists() and LOG.stat().st_size + len(line.encode()) >= LOG_MAX:
                os.replace(LOG, LOG.with_name(LOG.name + ".1"))
            with open(LOG, "a") as f:
                f.write(line)
        except OSError:
            pass


def motion_cmd(n, check, still):
    fast = check == "fast"
    graph = (f"[0:v]split=2[m][s];[m]{'fps=2,' if fast else ''}scale=320:180,format=gray[mo];"
             "[s]select=key[so]")  # one decode: frames for detection, and the panel's still
    return ["ffmpeg", "-nostdin", "-loglevel", "error", *([] if fast else ["-skip_frame", "nokey"]),
            "-rtsp_transport", "tcp", "-timeout", "10000000", "-user_agent", TAG,
            "-i", f"rtsp://127.0.0.1:8554/cam{n}", "-filter_complex", graph,
            "-map", "[mo]", "-fps_mode", "passthrough", "-f", "rawvideo", "pipe:1",
            "-map", "[so]", "-fps_mode", "passthrough", "-q:v", "5", "-update", "1", "-atomic_writing", "1",
            "-y", str(still)]


def record_cmd(n):
    return ["ffmpeg", "-nostdin", "-loglevel", "error", "-rtsp_transport", "tcp", "-timeout", "10000000",
            "-user_agent", TAG, "-i", f"rtsp://127.0.0.1:8554/cam{n}_hd", "-an", "-c", "copy",
            "-f", "mp4", "-movflags", "frag_keyframe+empty_moov+default_base_moof", "pipe:1"]


def _signal_group(proc, sig):
    try:
        os.killpg(proc.pid, sig)
    except (ProcessLookupError, PermissionError):
        pass


class _Source:
    """One ffmpeg kept running in its own thread: start it, read until it ends, stop it, wait, again.
    The wait starts at backoff[0] and doubles up to backoff[1]; it starts over after a long run.
    """

    def __init__(self, who, cmd, read, ended, backoff):
        self.who, self.cmd, self.read, self.ended, self.backoff = who, cmd, read, ended, backoff
        self.lock = threading.Lock()
        self.proc = None
        self.closing = threading.Event()
        self.wake = threading.Event()
        self.again = False  # restart at once, with a fresh command (settings changed)
        self.thread = threading.Thread(target=self._loop, name=who, daemon=True)

    def start(self):
        self.thread.start()

    def restart(self):
        self.again = True
        self.wake.set()
        self._signal(signal.SIGTERM)

    def close(self):
        """Ask the thread to end (the ffmpeg gets SIGTERM); join() waits for it."""
        self.closing.set()
        self.wake.set()
        self._signal(signal.SIGTERM)

    def kill(self):
        self._signal(signal.SIGKILL)

    def _signal(self, sig):
        with self.lock:
            if self.proc is not None and self.proc.returncode is None:
                _signal_group(self.proc, sig)

    def _loop(self):
        wait = self.backoff[0]
        while not self.closing.is_set():
            began = time.monotonic()
            try:
                why = self._run_once()
            except Exception as e:  # never die silently
                why = f"failed ({type(e).__name__}: {e})"
            if self.closing.is_set():
                return
            if self.again:
                wait = self.backoff[0]
                log(f"{self.who}: restarting with new settings")
                continue
            if time.monotonic() - began > LONG_RUN_S:
                wait = self.backoff[0]
            log(f"{self.who}: {why}; starting again in {wait:g} s")
            self.wake.wait(wait)
            self.wake.clear()
            wait = min(wait * 2, self.backoff[1])

    def _run_once(self):
        self.again = False
        try:
            proc = subprocess.Popen(self.cmd(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, start_new_session=True)
        except (OSError, ValueError) as e:
            return f"couldn't start ffmpeg ({type(e).__name__})"
        with self.lock:
            self.proc = proc
            skip = self.closing.is_set() or self.again  # close()/restart() came before it had a proc
        why = "stopped"
        try:
            if not skip:
                self.read(proc.stdout)
                why = "stream ended"
        except Exception as e:  # a corrupt box, a full disk...
            why = f"failed ({type(e).__name__}: {e})"
        finally:
            try:
                self.ended()
            except Exception as e:
                log(f"{self.who}: cleanup failed ({type(e).__name__}: {e})")
            try:
                proc.stdout.close()  # first, so an ffmpeg writing its trailer to the pipe can't hang
            except OSError:
                pass
            cameras._stop(proc)
            with self.lock:
                self.proc = None
        return why


def _read_exact(stream, n):
    """n bytes, or None if the stream ends first."""
    chunks = []
    while n > 0:
        chunk = stream.read(n)
        if not chunk:
            return None
        chunks.append(chunk)
        n -= len(chunk)
    return b"".join(chunks)


def _when(t):
    return None if t is None else int(t)


class Camera:
    """One recorded camera: a motion source and a record source, each kept running by a _Source."""

    def __init__(self, n, name, settings, store, finisher, stills, allow_new, motion_cmd=motion_cmd,
                 record_cmd=record_cmd, backoff=(10, 60), offline_s=30, clock=time.time):
        self.n, self.name, self.settings, self.store = n, name, settings, store
        self.allow_new, self.offline_s, self.clock = allow_new, offline_s, clock
        self.still = Path(stills) / f"cam{n}.jpg"
        self.lock = threading.Lock()
        self.detector = motion.Detector(settings.sensitivity, self._looks(settings))
        self.obstruction = motion.Obstruction()
        self.obstructed = None
        self.maker = clipmaker.ClipMaker(lambda start: store.new_part(name, start),
                                         lambda part, length, thumb_at: finisher.submit(part, length, thumb_at),
                                         settings.before_s, settings.after_s)
        self.started = None
        self.last_frame = self.last_fragment = self.last_motion = None
        self._finish = True  # what the record thread does with an open clip when its stream ends
        who = f"camera {n} ({name})"
        self.sources = (
            _Source(who + " motion", lambda: motion_cmd(self.n, self.settings.check, self.still),
                    self._read_motion, self._fresh_detector, backoff),
            _Source(who + " recording", lambda: record_cmd(self.n), self._read_record,
                    lambda: self.maker.stop(self._finish), backoff),
        )

    @staticmethod
    def _looks(s):
        return 2 if s.check == "fast" else 1  # fast: two looks in a row, to skip one-frame noise

    def _fresh_detector(self):
        # the motion ffmpeg ended: the next session's first frame must not be compared with this
        # session's last one (minutes old after a reconnect), or every restart looks like motion
        with self.lock:
            self.detector = motion.Detector(self.settings.sensitivity, self._looks(self.settings))

    def start(self):
        with self.lock:
            self.started = self.clock()
        for src in self.sources:
            src.start()

    def stop(self, finish=True):
        """Stop both ffmpegs (whole process groups); an open clip is finished, or left for recover()."""
        self._finish = finish
        for src in self.sources:
            src.close()
        deadline = time.monotonic() + 1.5
        for src in self.sources:
            if src.thread.is_alive():
                src.thread.join(max(0.0, deadline - time.monotonic()))
        for src in self.sources:
            if src.thread.is_alive():
                src.kill()
                src.thread.join(1)
                if src.thread.is_alive():
                    log(f"{src.who}: didn't stop")
        self.maker.stop(finish)

    def apply(self, s):
        with self.lock:
            old, self.settings = self.settings, s
            self.detector.sensitivity = s.sensitivity
            self.detector.looks_needed = self._looks(s)
        with self.maker.lock:
            self.maker.before_s, self.maker.after_s = s.before_s, s.after_s
        if s.check != old.check:
            with self.lock:
                self.started = self.clock()
            self.sources[0].restart()

    def state(self, now):
        with self.lock:
            seen = min(self.last_frame or 0, self.last_fragment or 0)
            if self.started is None or now - max(self.started, seen) > self.offline_s:
                state = "offline"
                self.obstruction.reset()
                self.obstructed = None
            elif self.maker.recording:
                state = "recording"
            elif self.obstructed and self.settings.obstructed == "pause":
                state = "paused"
            else:
                state = "watching"
            out = {"name": self.name, "n": self.n, "state": state, "obstructed": self.obstructed,
                   "last_motion": _when(self.last_motion), "last_frame": _when(self.last_frame),
                   "last_fragment": _when(self.last_fragment)}
        out["today"] = self.store.count(self.name, time.strftime("%Y-%m-%d", time.localtime(now)))
        return out

    def _read_motion(self, stream):
        size = motion.W * motion.H
        while True:
            frame = _read_exact(stream, size)
            if frame is None:
                return
            self._look(frame)

    def _look(self, frame):
        now = self.clock()
        with self.lock:
            self.last_frame = now
            moving = self.detector.look(frame)
            self.obstructed = self.obstruction.update(now, moving, frame)
            if moving:
                self.last_motion = now
            paused = self.obstructed is not None and self.settings.obstructed == "pause"
        if moving and not paused and self.allow_new():
            self.maker.motion(now)

    def _read_record(self, stream):
        clipmaker.pump(stream.read, self.maker, clock=self._fragment_time)

    def _fragment_time(self):
        self.last_fragment = now = self.clock()
        return now


class Finisher:
    """One thread that turns finished .part files into clips, one at a time (remux + thumbnail)."""

    def __init__(self, store, done):
        self.store, self.done = store, done
        self.queue = queue.Queue()
        self.recovered = threading.Event()  # set once leftover parts from a crash are dealt with
        self.thread = threading.Thread(target=self._run, name="finisher", daemon=True)

    def submit(self, part, length_s, thumb_at_s):
        self.queue.put((part, length_s, thumb_at_s))

    def start(self):
        self.thread.start()

    def stop(self, wait_s=5):
        self.queue.put(None)
        if self.thread.is_alive():
            self.thread.join(wait_s)

    def _run(self):
        try:
            saved = clipmaker.recover(self.store)
            if saved:
                log(f"saved {saved} clip(s) left from before a restart")
        except Exception as e:
            log(f"recovering old parts failed ({type(e).__name__}: {e})")
        finally:
            self.recovered.set()
        while True:
            item = self.queue.get()
            if item is None:
                return
            part = item[0]
            try:
                if clipmaker.finish(self.store, *item) is None:
                    log(f"couldn't save the clip {Path(part).name} of {Path(part).parent.parent.name}")
            except Exception as e:
                log(f"saving a clip failed ({type(e).__name__}: {e})")
            try:
                self.done()
            except Exception as e:
                log(f"after a clip: {type(e).__name__}: {e}")


def _disk(path):
    st = os.statvfs(path)
    return st.f_blocks * st.f_frsize, st.f_bavail * st.f_frsize  # total, free


class Recorder:
    """Keeps one Camera per recorded camera in step with the settings files; disk cap; state file."""

    def __init__(self, config, data, store, camera_factory=Camera, clock=time.time):
        self.config, self.data, self.store = Path(config), Path(data), store
        self.camera_factory, self.clock = camera_factory, clock
        self.stills = self.data / "recorder-stills"
        self.stills.mkdir(parents=True, exist_ok=True)
        self.store.root.mkdir(parents=True, exist_ok=True)  # statvfs needs it
        self.state_path = self.data / "recorder.json"
        self.finisher = Finisher(store, self._clip_done)
        self.cams = {}      # (n, name) -> Camera
        self.names = []     # step 11 cameras, in go2rtc order
        self.unknown = []   # names the recorder settings ask for that step 11 doesn't have (renamed?)
        self.disk = None
        self.bytes, self.floor_ok = 0, True
        self._enforce_now = False
        self._next = {"reload": 0.0, "enforce": 0.0, "state": 0.0}

    def allow_new(self):
        return self.floor_ok

    def _clip_done(self):
        self._enforce_now = True  # the cap is checked on the next tick, from the main thread

    def _due(self, what, now, every):
        if now < self._next[what]:
            return False
        self._next[what] = now + every
        return True

    def tick(self, now):
        if self._due("reload", now, RELOAD_S):
            self._try("reading settings", self._reload)
        if self.disk is not None and (self._enforce_now or self._due("enforce", now, ENFORCE_S)):
            self._enforce_now = False
            self._try("checking disk space", self._enforce)
        if self._due("state", now, STATE_S):
            self._try("writing the state file", self._write_state, now)

    @staticmethod
    def _try(what, fn, *args):
        try:
            fn(*args)
        except Exception as e:
            log(f"{what} failed ({type(e).__name__}: {e})")

    def _reload(self):
        self.store.root.mkdir(parents=True, exist_ok=True)  # "rm -r ~/recordings" must not stop the reloads
        names = cameras.load_names(self.config / "cameras")
        total, _ = _disk(self.store.root)
        self.disk = settings.disk_settings(settings.read_kv(self.config / "disk"), total)
        unknown = []
        if (self.config / "recorder").exists():
            kv = settings.read_kv(self.config / "recorder")
            s = settings.recorder_settings(kv, names)
            for name in (n.strip() for n in kv.get("cameras", "").split(",")):
                if name and name not in names and name not in unknown:
                    unknown.append(name)  # shown as not recording, never silently dropped
        else:
            s = None  # step 12 turned recording off: record nothing
        self.names, self.unknown = names, unknown
        wanted = {(i + 1, name) for i, name in enumerate(names) if s and name in s.cameras}
        for key in [k for k in self.cams if k not in wanted]:
            log(f"camera {key[0]} ({key[1]}): no longer recorded")
            self.cams.pop(key).stop()
        for key in sorted(wanted):
            cam = self.cams.get(key)
            if cam is None:
                log(f"camera {key[0]} ({key[1]}): watching")
                cam = self.cams[key] = self.camera_factory(key[0], key[1], s, self.store, self.finisher,
                                                           self.stills, self.allow_new)
                cam.start()
            else:
                cam.apply(s)

    def _enforce(self):
        root = self.store.root
        root.mkdir(parents=True, exist_ok=True)  # statvfs needs it
        self.bytes, floor_ok = self.store.enforce(self.disk.recordings_bytes, self.disk.keep_free_bytes,
                                                  lambda: _disk(root)[1])
        if floor_ok != self.floor_ok:
            log("disk almost full: no new clips" if not floor_ok else "disk space back: recording again")
        self.floor_ok = floor_ok

    def _write_state(self, now):
        today = time.strftime("%Y-%m-%d", time.localtime(now))
        rows = []
        for i, name in enumerate(self.names):
            cam = self.cams.get((i + 1, name))
            if cam is not None:
                rows.append(cam.state(now))
            else:
                rows.append({"name": name, "n": i + 1, "state": "off", "obstructed": None, "last_motion": None,
                             "last_frame": None, "last_fragment": None, "today": self.store.count(name, today)})
        for name in self.unknown:  # asked for, but not a step 11 camera (renamed?): it can't be recording
            rows.append({"name": name, "n": None, "state": "offline", "obstructed": None, "last_motion": None,
                         "last_frame": None, "last_fragment": None, "today": self.store.count(name, today)})
        body = json.dumps({"time": int(now), "bytes": self.bytes, "disk_full": not self.floor_ok, "cameras": rows})
        tmp = self.state_path.with_name(self.state_path.name + ".tmp")
        tmp.write_text(body)
        os.replace(tmp, self.state_path)

    def stop(self):
        """Stop every camera at once; open clips are left as parts for recover() on the next start."""
        cams, self.cams = list(self.cams.values()), {}
        threads = [threading.Thread(target=cam.stop, args=(False,), daemon=True) for cam in cams]
        for t in threads:
            t.start()
        for t in threads:
            t.join(5)


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    if not (CONFIG / "recorder").exists():
        log("no recorder settings (step 12 not run): nothing to do")
        return 0
    subprocess.run(["pkill", "-f", "--", LEFTOVER_PATTERN], capture_output=True)  # from a recorder that crashed
    rec = Recorder(CONFIG, DATA, ClipStore(RECORDINGS))

    # The handler only sets a flag: it runs between any two lines of the main thread, maybe while that
    # holds a lock (log, a camera, even an Event's own lock), so taking one there could hang for good.
    stopping = []
    signal.signal(signal.SIGTERM, lambda signum, frame: stopping.append(signum))
    log("starting")
    rec.finisher.start()
    while not stopping and not rec.finisher.recovered.is_set():
        time.sleep(0.5)  # a leftover part must never be one a camera is writing
    while not stopping:
        try:
            rec.tick(rec.clock())
        except Exception as e:
            log(f"tick failed ({type(e).__name__}: {e})")
        time.sleep(1)
    log("stopping")  # outside every lock now
    rec.stop()
    os._exit(0)


if __name__ == "__main__":
    sys.exit(main())
