#!/data/data/com.termux/files/usr/bin/python
"""drawer-server status panel.

A tiny web page (standard library only) that shows battery, temperature, memory, disk
and which services are alive. It also logs the battery every 5 minutes so you can see
how an always-plugged phone behaves over a day.

Runs inside Termux:  python ~/panel/panel.py   ->  http://<phone-ip>:8080
"""
import csv
import html
import ipaddress
import json
import os
import re
import shutil
import signal
import socket
import sys
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cameras import Stills, is_home, kill_leftovers, load_names
from clips import CLIP, DAY, FOLDER, THUMB, ClipStore
from settings import disk_settings, read_kv, shows_recordings
from system import Sampler, battery_watts, load_word, sysinfo

HOME = Path.home()
PORT = int(os.environ.get("PANEL_PORT", "8080"))
LANG = os.environ.get("PANEL_LANG", "en")
DATA = HOME / ".cache" / "drawer-server"
BATTERY_LOG = DATA / "battery.csv"
LOG_EVERY = 300           # seconds between battery samples
KEEP_SAMPLES = 7 * 24 * 12  # one week at 5-minute samples

DATA.mkdir(parents=True, exist_ok=True)
_battery = {}


def battery():
    """termux-battery-status (Termux:API). Slow-ish (~1 s), so callers use the cached copy.

    If Termux:API doesn't answer, the helper it spawns waits forever. subprocess's timeout only
    kills the direct child, so those helpers piled up (1921 of them on the test phone). Run it in
    its own process group and kill the whole group instead.
    """
    proc = subprocess.Popen(["termux-battery-status"], stdout=subprocess.PIPE, text=True,
                            start_new_session=True)
    try:
        out, _ = proc.communicate(timeout=15)
        return json.loads(out)
    except (subprocess.TimeoutExpired, ValueError):
        try:
            os.killpg(proc.pid, 9)
        except OSError:
            pass
        proc.wait()
        return {}


_battery_ok_at = time.time()


def battery_logger():
    global _battery, _battery_ok_at
    while True:
        b = battery()
        if b:
            _battery, _battery_ok_at = b, time.time()
            with BATTERY_LOG.open("a", newline="") as f:
                csv.writer(f).writerow([int(time.time()), b.get("percentage"), b.get("temperature"), b.get("plugged")])
            lines = BATTERY_LOG.read_text().splitlines()
            if len(lines) > KEEP_SAMPLES:
                BATTERY_LOG.write_text("\n".join(lines[-KEEP_SAMPLES:]) + "\n")
        # retry soon if Termux:API didn't answer (e.g. Android had it stopped)
        time.sleep(LOG_EVERY if b else 30)


# --- Smart plug: charge between 30 and 80% ---------------------------------------------------------
# Android can't stop charging without root, so a Tuya plug feeding the charger does it:
# off at CHARGE_HIGH, on at CHARGE_LOW. Local network only (tinytuya + the plug's local key,
# saved by scripts/10-smart-plug.sh). If the battery can't be read for a while, charge: a phone
# that runs flat is worse than one that sits at 100% for a bit.
PLUG_CONFIG = HOME / ".config" / "drawer-server" / "plug"
CHARGE_LOW = int(os.environ.get("CHARGE_LOW", "30"))
CHARGE_HIGH = int(os.environ.get("CHARGE_HIGH", "80"))
_plug = None


def plug_keeper():
    global _plug, _battery, _battery_ok_at
    import tinytuya
    dev_id, ip, key, version = PLUG_CONFIG.read_text().split()
    plug = tinytuya.OutletDevice(dev_id, ip, key, version=float(version))
    plug.set_socketTimeout(5)
    battery_ok_at = time.time()
    while True:
        b = battery()
        if b:  # fresher than the 5-minute log, so the page shows the cut right away
            _battery = b
            battery_ok_at = _battery_ok_at = time.time()
        try:
            dps = plug.status().get("dps") or {}
            if "1" not in dps:
                raise OSError("no answer")
            on, p = dps["1"], b.get("percentage")
            if p is not None and p >= CHARGE_HIGH and on:
                plug.turn_off()
                on = False
            elif not on and ((p is not None and p <= CHARGE_LOW) or time.time() - battery_ok_at > 1800):
                plug.turn_on()
                on = True
            # DP 19 is the power reading in tenths of a watt on Tuya metering plugs
            _plug = {"on": on, "watts": dps["19"] / 10 if isinstance(dps.get("19"), int) else None,
                     "low": CHARGE_LOW, "high": CHARGE_HIGH}
        except Exception as e:  # unplugged, Wi-Fi hiccup...: try again next round
            _plug = {"error": str(e)[:80]}
        time.sleep(60)


def memory():
    info = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, value = line.split(":", 1)
        info[key] = int(value.split()[0]) // 1024
    return {"total_mb": info["MemTotal"], "available_mb": info["MemAvailable"]}


def disk():
    """Free space, plus how the disk is split between kinds of files (DISK_KINDS) and one warning:
    only photo backups warn, since the panel never deletes them. Recordings at their cap are normal
    (the oldest clip goes), so they never warn."""
    d = shutil.disk_usage(HOME)
    settings = disk_settings(read_kv(CONFIG / "disk"), d.total)
    kinds, sizes = [], {}
    for kind, measure, share in DISK_KINDS:
        size = measure()
        if size is None:  # this server doesn't have that kind
            continue
        sizes[kind], limit = size, share(settings)
        kinds.append({"kind": kind, "gb": round(size / 1e9, 1), "share_gb": None if limit is None else round(limit / 1e9, 1)})
    warn = None
    if paused_by_us():
        warn = "paused"
    elif settings.backup_bytes and sizes.get("backup", 0) > BACKUP_NEAR * settings.backup_bytes:
        warn = "near"
    return {"total_gb": round(d.total / 1e9, 1), "free_gb": round(d.free / 1e9, 1), "kinds": kinds, "warn": warn}


BACKUP_NEAR = 0.9     # warn over this part of the photo backup's share
BACKUP_RESUME = 0.95  # resume the folders the panel paused once under this part of it
BACKUP_PAUSED = DATA / "backup-paused.json"  # folder ids the panel paused itself, to resume only those
_rec_size = {"t": 0.0, "v": 0}


def backup_bytes():
    b = _home.get("backup")
    return b.get("local_bytes") if isinstance(b, dict) else None


def recordings_bytes():
    """The recorder's own count while it runs, else a walk of the clips (at most every 5 minutes).
    None when there is no recorder and no clips."""
    now = time.time()
    rec = recorder_status(now)
    if rec and not rec["stale"]:
        return rec["bytes"]
    if now - _rec_size["t"] > 300:
        _rec_size["t"], _rec_size["v"] = now, STORE.total_bytes()
    return None if rec is None and not _rec_size["v"] else _rec_size["v"]


# (kind, how many bytes it uses or None, its share of the disk or None); a new kind is one more entry
DISK_KINDS = [("backup", lambda: backup_bytes(), lambda s: s.backup_bytes),
              ("recordings", lambda: recordings_bytes(), lambda s: s.recordings_bytes)]


def paused_by_us():
    try:
        ids = json.loads(BACKUP_PAUSED.read_text())
        return {i for i in ids if isinstance(i, str)} if isinstance(ids, list) else set()
    except (OSError, ValueError):
        return set()


def remember_paused(ids):
    BACKUP_PAUSED.parent.mkdir(parents=True, exist_ok=True)
    tmp = BACKUP_PAUSED.with_name(BACKUP_PAUSED.name + ".tmp")
    tmp.write_text(json.dumps(sorted(ids)))
    os.replace(tmp, BACKUP_PAUSED)


def backup_pause_plan(total, share, pause_on, paused_now, ours):
    """(folders to pause, folders to resume). Only folders in `ours` are ever resumed."""
    full = pause_on and bool(share) and total >= share
    pause = {f for f, p in paused_now.items() if not p} if full else set()
    ok = not pause_on or not share or total < BACKUP_RESUME * share
    resume = {f for f in ours if paused_now.get(f)} if ok else set()
    return pause, resume


def pid_alive(pidfile):
    try:
        os.kill(int(Path(pidfile).read_text().strip()), 0)
        return True
    except (OSError, ValueError):
        return False


def process_running(name):
    """True if a process with exactly this name runs (never matches our own command line)."""
    for proc in Path("/proc").iterdir():
        if proc.name.isdigit():
            try:
                if (proc / "comm").read_text().strip() == name:
                    return True
            except OSError:
                pass
    return False


def luanti_players():
    """Count players from the server log: joins minus leaves since the server started."""
    log = HOME / "luanti" / "server.log"
    if not log.exists():
        return None
    online = set()
    for line in log.read_text(errors="replace").splitlines():
        m = re.search(r"ACTION\[Server\]: (\S+) (joins|leaves) game", line)
        if m:
            (online.add if m.group(2) == "joins" else online.discard)(m.group(1))
    return sorted(online)


def nextdns_last():
    log = HOME / ".cache" / "nextdns-link.log"
    if not log.exists():
        return None
    lines = log.read_text().splitlines()
    return lines[-1] if lines else None


def my_ip():
    """This phone's address on the home network (a UDP connect sends nothing, it only picks the route)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return None


def uptime_hours():
    info = sysinfo()  # Android 15 refuses /proc/uptime to apps
    if info:
        return round(info["uptime_s"] / 3600, 1)
    try:
        return round(float(Path("/proc/uptime").read_text().split()[0]) / 3600, 1)
    except (OSError, ValueError):
        return None


# --- Home: Starlink, printer, who's home, photo backup -------------------------------------------------
# Each reader runs in its own thread every few minutes and leaves its last result here,
# so a page load never waits on the network.
CONFIG = HOME / ".config" / "drawer-server"
STARLINK_DISH = os.environ.get("STARLINK_DISH", "192.168.100.1:9200")
_home = {"starlink": None, "printer": None, "people": None, "backup": None, "devices": None}


def every(seconds, key, reader, store=True):
    """store=False: the reader puts its result in _home itself (under its own lock)."""
    def loop():
        while True:
            try:
                value = reader()
                if store:
                    _home[key] = value
            except Exception as e:  # a broken reader must not kill the panel
                _home[key] = {"error": str(e)}
            time.sleep(seconds)
    threading.Thread(target=loop, daemon=True).start()


def starlink():
    """Ask the dish for its status over its local gRPC API (no account needed)."""
    out = subprocess.run(["grpcurl", "-plaintext", "-max-time", "8", "-d", '{"get_status":{}}',
                          STARLINK_DISH, "SpaceX.API.Device.Device/Handle"],
                         capture_output=True, text=True, timeout=15)
    s = json.loads(out.stdout)["dishGetStatus"]
    return {
        "latency_ms": round(s.get("popPingLatencyMs", 0)),
        "down_mbps": round(s.get("downlinkThroughputBps", 0) / 1e6, 2),
        "up_mbps": round(s.get("uplinkThroughputBps", 0) / 1e6, 2),
        "obstructed_pct": round(s.get("obstructionStats", {}).get("fractionObstructed", 0) * 100, 1),
        "uptime_h": round(int(s.get("deviceState", {}).get("uptimeS", 0)) / 3600, 1),
        "alerts": [k for k, v in s.get("alerts", {}).items() if v],
    }


SPEED_LOG = DATA / "speed.csv"
SPEED_TRIES = DATA / "speed-tries"  # when each test started, failed ones too; kept for a day
SPEED_KEEP = 200       # rows kept in speed.csv
SPEED_GAP_S = 300      # wait this long after a test before another one
SPEED_MAX_PER_DAY = 6  # automatic tests a day, at most
SPEED_DAY_CAP = 12     # tests a day in all, "Test now" included: each one moves ~100 MB
_speed = {"running": False, "error": None}
_speed_lock = threading.Lock()


def speed_per_day():
    """Automatic tests a day, 0 to 6 (PANEL_SPEEDTEST in .env); 0 = only the button; None = off.
    Read on every use: the scheduler always runs, so changing the file needs no restart."""
    f = CONFIG / "speedtest"
    if not f.exists() or not shutil.which("speedtest-go"):
        return None
    try:
        return min(SPEED_MAX_PER_DAY, max(0, int(f.read_text().strip() or 0)))
    except ValueError:
        return 0


def speed_history():
    if not SPEED_LOG.exists():
        return []
    rows = []
    for row in csv.reader(SPEED_LOG.read_text().splitlines()):
        try:
            rows.append([int(row[0]), float(row[1]), float(row[2]), int(row[3]), row[4]])
        except (IndexError, ValueError):
            pass
    return rows


def speedtest():
    """One test against the nearest speedtest.net server: 10 s down, 15 s up, ~100 MB in all.
    It runs on the server, so its own Wi-Fi is part of what gets measured."""
    out = subprocess.run(["speedtest-go", "--json"], capture_output=True, text=True, timeout=120)
    s = json.loads(out.stdout)["servers"][0]
    # speedtest-go reports bytes per second and nanoseconds
    return [int(time.time()), round(s["dl_speed"] * 8 / 1e6, 1), round(s["ul_speed"] * 8 / 1e6, 1),
            round(s["latency"] / 1e6), s.get("name") or ""]


def speed_tries():
    day_ago = time.time() - 24 * 3600
    if not SPEED_TRIES.exists():  # e.g. after an update: the last result still counts
        return [r[0] for r in speed_history()[-1:] if r[0] >= day_ago]
    tries = []
    for t in SPEED_TRIES.read_text().split():
        try:
            if int(t) >= day_ago:
                tries.append(int(t))
        except ValueError:
            pass
    return tries


def speed_next_ok(tries):
    """When the next test may start: after the gap, and the next day once the day's tests are used."""
    if len(tries) >= SPEED_DAY_CAP:
        return tries[-SPEED_DAY_CAP] + 24 * 3600
    return tries[-1] + SPEED_GAP_S if tries else 0


def start_speedtest():
    """Run a test in the background. False if one is running, or it's too soon (see speed_next_ok).
    Failed tests count too: one that breaks after moving its 100 MB must not repeat every few minutes."""
    if not _speed_lock.acquire(blocking=False):
        return False
    tries = speed_tries()
    if time.time() < speed_next_ok(tries):
        _speed_lock.release()
        return False
    tmp = SPEED_TRIES.with_suffix(".tmp")
    tmp.write_text("".join(f"{t}\n" for t in tries + [int(time.time())]))
    os.replace(tmp, SPEED_TRIES)
    _speed["running"] = True

    def work():
        try:
            rows = speed_history() + [speedtest()]
            tmp = SPEED_LOG.with_suffix(".tmp")  # write aside, then swap: a power cut can't empty the log
            with tmp.open("w", newline="") as f:
                csv.writer(f).writerows(rows[-SPEED_KEEP:])
            os.replace(tmp, SPEED_LOG)
            _speed["error"] = None
        except Exception as e:  # offline, server busy, odd output: show it, try again next time
            _speed["error"] = str(e) or type(e).__name__
        finally:
            _speed["running"] = False
            _speed_lock.release()
    threading.Thread(target=work, daemon=True).start()
    return True


def speed_scheduler():
    time.sleep(120)  # let the phone settle after a boot
    while True:
        per_day, tries = speed_per_day(), speed_tries()
        if per_day and (not tries or time.time() - tries[-1] >= 24 * 3600 / per_day):
            start_speedtest()
        time.sleep(300)


def speed_status():
    per_day = speed_per_day()
    if per_day is None:
        return None
    day_ago = time.time() - 24 * 3600
    rows = speed_history()
    return {"per_day": per_day, "running": _speed["running"], "error": _speed["error"],
            "next_ok": speed_next_ok(speed_tries()),
            "last": rows[-1] if rows else None, "day": [r for r in rows if r[0] >= day_ago]}


INK_COLORS = {0: "black", 1: "cyan", 2: "magenta", 3: "yellow", 4: "light cyan", 5: "light magenta"}


def printer():
    """Epson ink levels via Epson's own SNMP status query ('st' command), which works even on
    old models that don't fill in the standard printer supplies table."""
    host = (CONFIG / "printer").read_text().strip()
    out = subprocess.run(["snmpget", "-v1", "-c", "public", "-t", "4", "-Ox", "-Oqv", host,
                          "1.3.6.1.4.1.1248.1.2.2.44.1.1.2.1.115.116.1.0.1"],
                         capture_output=True, text=True, timeout=15)
    data = bytes.fromhex(re.sub(r"[^0-9A-Fa-f]", "", out.stdout))
    start = data.find(b"@BDC ST2\r\n")
    if start < 0:
        raise ValueError("no Epson status in reply")
    body = data[start + 12:]  # skip header and the 2-byte length
    inks, i = [], 0
    while i + 2 <= len(body):  # fields are: type, length, value
        kind, size = body[i], body[i + 1]
        value = body[i + 2:i + 2 + size]
        if kind == 0x0F and value:  # ink: entry size, then [cartridge, color, level] per ink
            step = value[0]
            for j in range(1, len(value) - step + 1, step):
                inks.append({"color": INK_COLORS.get(value[j + 1], str(value[j + 1])), "level": value[j + 2]})
        i += 2 + size
    return {"inks": inks}


def ping(ip):
    return subprocess.run(["ping", "-c", "2", "-W", "2", ip], capture_output=True).returncode == 0


_last_seen = {}


def people():
    """Who's home: ping each person's phone. Sleeping phones skip pings, so someone counts as
    home if their phone answered in the last 20 minutes, or if the router card lists it as
    connected (a sleeping phone stays on the Wi-Fi). Config: one 'Name IP' per line."""
    dv = _home.get("devices") or {}
    on_wifi = {d["ip"] for d in dv.get("devices", []) if d["online"] and d["ip"]}
    result = []
    for line in (CONFIG / "people").read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        name, ip = line.rsplit(None, 1)
        if ip in on_wifi or ping(ip):
            _last_seen[name] = time.time()
        seen = _last_seen.get(name)
        result.append({"name": name, "ip": ip, "home": bool(seen and time.time() - seen < 20 * 60),
                       "seen_min_ago": round((time.time() - seen) / 60) if seen else None})
    return result


SYNCTHING_CONFIG = HOME / ".local" / "state" / "syncthing" / "config.xml"
_sync_prev = {}


def backup():
    """Photo backup (scripts/09-syncthing.sh): each folder's progress and whether the phone that
    sends it is connected, from Syncthing's local REST API."""
    key = re.search(r"<apikey>([^<]+)</apikey>", SYNCTHING_CONFIG.read_text()).group(1)

    def get(path):
        req = urllib.request.Request("http://127.0.0.1:8384" + path, headers={"X-API-Key": key})
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.load(r)

    me = get("/rest/system/status")["myID"]
    names = {d["deviceID"]: d["name"] for d in get("/rest/config/devices")}
    conns = get("/rest/system/connections")
    online = {d for d, c in conns["connections"].items() if c.get("connected")}
    # download speed from the change in bytes received since the last call
    now, received = time.time(), conns["total"]["inBytesTotal"]
    t0, r0 = _sync_prev.get("t"), _sync_prev.get("in", 0)
    speed = (received - r0) / (now - t0) / 1e6 if t0 and received >= r0 else 0
    _sync_prev["t"], _sync_prev["in"] = now, received
    folders, config = [], get("/rest/config/folders")
    for f in config:
        st = get("/rest/db/status?folder=" + urllib.parse.quote(f["id"]))
        senders = [d["deviceID"] for d in f["devices"] if d["deviceID"] != me]
        total, need = st["globalBytes"], st["needBytes"]
        folders.append({"id": f["id"], "label": f["label"] or f["id"], "paused": bool(f.get("paused")),
                        "local_bytes": int(st.get("localBytes", 0)),
                        "from": ", ".join(names.get(d, d[:7]) for d in senders),
                        "online": any(d in online for d in senders),
                        "pct": 100 if not total else int((total - need) * 100 / total),
                        "need_gb": round(need / 1e9, 1), "need_files": st["needFiles"]})
    local = sum(f["local_bytes"] for f in folders)
    keep_backup_share(local, folders, key)
    return {"folders": folders, "mb_s": round(speed, 1), "local_bytes": local}


def keep_backup_share(local, folders, key):
    """With DISK_BACKUP_PAUSE=yes, pause the photo folders at their share and resume them below 95%.
    Resumes only folders it paused itself (kept in BACKUP_PAUSED), never ones a person paused."""
    settings = disk_settings(read_kv(CONFIG / "disk"), shutil.disk_usage(HOME).total)
    paused = {f["id"]: f["paused"] for f in folders}
    ours = paused_by_us() & {i for i, p in paused.items() if p}  # a person resumed it, or it's gone: forget it
    to_pause, to_resume = backup_pause_plan(local, settings.backup_bytes, settings.backup_pause, paused, ours)
    for fid in sorted(to_pause | to_resume):
        pause = fid in to_pause
        if pause:  # write the intent first: a paused folder nobody remembers would never resume
            try:
                remember_paused(ours | {fid})
            except OSError as e:
                print("backup pause skipped, can't write", BACKUP_PAUSED, e, file=sys.stderr, flush=True)
                continue
        req = urllib.request.Request("http://127.0.0.1:8384/rest/config/folders/" + urllib.parse.quote(fid, safe=""),
                                     data=json.dumps({"paused": pause}).encode(), method="PATCH",
                                     headers={"X-API-Key": key, "Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=5).close()
        except (OSError, ValueError):  # Syncthing busy or down: try again in 30 s
            # A timeout can come after Syncthing applied the pause, so the intent stays in `ours`.
            # If it didn't apply, the next pass sees the folder unpaused and drops the entry.
            if pause:
                ours = ours | {fid}
            continue
        for f in folders:
            if f["id"] == fid:
                f["paused"] = pause
        ours = ours | {fid} if pause else ours - {fid}
        if not pause:
            try:
                remember_paused(ours)
            except OSError:
                pass  # a stale entry is harmless: only paused folders in it are ever resumed
    if ours != paused_by_us():  # forgot folders a person resumed
        try:
            remember_paused(ours)
        except OSError:
            pass


# Ezviz (Hikvision) cameras and doorbells; the rest is guessed from the name the device reports
CAMERA_MACS = ("F4-70-18", "0C-A6-4C")
KINDS = ("camera", "computer", "phone", "network", "other")
DEVICES_SEEN = DATA / "devices.json"


def device_kind(name, mac):
    n = name.lower()
    if mac.startswith(CAMERA_MACS) or re.search(r"cam|timbre|doorbell|ezviz", n):
        return "camera"
    if re.search(r"desktop|laptop|lenovo|notebook|macbook|imac|compu|\bpc\b", n):
        return "computer"
    if re.search(r"archer|deco|router|repeater|extender", n):
        return "network"
    # phones make up a "private" MAC per network: the second hex digit is 2, 6, A or E
    if re.search(r"celu|phone|iphone|galaxy|moto|pixel", n) or mac[1:2] in "26AE":
        return "phone"
    return "other"


DEVICE_PATH = re.compile(r"/api/devices/([0-9A-F]{2}(?:-[0-9A-F]{2}){5})(/name)?")
_devices_lock = threading.Lock()  # the router reader and the panel's rename/forget buttons share these files
_dv_last = {"read": False, "online": set(), "ssid": None}  # the last router read, to redraw the list after a change


def device_names():
    """Names from PANEL_DEVICE_NAMES ('MAC Name' lines), then the ones given in the panel, which win."""
    names = {}
    if (CONFIG / "device-names").exists():
        for line in (CONFIG / "device-names").read_text().splitlines():
            if line.strip():
                mac, name = line.split(None, 1)
                names[mac.upper().replace(":", "-")] = name.strip()
    names.update(read_json(CONFIG / "device-names-panel.json"))
    return names


def read_json(path):
    """A dict saved by write_json, or {} if there's none."""
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_json(path, data):
    # a new file swapped in whole: a power cut halfway leaves the old one, not an empty one
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False))
    os.replace(tmp, path)


def devices():
    """Everything connected to the home router (TP-Link, through its web API), plus devices seen
    before that are gone now, so a camera that drops off the Wi-Fi shows up as offline.
    Config: router URL and password in ~/.config/drawer-server/router (one per line), optional
    'MAC Name' lines in ~/.config/drawer-server/device-names, and MACs to leave out (one per line,
    e.g. a camera's Wi-Fi that was turned off on purpose) in ~/.config/drawer-server/device-hide.
    Names given in the panel go to ~/.config/drawer-server/device-names-panel.json."""
    from tplinkrouterc6u import TplinkRouterProvider  # only installed when the router card is on
    url, password = (CONFIG / "router").read_text().splitlines()[:2]
    try:
        router = TplinkRouterProvider.get_client(url, password)
        router.authorize()  # TP-Link allows one admin at a time: this logs out a browser session
        try:
            connected = router.get_status().devices
            try:
                ssid = router.request("admin/wireless?form=wireless_2g", "operation=read").get("ssid")
            except Exception:
                ssid = None
        finally:
            router.logout()
    except Exception:
        _dv_last["read"] = False  # who's online is unknown: no renaming or forgetting until a read works
        raise
    with _devices_lock:
        seen = read_json(DEVICES_SEEN)
        now, online = time.time(), set()
        for d in connected:
            mac = str(d.macaddr).upper()
            online.add(mac)
            conn = {"WIRED": "wired", "HOST_2G": "2.4", "HOST_5G": "5", "GUEST_2G": "2.4", "GUEST_5G": "5"}.get(
                getattr(d.type, "name", ""), "wifi")
            ip = str(d.ipaddr)
            seen[mac] = {"host": d.hostname if d.hostname and d.hostname != "network device" else seen.get(mac, {}).get("host"),
                         "ip": None if ip == "0.0.0.0" else ip, "conn": conn,
                         "signal": d.signal if conn != "wired" else None, "last": now}
        for mac in [m for m, d in seen.items() if now - d["last"] > 30 * 86400]:
            del seen[mac]  # forget devices gone for a month
        write_json(DEVICES_SEEN, seen)
        _dv_last.update(read=True, online=online, ssid=ssid)
        _home["devices"] = device_list(seen)  # inside the lock, so it can't undo a rename made meanwhile


def device_list(seen):
    """What the page shows, from the devices seen and the last router read."""
    names, online, now = device_names(), _dv_last["online"], time.time()
    hide = set()
    if (CONFIG / "device-hide").exists():
        hide = {m.strip().upper().replace(":", "-") for m in (CONFIG / "device-hide").read_text().split()}
    result = []
    for mac, d in seen.items():
        if mac in hide:
            continue
        name = names.get(mac) or d["host"] or (d["ip"] or mac)
        # last_ip lets the page match a device to a person's phone even while it's away
        result.append({"name": name, "kind": device_kind(name, mac), "ip": d["ip"] if mac in online else None,
                       "last_ip": d["ip"], "conn": d["conn"], "signal": d["signal"], "online": mac in online,
                       "seen_min_ago": round((now - d["last"]) / 60), "mac": mac, "host": d["host"]})
    result.sort(key=lambda x: (KINDS.index(x["kind"]), not x["online"], x["name"].lower()))
    return {"ssid": _dv_last["ssid"], "devices": result}


def change_device(mac, name=None, forget=False):
    """The panel's buttons: name a device (an empty name goes back to the router's or .env's), or
    forget one that is offline, name included; if it comes back it shows up as new. Returns the new
    list, or None if there's no such device, or it's online and asked to be forgotten."""
    with _devices_lock:
        seen = read_json(DEVICES_SEEN)
        # until a router read worked, who's online isn't known
        if not _dv_last["read"] or mac not in seen or (forget and mac in _dv_last["online"]):
            return None
        path = CONFIG / "device-names-panel.json"
        given = read_json(path)
        if forget:
            del seen[mac]
            write_json(DEVICES_SEEN, seen)
            given.pop(mac, None)
        elif name:
            given[mac] = name
        else:
            given.pop(mac, None)
        write_json(path, given)
        _home["devices"] = device_list(seen)
        return _home["devices"]


def start_home_readers():
    if (CONFIG / "starlink").exists():
        every(60, "starlink", starlink)
    if (CONFIG / "printer").exists():
        every(600, "printer", printer)
    if (CONFIG / "people").exists():
        every(120, "people", people)
    if (CONFIG / "router").exists():
        every(300, "devices", devices, store=False)
    if SYNCTHING_CONFIG.exists():
        every(30, "backup", backup)


# --- Cameras (scripts/11-cameras.sh) -------------------------------------------------------------
# The panel serves the stills, and passes live video through from go2rtc, which only listens on
# this phone: that way "home only" covers live video too, and go2rtc never faces the network.
GO2RTC_PORT = int(os.environ.get("GO2RTC_PORT", "1984"))
CAMERA_NAMES = []
STILLS = None
CAMERA_PATH = re.compile(r"/api/camera/([1-9][0-9]?)\.jpg(\?.*)?")
LIVE_PATH = re.compile(r"/live/ws\?src=cam([1-9][0-9]?)(_hd)?")
LIVE_IDLE_S = 30  # hang up live video after this long without a byte from go2rtc
LIVE_HEADERS = ("upgrade", "connection", "sec-websocket-key", "sec-websocket-version",
                "sec-websocket-extensions", "sec-websocket-protocol")


# --- Recordings (scripts/12-recorder.sh) ---------------------------------------------------------
# The recorder writes clips and a small state file; the panel only reads them, home-only like live view.
RECORDINGS = HOME / "recordings"
STORE = ClipStore(RECORDINGS)
REC_STATE = DATA / "recorder.json"
REC_BOOT = HOME / ".termux" / "boot" / "70-recorder.sh"
REC_STALE_S = 60  # the recorder rewrites its state every few seconds; older than this = not running
REC_LIST = re.compile(r"/api/recordings")
REC_DAY = re.compile(r"/api/recordings/([^/]+)/([^/]+)")
REC_FILE = re.compile(r"/rec/([^/]+)/([^/]+)/([^/]+)")
RANGE = re.compile(r"bytes=(\d*)-(\d*)")
CHUNK = 64 * 1024


_rec_any = {"t": 0.0, "v": False}  # "is there any clip at all", asked at most once a minute


def recordings_shown():
    # status() asks every few seconds: the boot script check is cheap; without it (recorder off, clips
    # kept), a look for any clip that stops at the first one, remembered for a minute
    if not shows_recordings(read_kv(CONFIG / "panel-recordings")):
        return False
    if REC_BOOT.exists():
        return True
    now = time.time()
    if now - _rec_any["t"] > 60:
        _rec_any["t"], _rec_any["v"] = now, STORE.has_clips()
    return _rec_any["v"]


def recorder_status(now):
    if not REC_BOOT.exists():
        return None
    try:
        state = json.loads(REC_STATE.read_text())
        cams = [c for c in state["cameras"] if isinstance(c, dict)]
        out = {"stale": now - float(state["time"]) > REC_STALE_S, "disk_full": bool(state.get("disk_full")),
               "bytes": int(state.get("bytes", 0)), "today": sum(int(c.get("today", 0)) for c in cams),
               "cameras": [{"name": c.get("name"), "state": c.get("state"), "obstructed": c.get("obstructed")} for c in cams]}
    except (OSError, ValueError, KeyError, TypeError):
        out = {"stale": True, "disk_full": False, "bytes": 0, "today": 0, "cameras": []}
    return out


SAMPLER = Sampler()  # started in __main__; until then (and in tests) it reports nothing yet


def system_status():
    """How hard the phone works: CPU clock, load, our services and the battery's watts."""
    snap, info = SAMPLER.snapshot(), sysinfo()
    load = info["load"][0] if info else None
    return dict(snap, load=load, load_word=load_word(load, snap["ncpu"]) if load is not None else None,
                watts=battery_watts(_battery))


def status(client_ip="127.0.0.1"):
    # each optional service shows up once its step installed it
    services = [{"name": "SSH", "ok": process_running("sshd")}]
    if (HOME / ".termux" / "boot" / "20-nextdns-link.sh").exists():
        services.append({"name": "NextDNS", "ok": pid_alive(HOME / ".cache" / "nextdns-link.pid"), "detail": nextdns_last()})
    if (HOME / "luanti").exists():
        players = luanti_players()
        services.append({"name": "Luanti", "ok": pid_alive(HOME / "luanti" / "server.pid") and process_running("luantiserver"),
                         "players": players})
    if (HOME / ".termux" / "boot" / "50-syncthing.sh").exists():
        services.append({"name": "Syncthing", "ok": pid_alive(HOME / ".cache" / "syncthing.pid")})
    if CAMERA_NAMES:
        services.append({"name": "Cameras", "ok": pid_alive(HOME / ".cache" / "go2rtc.pid")})
    recorder = recorder_status(time.time())
    if recorder:
        services.append({"name": "Recorder", "ok": not recorder["stale"]})
    history = []
    if BATTERY_LOG.exists():
        day_ago = time.time() - 24 * 3600
        for row in csv.reader(BATTERY_LOG.read_text().splitlines()):
            if len(row) >= 3 and row[1] and int(row[0]) >= day_ago:
                history.append([int(row[0]), float(row[1]), float(row[2] or 0)])
    # Android sometimes puts Termux:API to sleep; then battery readings silently stop
    battery_stale = time.time() - _battery_ok_at > 600
    return {"battery": {} if battery_stale else _battery, "battery_stale": battery_stale, "memory": memory(), "disk": disk(), "uptime_h": uptime_hours(),
            "system": system_status(), "services": services, "history": history,
            "home": _home, "plug": _plug, "time": int(time.time()), "speed": speed_status(),
            "cameras": {"names": CAMERA_NAMES, "home": is_home(client_ip)} if CAMERA_NAMES else None,
            "recorder": recorder,
            "at_home": is_home(client_ip),  # the devices card's name and delete buttons are home-only
            # None only when PANEL_RECORDINGS hides them; nothing recorded yet and no recorder = "off"
            "recordings": {"home": is_home(client_ip)} if recordings_shown()
                          else {"off": True} if shows_recordings(read_kv(CONFIG / "panel-recordings")) else None,
            # the server and its plug show in the server section, not with the other devices
            "self_ip": my_ip(), "plug_ip": PLUG_CONFIG.read_text().split()[1] if PLUG_CONFIG.exists() else None}


TEXT = {
    "en": {"title": "Drawer server", "battery": "Battery", "temp": "Temperature", "ram": "Memory (RAM)",
           "disk": "Free storage", "uptime": "on for", "hours": "h", "services": "Services",
           "players": "playing", "nobody": "nobody playing",
           "charging": "charging", "not_charging": "on battery", "updated": "updated",
           "unplug": "🔌 Battery at {p}%: unplug the charger (keeping it between 30 and 80% makes it last longer)",
           "plug": "🔌 Battery at {p}%: plug the charger in (unplug it at 80%)",
           "plug_on": "On", "plug_off": "Off", "plug_to_high": "charging up to {high}%", "plug_to_low": "charges again at {low}%",
           "plug_noanswer": "Not answering", "plug_reach": "connected", "plug_now": "Now",
           "plug_rule": "It turns off when the battery reaches {high}% and back on when it drops to {low}%, so the battery lasts more years.",
           "ram_each": "What each part uses:", "ram_rest": "Android and the rest",
           "plug_error": "⚠️ Can't reach the smart plug ({e}). Is it on and on the Wi-Fi?",
           "latency": "latency", "obstructed": "Sky blocked", "dish_up": "Dish on for", "alerts": "Dish alerts",
           "printer": "Printer", "people": "Who's home", "bk": "Backup", "bk_ok": "photos up to date", "bk_none": "not set up",
           "api_asleep": "⚠️ Can't read the battery: Android put Termux:API to sleep. Run scripts/restart-server.sh with the phone plugged into the computer.",
           "seen": "seen {m} ago", "devices": "Devices",
           "on": "on", "wired": "cable", "no_ip": "connected but the router gave it no address",
           "offline": "offline", "weak": "weak signal",
           "camera": "Cameras", "computer": "Computers", "phone": "Phones", "network": "Network", "other": "Other",
           "backup": "Photo backup",
           "receiving": "receiving {p}%: {gb} GB left ({n} files)", "up_to_date": "up to date ✓",
           "waiting": "{p}%, {gb} GB to go: waiting for the phone (on home Wi-Fi with Syncthing open)",
           "black": "black", "cyan": "cyan", "magenta": "magenta", "yellow": "yellow",
           "all_ok": "Everything works", "internet": "Internet", "details": "Details",
           "net_unknown": "Can't read the dish", "down_now": "download now", "up_now": "upload now",
           "the_plug": "Smart plug",
           "svc": {"SSH": "Remote access", "NextDNS": "Ad blocking", "Luanti": "Kids' game", "Syncthing": "Photo backup",
                   "Cameras": "Cameras", "Recorder": "Recorder", "Panel": "Panel", "Other": "Other"},
           "cpu": "Processor", "cpu_of_max": "of its top speed", "cpu_each": "What each part uses, of the whole:",
           "temp_ok": "normal", "temp_warm": "warm", "temp_hot": "hot", "ram_of": "free of {t}", "of": "of {t}",
           "cpu_note": "Android doesn't let apps see the processor's real use; this is how fast it's running compared with its top speed.",
           "uses_w": "using {w} W", "charges_w": "charging at {w} W",
           "use_note": "The dish reports how much is being used right now, not the top speed of the connection.",
           "net_now_t": "Now", "speed_t": "Speed test", "speed_down": "download", "speed_up": "upload", "test_now": "Test again", "testing": "testing… (about 30 s)",
           "speed_wait": "just tested, try again in a few minutes",
           "speed_by_ip": "open the panel by its IP address, not a name, to test", "speed_fail": "the last test failed",
           "speed_ago": "tested {t} ago", "speed_none": "no speed test yet", "speed_day": "Speed tests, last 24 h",
           "speed_every": "It tests by itself {n} times a day.", "speed_every1": "It tests by itself once a day.",
           "speed_note": "Measured from the server over its own Wi-Fi, against the nearest speedtest.net server; each test moves about 100 MB.",
           "server": "Server", "last_24h": "Last 24 h", "n_of": "{a} of {b} online", "n_home": "{a} of {b} home", "wifi": "Wi-Fi",
           "photos": "Photos", "no_details": "No details while away.",
           "printer_off": "not answering (off?)", "lowest": "lowest: {c} {p}%",
           "day_ago": "24 h ago", "now": "now",
           "p_battery": "battery not read", "p_plug": "smart plug not answering", "p_down": "{s} down",
           "p_hot": "server hot", "p_internet": "internet with alerts", "p_cams": "{n} camera(s) offline",
           "cam_away": "Home only: open {url} on the home Wi-Fi", "no_image": "no image",
           "connecting": "connecting…", "no_video": "Can't show this camera live on this screen",
           "rec": "Recordings", "rec_sum": "{n} today · {gb} GB", "rec_off": "off", "n_cams": "{n} cameras", "not_rec": "not recording", "rec_none": "No clips yet",
           "rec_today": "Today", "rec_yesterday": "Yesterday",
           "rec_cant_play": "This browser can't play these videos (H.265).", "rec_download": "Download",
           "rec_delete": "Delete", "rec_del_one": "Delete this clip? It can't be undone.",
           "rec_del_day": "Delete the whole day", "rec_del_day_q": "Delete the {n} clips ({size}) from {cam}, {day}?", "rec_del_day_q1": "Delete the only clip ({size}) from {cam}, {day}?",
           "rec_del_sure": "It can't be undone. Delete them anyway?", "rec_del_fail": "Couldn't delete it.",
           "dv_router_calls": "the router calls it \"{n}\"", "dv_router_none": "the router gave it no name",
           "dv_name": "Name", "dv_name_ph": "Give it a name", "dv_save": "Save", "dv_forget": "Delete from the list",
           "dv_forget_q": "Delete {n} from the list? If it connects again, it shows up again.",
           "dv_fail": "Couldn't save it.", "dv_away": "This can only be done from home.",
           "p_obstructed": "{cam} looks obstructed, check it ({what})", "p_still_rec": "still recording",
           "p_paused": "recording paused", "p_not_rec": "{cam} not recording", "p_rec_down": "recorder stopped",
           "p_disk_full": "Disk almost full: recording stopped",
           "disk_backup": "Photo backup", "disk_recordings": "Recordings", "disk_free": "Free",
           "p_backup_near": "photo backup near its limit",
           "p_backup_paused": "photo backup paused: at its limit"},
    "es": {"title": "Servidor del cajón", "battery": "Batería", "temp": "Temperatura", "ram": "Memoria RAM",
           "disk": "Espacio libre", "uptime": "prendido hace", "hours": "h", "services": "Servicios",
           "players": "jugando", "nobody": "nadie jugando",
           "charging": "cargando", "not_charging": "a batería", "updated": "actualizado",
           "unplug": "🔌 Batería al {p}%: desenchufá el cargador (entre 30 y 80% dura muchos más años)",
           "plug": "🔌 Batería al {p}%: enchufá el cargador (y sacalo al 80%)",
           "plug_on": "Prendido", "plug_off": "Apagado", "plug_to_high": "carga hasta el {high}%", "plug_to_low": "vuelve a cargar al bajar a {low}%",
           "plug_noanswer": "No contesta", "plug_reach": "conectado", "plug_now": "Ahora",
           "plug_rule": "Se apaga cuando la batería llega al {high}% y se vuelve a prender al bajar a {low}%, así la batería dura más años.",
           "ram_each": "Cuánto usa cada cosa:", "ram_rest": "Android y el resto",
           "plug_error": "⚠️ No puedo hablar con el enchufe ({e}). ¿Está prendido y en el WiFi?",
           "latency": "latencia", "obstructed": "Cielo tapado", "dish_up": "Antena prendida hace", "alerts": "Alertas de la antena",
           "printer": "Impresora", "people": "¿Quién está en casa?", "bk": "Backup", "bk_ok": "fotos al día", "bk_none": "sin activar",
           "api_asleep": "⚠️ No puedo leer la batería: Android durmió a Termux:API. Corré scripts/restart-server.sh con el celu enchufado a la compu.",
           "seen": "visto hace {m}", "devices": "Dispositivos",
           "on": "en", "wired": "cable", "no_ip": "conectado pero el router no le dio dirección",
           "offline": "desconectado", "weak": "señal débil",
           "camera": "Cámaras", "computer": "Computadoras", "phone": "Celulares", "network": "Red", "other": "Otros",
           "backup": "Backup de fotos",
           "receiving": "recibiendo {p}%: faltan {gb} GB ({n} archivos)", "up_to_date": "al día ✓",
           "waiting": "{p}%, faltan {gb} GB: esperando al celu (en el WiFi de casa con Syncthing abierto)",
           "black": "negro", "cyan": "cian", "magenta": "magenta", "yellow": "amarillo",
           "all_ok": "Todo funciona", "internet": "Internet", "details": "Detalles",
           "net_unknown": "No puedo leer la antena", "down_now": "bajada actual", "up_now": "subida actual",
           "the_plug": "Enchufe",
           "svc": {"SSH": "Acceso remoto", "NextDNS": "Bloqueo de publicidad", "Luanti": "Juego de los chicos", "Syncthing": "Backup de fotos",
                   "Cameras": "Cámaras", "Recorder": "Grabador", "Panel": "Panel", "Other": "Otros"},
           "cpu": "Procesador", "cpu_of_max": "de su velocidad máxima", "cpu_each": "Cuánto usa cada cosa, del total:",
           "temp_ok": "normal", "temp_warm": "tibio", "temp_hot": "caliente", "ram_of": "libres de {t}", "of": "de {t}",
           "cpu_note": "Android no deja ver el uso real del procesador; esto es qué tan rápido va comparado con su máximo.",
           "uses_w": "usa {w} W", "charges_w": "carga a {w} W",
           "use_note": "La antena dice cuánto se está usando en este momento, no la velocidad máxima de la conexión.",
           "net_now_t": "Ahora", "speed_t": "Test de velocidad", "speed_down": "bajada", "speed_up": "subida", "test_now": "Medir de nuevo", "testing": "midiendo… (unos 30 s)",
           "speed_wait": "recién se midió, probá en unos minutos",
           "speed_by_ip": "abrí el panel con su dirección IP, no con un nombre, para medir", "speed_fail": "falló la última medición",
           "speed_ago": "medido hace {t}", "speed_none": "todavía sin medir", "speed_day": "Mediciones, últimas 24 h",
           "speed_every": "Mide sola {n} veces por día.", "speed_every1": "Mide sola una vez por día.",
           "speed_note": "Medido desde el server por su propio WiFi, contra el servidor de speedtest.net más cercano; cada medición usa unos 100 MB.",
           "server": "Servidor", "last_24h": "Últimas 24 h", "n_of": "{a} de {b} conectados", "n_home": "{a} de {b} en casa", "wifi": "WiFi",
           "photos": "Fotos", "no_details": "Sin detalles mientras está afuera.",
           "printer_off": "no contesta (¿apagada?)", "lowest": "la más baja: {c} {p}%",
           "day_ago": "hace 24 h", "now": "ahora",
           "p_battery": "no leo la batería", "p_plug": "el enchufe no contesta", "p_down": "{s} caído",
           "p_hot": "server caliente", "p_internet": "internet con alertas", "p_cams": "{n} cámara(s) desconectada(s)",
           "cam_away": "Solo en casa: abrí {url} en el WiFi de casa", "no_image": "sin imagen",
           "connecting": "conectando…", "no_video": "No puedo mostrar esta cámara en vivo en esta pantalla",
           "rec": "Grabaciones", "rec_sum": "{n} hoy · {gb} GB", "rec_off": "desactivadas", "n_cams": "{n} cámaras", "not_rec": "sin grabar", "rec_none": "Todavía no hay clips",
           "rec_today": "Hoy", "rec_yesterday": "Ayer",
           "rec_cant_play": "Este navegador no puede reproducir estos videos (H.265).", "rec_download": "Descargar",
           "rec_delete": "Borrar", "rec_del_one": "¿Borrar este clip? No se puede deshacer.",
           "rec_del_day": "Borrar todo el día", "rec_del_day_q": "¿Borrar los {n} clips ({size}) de {cam} del {day}?", "rec_del_day_q1": "¿Borrar el único clip ({size}) de {cam} del {day}?",
           "rec_del_sure": "No se puede deshacer. ¿Borrar igual?", "rec_del_fail": "No se pudo borrar.",
           "dv_router_calls": "el router lo llama \"{n}\"", "dv_router_none": "el router no le dio nombre",
           "dv_name": "Nombre", "dv_name_ph": "Ponele un nombre", "dv_save": "Guardar", "dv_forget": "Borrar de la lista",
           "dv_forget_q": "¿Borrar {n} de la lista? Si se vuelve a conectar, aparece de nuevo.",
           "dv_fail": "No se pudo guardar.", "dv_away": "Solo se puede desde casa.",
           "p_obstructed": "{cam} parece tapada, revisala ({what})", "p_still_rec": "sigue grabando",
           "p_paused": "grabación en pausa", "p_not_rec": "{cam} no está grabando", "p_rec_down": "el grabador se detuvo",
           "p_disk_full": "Disco casi lleno: se dejó de grabar",
           "disk_backup": "Backup de fotos", "disk_recordings": "Grabaciones", "disk_free": "Libre",
           "p_backup_near": "el backup de fotos está cerca de su límite",
           "p_backup_paused": "backup de fotos en pausa: llegó a su límite"},
}

PAGE = """<!doctype html>
<html lang="__LANG__"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<link rel="manifest" href="/manifest.json">
<link rel="icon" href="/icon-192.png">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<meta name="theme-color" content="#2563eb">
<style>
  :root { --bg:#f6f7f9; --card:#fff; --ink:#1d2330; --muted:#6b7280; --ok:#16a34a; --bad:#dc2626; --warn:#d97706; --line:#2563eb; --soft:#8882; }
  @media (prefers-color-scheme: dark) { :root { --bg:#0f1218; --card:#181c24; --ink:#e6e8ee; --muted:#9aa3b2; --line:#60a5fa; } }
  * { box-sizing:border-box; }
  body { margin:0; padding:16px; background:var(--bg); color:var(--ink); font:16px/1.4 system-ui, sans-serif; }
  main { max-width:760px; margin:0 auto; display:flex; flex-direction:column; gap:12px; }
  header { display:flex; justify-content:space-between; align-items:baseline; flex-wrap:wrap; gap:4px 16px; }
  h1 { font-size:24px; margin:0; }
  .overall { font-weight:600; }
  .overall.ok { color:var(--ok); } .overall.bad { color:var(--warn); }
  .grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); gap:12px; }
  .card { background:var(--card); border-radius:14px; padding:14px; box-shadow:0 1px 3px #0001; }
  .label { color:var(--muted); font-size:13px; }
  .big { font-size:30px; font-weight:700; font-variant-numeric:tabular-nums; }
  .sub { color:var(--muted); font-size:13px; }
  .svc { display:flex; justify-content:space-between; gap:8px; padding:6px 0; border-bottom:1px solid var(--soft); }
  .svc:last-child { border:0; }
  .svc > span:first-child { display:flex; align-items:center; flex-shrink:0; max-width:60%; }
  .svc > .sub { text-align:right; min-width:0; }
  .dot { display:inline-block; flex:none; width:10px; height:10px; border-radius:50%; margin-right:8px; }
  .wide { grid-column:1 / -1; }
  svg { width:100%; height:120px; display:block; }
  .axis { display:flex; justify-content:space-between; }
  .foot { color:var(--muted); font-size:12px; text-align:center; }
  .alert { background:#fef3c7; color:#78350f; border-radius:14px; padding:12px 14px; font-weight:600; }
  .alert:empty { display:none; }
  .ink { display:flex; gap:6px; margin-top:6px; }
  .ink > div { flex:1; min-width:0; text-align:center; font-size:12px; color:var(--muted); font-variant-numeric:tabular-nums; }
  .tank { background:var(--soft); border-radius:6px; position:relative; height:60px; overflow:hidden; margin-bottom:4px; }
  .tank i { position:absolute; bottom:0; left:0; right:0; border-radius:6px; }
  .hidden { display:none; }
  .tabs { display:flex; gap:4px; background:var(--soft); border-radius:10px; padding:3px; margin:0 0 12px; font-size:14px; font-weight:600; }
  .tabs > * { flex:1; text-align:center; padding:6px; border-radius:8px; color:var(--muted); text-decoration:none; }
  .tabs .on { background:var(--card); color:var(--ink); box-shadow:0 1px 2px #0002; }
  .bar { background:var(--soft); border-radius:4px; height:6px; overflow:hidden; margin:2px 0 6px; }
  .bar i { display:block; height:100%; background:var(--ok); }
  details { border-bottom:1px solid var(--soft); }
  details:last-child, .card > details { border:0; }
  summary { list-style:none; cursor:pointer; display:flex; align-items:center; gap:8px; padding:8px 0; }
  summary::-webkit-details-marker { display:none; }
  summary::after { content:'›'; color:var(--muted); font-size:20px; line-height:1; transition:transform .15s; }
  details[open] > summary::after { transform:rotate(90deg); }
  .right { margin-left:auto; text-align:right; }
  /* internet: what the dish says now | the last speed test, each under its own small heading */
  .net { display:grid; grid-template-columns:auto auto 1fr; grid-template-areas:"a b ." "f f f"; gap:0 24px; margin-top:8px; }
  /* Details takes the whole last row (opened, its notes use the full width); the test's time sits on top of it,
     level with "Details" and under the speed test */
  .net .a { grid-area:a; } .net .b { grid-area:b; } .net .foot-a { grid-area:f; } .net .foot-b { grid-row:f; grid-column:2; }
  .net .b { border-left:1px solid var(--soft); padding-left:24px; }
  .net .foot-b { padding-left:24px; }  /* lines up with the speed test above it */
  .net:has(> .a.hidden) :is(.b, .foot-b) { border-left:0; padding-left:0; }
  .net .b .stats { align-items:center; }
  .net .foot-b:not(.hidden) { display:flex; align-items:center; align-self:start; min-height:34px; }  /* level with "Details" */
  .net details { border:0; }
  .net:has(> .a.hidden) { grid-template-areas:"b b ." "f f f"; }
  .hd2 { font-size:12px; color:var(--muted); text-transform:uppercase; letter-spacing:.04em; margin-bottom:2px; }
  @media (max-width:599px) {
    .net { grid-template-columns:auto 1fr; grid-template-areas:"a a" "b b" "f f"; }
    .net .b { border-left:0; padding-left:0; border-top:1px solid var(--soft); padding-top:10px; margin-top:10px; }
    .net:has(> .a.hidden) { grid-template-areas:"b b" "f f"; }
    .net:has(> .a.hidden) .b { border-top:0; padding-top:0; margin-top:0; }
    .net .b .stats { column-gap:14px; }
    .net .foot-b { justify-content:flex-end; padding-left:0; }
    .cams .cam .name { font-size:11px; left:4px; bottom:4px; padding:1px 5px; }
  }
  .pair { display:grid; gap:12px; }
  .pair:not(:has(> section:not(.hidden))) { display:none; }
  @media (min-width:900px) {
    main { max-width:1180px; }
    .pair { grid-template-columns:1fr 1fr; align-items:start; }
    .pair:has(> section.hidden) > section { grid-column:1 / -1; }
  }
  #srv .grid { grid-auto-flow:dense; }  /* an opened card spans the row; the small ones fill the gap it leaves */
  /* server cards in tidy rows: two of three on mid screens, one of six on wide ones
     (auto-fit would keep an empty column there for the wide cards to span) */
  @media (min-width:600px) and (max-width:1099px) {
    #srv .grid { grid-template-columns:repeat(3, 1fr); }
  }
  @media (min-width:1100px) {
    #srv .grid { grid-template-columns:repeat(6, 1fr); }
    #srv .grid:has(> #plugbox.hidden) { grid-template-columns:repeat(5, 1fr); }
  }
  /* every section folds from its heading; folded, the heading shows a one-line summary */
  .sec-h { display:flex; align-items:center; gap:8px; cursor:pointer; user-select:none; }
  .sec-h > :first-child { flex:1; }
  .sec-h::after { content:'›'; color:var(--muted); font-size:20px; line-height:1; transition:transform .15s; }
  /* the whole heading row is the tap target, edge to edge of its card */
  .sec > .sec-h { margin:-14px; padding:14px; min-height:48px; }
  .sec:not(.shut) > .sec-h { margin-bottom:0; padding-bottom:4px; }
  .sec:not(.shut) > .sec-h::after { transform:rotate(90deg); }
  .sec.shut > :not(.sec-h), .sec:not(.shut) .sum, .sec.shut .open-only { display:none !important; }
  .sec-h:focus-visible, summary:focus-visible { outline:2px solid var(--line); outline-offset:2px; border-radius:6px; }
  .stats { display:flex; flex-wrap:wrap; gap:4px 20px; }
  .stats .big { font-size:26px; }
  .unit { font-size:15px; font-weight:600; color:var(--muted); }
  .more { padding:0 0 8px 18px; }
  #srv .grid > .card:has(> details[open]) { grid-column:1 / -1; }  /* an opened tile takes the whole row */
  /* the server's cards sit inside its section, a shade off the card */
  #srv .grid { margin-top:8px; }
  #srv .grid > .card { background:var(--bg); box-shadow:none; }
  #srv .grid > .card:not(.hidden) { display:flex; flex-direction:column; }  /* :not so .hidden still hides */
  #srv .grid > .card > details, #srv .grid > .card > .bottom { margin-top:auto; }
  .bottom { padding-top:8px; }
  .chartbox { position:relative; margin-top:4px; }
  .more.wide-more { padding-left:0; }
  .chartbox .y { position:absolute; right:0; transform:translateY(-50%); font-size:11px; color:var(--muted); background:var(--bg); padding:0 3px; }
  .recs { border-top:1px solid var(--soft); margin-top:12px; padding-top:4px; }
  .recs .svc { border:0; padding:8px 0; }
  .chips { display:flex; flex-wrap:wrap; gap:6px 14px; margin-top:6px; }
  .chips > span { display:inline-flex; align-items:center; }
  .chips .sub { margin-left:4px; }
  button.link { background:none; border:0; padding:0; margin-top:6px; color:var(--line); font:inherit; font-size:13px; cursor:pointer; }
  button.pill { align-self:flex-start; background:var(--soft); border-radius:999px; padding:8px 14px; margin:6px 0 0; }
  button.pill:disabled { color:var(--muted); cursor:default; }
  .dvr { cursor:pointer; }
  .dvr.sel { background:var(--soft); border-radius:8px 8px 0 0; margin:0 -8px; padding:6px 8px; border-bottom:0; }
  .dvx { background:var(--soft); border-radius:0 0 8px 8px; margin:0 -8px 6px; padding:2px 8px 10px; }
  .dvx .sub { font-size:12px; overflow-wrap:anywhere; }
  .dvx form { display:flex; gap:8px; margin:8px 0 0; }
  .dvx input { flex:1; min-width:0; font:inherit; padding:7px 10px; border-radius:8px; border:1px solid #8885; background:var(--card); color:var(--ink); }
  .dvx button.pill { margin:0; border:0; font:inherit; font-size:14px; color:var(--ink); cursor:pointer; }
  .dvx button.save { background:var(--line); color:#fff; }
  .dvx button.del { margin-top:8px; color:var(--bad); background:var(--card); }
  .net button.pill { margin:0 0 0 auto; }
  .cams { display:grid; grid-template-columns:repeat(auto-fit, minmax(100px, 1fr)); gap:8px; margin-top:8px; }
  .cam { position:relative; aspect-ratio:16/9; background:var(--soft); border:0; border-radius:10px; padding:0; overflow:hidden; cursor:pointer; }
  .cam img { position:absolute; inset:0; width:100%; height:100%; object-fit:cover; }
  .cam .none { position:absolute; inset:0; display:flex; align-items:center; justify-content:center; color:var(--muted); font-size:13px; }
  .cam .name { position:absolute; left:6px; bottom:6px; background:#0009; color:#fff; font-size:12px; padding:2px 7px; border-radius:6px; }
  .live { position:fixed; inset:0; z-index:10; background:#000; color:#fff; display:flex; flex-direction:column; }
  .live.hidden { display:none; }
  .live_top { display:flex; align-items:center; justify-content:space-between; padding:8px 14px; }
  .live_top button { background:none; border:0; color:#fff; font-size:26px; cursor:pointer; }
  #clip_del { font-size:20px; margin-right:14px; }
  .live_view { flex:1; position:relative; overflow:hidden; touch-action:none; }
  .live_view video { width:100%; height:100%; object-fit:contain; transform-origin:0 0; }
  .live_msg { position:absolute; inset:0; display:flex; align-items:center; justify-content:center; color:#ccc; pointer-events:none; }
  .nav { position:absolute; top:50%; transform:translateY(-50%); width:48px; height:48px; border:0; border-radius:50%;
         background:#0007; color:#fff; font-size:20px; cursor:pointer; }
  .nav.prev { left:8px; } .nav.next { right:8px; }
  .picks { display:flex; flex-wrap:wrap; gap:6px; margin-top:6px; }
  button.pick { background:var(--soft); color:var(--ink); border:0; border-radius:8px; padding:6px 12px; font:inherit; font-size:13px; cursor:pointer; }
  button.pick.on { background:var(--line); color:#fff; }
  .clips { display:grid; grid-template-columns:repeat(auto-fill, minmax(100px, 1fr)); gap:8px; margin-top:10px; }
  .clip { position:relative; aspect-ratio:16/9; background:var(--soft); border:0; border-radius:8px; padding:0; overflow:hidden; cursor:pointer; }
  .clip img { position:absolute; inset:0; width:100%; height:100%; object-fit:cover; }
  .clip .name { position:absolute; left:4px; bottom:4px; background:#0009; color:#fff; font-size:11px; padding:1px 6px; border-radius:6px; }
  .live_msg.col { flex-direction:column; gap:10px; text-align:center; padding:0 24px; }
  .live_msg a { color:#fff; pointer-events:auto; }
  .home_link a { color:var(--line); }
</style></head>
<body><main>
<nav class="tabs hidden" id="tabs"></nav>
<header><h1>🏡 __TITLE__</h1><div class="overall" id="overall"></div></header>
<div class="alert" id="alert"></div>

<section class="card sec hidden" id="net">
  <div class="sec-h" data-s="net" role="button" tabindex="0"><span class="label">🌐 __INTERNET__</span><span class="sub right sum" id="net_sum"></span></div>
  <div class="net">
    <div class="a" id="net_now"><div class="hd2">__NET_NOW_T__</div><div class="stats">
      <div><div class="big" id="net_lat">–</div><div class="sub">__LATENCY__</div></div>
      <div><div class="big" id="net_down">–</div><div class="sub">⬇ __DOWN_NOW__</div></div>
      <div><div class="big" id="net_up">–</div><div class="sub">⬆ __UP_NOW__</div></div></div></div>
    <div class="b hidden" id="net_speed"><div class="hd2">🚀 __SPEED_T__</div><div class="stats">
      <div><div class="big" id="sp_down">–</div><div class="sub">⬇ __SPEED_DOWN__</div></div>
      <div><div class="big" id="sp_up">–</div><div class="sub">⬆ __SPEED_UP__</div></div>
      <button class="link pill" id="speed_btn">__TEST_NOW__</button></div></div>
    <details class="foot-a" data-k="net"><summary class="sub">__DETAILS__</summary><div class="more" id="net_more"></div></details>
    <div class="foot-b hidden" id="net_line"><span class="sub" id="speed_last"></span></div>
  </div>
</section>

<section class="card sec hidden" id="cams"><div class="sec-h" data-s="cams" role="button" tabindex="0"><span class="label">📹 __CAMERA__</span><span class="sub right sum" id="cams_sum"></span></div>
  <div class="cams" id="cam_grid"></div><div class="sub home_link hidden" id="cam_away"></div>
  <div class="recs hidden" id="rc"><details data-k="rec" id="rc_det"><summary><span>🎞️ __REC__</span><span class="sub right" id="rc_sum"></span></summary>
    <div class="more" id="rc_body"></div><div class="sub more home_link hidden" id="rc_away"></div></details>
    <div class="svc hidden" id="rc_off"><span>🎞️ __REC__</span><span class="sub">__REC_OFF__</span></div></div></section>
<div class="live hidden" id="clip">
  <div class="live_top"><b id="clip_name"></b><span><button id="clip_del" aria-label="__REC_DELETE__" title="__REC_DELETE__">🗑️</button>
    <button id="clip_close" aria-label="close">✕</button></span></div>
  <div class="live_view" id="clip_view"><video id="clip_video" controls autoplay playsinline></video><div class="live_msg col" id="clip_msg"></div>
    <button class="nav prev" id="clip_prev" aria-label="previous">◀</button><button class="nav next" id="clip_next" aria-label="next">▶</button></div>
</div>
<div class="live hidden" id="live">
  <div class="live_top"><b id="live_name"></b><button id="live_close" aria-label="close">✕</button></div>
  <div class="live_view" id="live_view"><div class="live_msg" id="live_msg"></div>
    <button class="nav prev" id="live_prev" aria-label="previous">◀</button><button class="nav next" id="live_next" aria-label="next">▶</button></div>
</div>

<div class="pair"><section class="card sec hidden" id="pp"><div class="sec-h" data-s="pp" role="button" tabindex="0"><span class="label">🏠 __PEOPLE__</span><span class="sub right sum" id="pp_sum"></span></div><div id="pp_list"></div></section>
<section class="card sec hidden" id="bk"><div class="sec-h" data-s="bk" role="button" tabindex="0"><span class="label">📷 __BACKUP__</span><span class="sub right sum" id="bk_sum"></span></div><div id="bk_list"></div></section></div>

<section class="card sec" id="srv"><div class="sec-h" data-s="srv" role="button" tabindex="0"><span class="label">🖥️ __SERVER__</span>
  <span class="sub right sum" id="srv_sum"></span><span class="sub right open-only" id="srv_wifi"></span></div>
<div class="grid">
  <div class="card"><div class="label">🔋 __BATTERY__</div><div class="big" id="bat">–</div><div class="sub" id="batsub"></div>
    <details data-k="bat"><summary class="sub">__DETAILS__</summary><div class="more wide-more"><div class="label">📈 __LAST_24H__</div>
      <div class="chartbox"><svg id="chart" viewBox="0 0 300 100" preserveAspectRatio="none"></svg><span class="y" id="chart_hi"></span><span class="y" id="chart_lo"></span></div>
      <div class="axis sub"><span>__DAY_AGO__</span><span>__NOW__</span></div></div></details></div>
  <div class="card"><div class="label">🌡️ __TEMP__</div><div class="big" id="temp">–</div><div class="sub" id="tempsub"></div>
    <details data-k="temp"><summary class="sub">__DETAILS__</summary><div class="more wide-more"><div class="label">📈 __LAST_24H__</div>
      <div class="chartbox"><svg id="tchart" viewBox="0 0 300 100" preserveAspectRatio="none"></svg><span class="y" id="tchart_hi"></span><span class="y" id="tchart_lo"></span></div>
      <div class="axis sub"><span>__DAY_AGO__</span><span>__NOW__</span></div></div></details></div>
  <div class="card"><div class="label">📊 __CPU__</div><div class="big" id="cpu">–</div>
    <div class="bar"><i id="cpu_bar" style="width:0"></i></div><div class="sub">__CPU_OF_MAX__</div>
    <details data-k="cpu" id="cpu_det"><summary class="sub">__DETAILS__</summary><div class="more" id="cpu_more"></div></details></div>
  <div class="card"><div class="label">🧠 __RAM__</div><div class="big" id="ram">–</div><div class="sub" id="ramsub"></div>
    <details data-k="ram"><summary class="sub">__DETAILS__</summary><div class="more" id="ram_more"></div></details></div>
  <div class="card"><div class="label">💾 __DISK__</div><div class="big" id="disk">–</div><div class="sub" id="disksub"></div>
    <details data-k="disk" class="hidden" id="disk_det"><summary class="sub">__DETAILS__</summary><div class="more" id="disk_more"></div></details></div>
  <div class="card hidden" id="plugbox"><div class="label">🔌 __THE_PLUG__</div><div class="big" id="plug">–</div><div class="sub" id="plugsub"></div>
    <details data-k="plug"><summary class="sub">__DETAILS__</summary><div class="more" id="plug_more"></div></details></div>
  <div class="card wide"><div class="axis"><span class="label">⚙️ __SERVICES__</span><span class="sub" id="up"></span></div><div class="chips" id="svcs"></div></div>
</div></section>

<section class="card sec hidden" id="dv"><div class="sec-h" data-s="dv" role="button" tabindex="0"><span class="label" id="dv_title"></span><span class="sub right sum" id="dv_sum"></span></div><div id="dv_list"></div></section>
<section class="card sec hidden" id="pr"><div class="sec-h" data-s="pr" role="button" tabindex="0"><span class="label">🖨️ __PRINTER__</span><span class="sub right sum" id="pr_sum"></span></div>
  <div class="ink" id="pr_ink"></div></section>
<div class="foot" id="foot"></div>
</main>
<script>
const T = __TEXT__;
const LANG = document.documentElement.lang;
const $ = id => document.getElementById(id);
// names come from config files, game logs and other phones: never insert them as HTML
const esc = v => String(v).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const ago = m => m < 60 ? m + ' min' : m < 2880 ? Math.round(m / 60) + ' h' : Math.round(m / 1440) + (LANG === 'es' ? ' días' : ' days');
const num = (v, d) => Number(v).toLocaleString(LANG, d == null ? {} : {minimumFractionDigits: d, maximumFractionDigits: d});
// tabs to other pages (PANEL_TABS): opened by a home address, link to their home address; else their away one
const TABS = __TABS__;
if (TABS.length) {
  const h = location.hostname, [a, b] = h.split('.').map(Number);
  const atHome = h === 'localhost' || a === 10 || a === 127 || (a === 192 && b === 168) || (a === 172 && b >= 16 && b <= 31);
  for (const t of TABS) {
    const el = document.createElement(t.self ? 'span' : 'a');
    el.textContent = t.label;
    if (t.self) { el.className = 'on'; el.setAttribute('aria-current', 'page'); } else el.href = atHome ? t.home : t.away;
    $('tabs').append(el);
  }
  $('tabs').classList.remove('hidden');
}
const OK = 'var(--ok)', BAD = 'var(--bad)', WARN = 'var(--warn)', OFF = 'var(--muted)';
const dot = c => `<span class="dot" style="background:${c}"></span>`;
const row = (a, b, style) => `<div class="svc"><span>${a}</span><span class="sub"${style ? ` style="${style}"` : ''}>${b}</span></div>`;
function show(id, on) { $(id).classList.toggle('hidden', !on); }
// rebuilding a list only when it changed keeps taps and scroll steady across the 10 s refresh
function set(id, html) { if ($(id).dataset.html !== html) { $(id).innerHTML = html; $(id).dataset.html = html; } }

// which sections are open survives the refresh, and a reload when the browser keeps storage
let open = new Set();
try { open = new Set(JSON.parse(localStorage.getItem('open') || '[]')); } catch (e) {}
function remember(k, on) {
  on ? open.add(k) : open.delete(k);
  try { localStorage.setItem('open', JSON.stringify([...open])); } catch (e) {}
}
document.addEventListener('toggle', e => { if (e.target.dataset.k) remember(e.target.dataset.k, e.target.open); }, true);
document.querySelectorAll('details[data-k]').forEach(d => { d.open = open.has(d.dataset.k); });
const fold = (k, summary, body) =>
  `<details data-k="${esc(k)}"${open.has(k) ? ' open' : ''}><summary>${summary}</summary><div class="more">${body}</div></details>`;
// folded sections, remembered like the open details; everything but the printer starts unfolded
let shut = new Set(['pr']);
try { shut = new Set(JSON.parse(localStorage.getItem('shut') || '["pr"]')); } catch (e) {}
const isShut = k => shut.has(k);
function shutSection(k, on) {
  on ? shut.add(k) : shut.delete(k);
  try { localStorage.setItem('shut', JSON.stringify([...shut])); } catch (e) {}
  const h = document.querySelector(`.sec-h[data-s="${k}"]`);
  h.closest('.sec').classList.toggle('shut', on);
  h.setAttribute('aria-expanded', String(!on));
  if (k === 'cams' && !on) stills();
}
document.querySelectorAll('.sec-h').forEach(h => {
  const k = h.dataset.s;
  h.closest('.sec').classList.toggle('shut', isShut(k));
  h.setAttribute('aria-expanded', String(!isShut(k)));
  h.onclick = () => shutSection(k, !isShut(k));
  h.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); h.click(); } };
});

async function refresh() {
  try {
    const s = await (await fetch('/api/status')).json();
    const h = s.home || {}, b = s.battery || {}, sp = s.plug;
    $('bat').textContent = b.percentage != null ? b.percentage + '%' : '–';
    const w = s.system && s.system.watts, wt = k => w != null ? T[k].replace('{w}', num(w, 1)) : '';
    // the current's sign differs between phones, so "charging at" goes by what Android says it is doing
    $('batsub').textContent = b.plugged && b.plugged !== 'UNPLUGGED' ? '⚡ ' + (b.status === 'CHARGING' && wt('charges_w') || T.charging)
                            : wt('uses_w') || T.not_charging;
    const t = b.temperature;
    $('temp').textContent = t != null ? num(t, 1) + ' °C' : '–';
    $('temp').style.color = t == null ? '' : t >= 40 ? BAD : t >= 35 ? WARN : '';
    $('tempsub').textContent = t == null ? '' : t >= 40 ? T.temp_hot : t >= 35 ? T.temp_warm : T.temp_ok;
    $('ram').textContent = num(s.memory.available_mb / 1024, 1) + ' GB';
    $('ramsub').textContent = T.ram_of.replace('{t}', num(s.memory.total_mb / 1024, 1) + ' GB');
    $('disk').textContent = num(s.disk.free_gb) + ' GB';
    $('disksub').textContent = T.of.replace('{t}', num(s.disk.total_gb) + ' GB');
    drawDisk(s.disk);
    drawCpu(s.system);
    $('up').textContent = s.uptime_h != null ? T.uptime + ' ' + ago(Math.round(s.uptime_h * 60)) : '';
    set('svcs', s.services.map(v => {
      let detail = '';
      if (v.players) detail = v.players.length ? ' · ' + v.players.length + ' ' + T.players + ': ' + esc(v.players.join(', ')) : ' · ' + T.nobody;
      return `<span>${dot(v.ok ? OK : BAD)}${T.svc[v.name] || v.name}<span class="sub">${detail}</span></span>`;
    }).join(''));
    drawCharts(s.history, sp);
    drawRam(s.memory, s.system);
    drawPlug(sp, h.devices, s.plug_ip);
    // charge-cycling reminder, unless a smart plug does it automatically
    const p = b.percentage, plugged = b.plugged && b.plugged !== 'UNPLUGGED';
    $('alert').textContent = s.battery_stale ? T.api_asleep
                           : sp && sp.error ? T.plug_error.replace('{e}', sp.error)
                           : sp ? ''
                           : p == null ? '' : plugged && p >= 80 ? T.unplug.replace('{p}', p)
                           : !plugged && p <= 30 ? T.plug.replace('{p}', p) : '';
    const people = Array.isArray(h.people) ? h.people : null;
    drawInternet(h.starlink, s.speed, s.time);
    drawCameras(s.cameras, s.self_ip);
    drawRecordings(s.recordings, s.recorder, s.self_ip);
    show('cams', s.cameras || (s.recordings && !s.recordings.off));  // recordings live in this card
    drawPeople(people, h);
    drawServerWifi(h.devices, s.self_ip);
    dvHome = s.at_home;
    drawDevices(h.devices, (people ? people.map(x => x.ip) : []).concat([s.self_ip, s.plug_ip]));
    drawPrinter(h.printer);
    drawOverall(s, h);
    drawSums(s, h);
    $('foot').textContent = T.updated + ' ' + new Date(s.time * 1000).toLocaleTimeString(LANG);
  } catch (e) { $('foot').textContent = '⚠️ ' + e; }
}

// how the disk is split: one row per kind (size, share and a bar), then what is free
function drawDisk(d) {
  const kinds = d.kinds || [];
  show('disk_det', kinds.length);
  set('disk_more', kinds.map(k => {
    const pct = k.share_gb ? Math.round(k.gb * 100 / k.share_gb) : null;
    const bad = k.kind === 'backup' && d.warn;
    return row(T['disk_' + k.kind] || esc(k.kind), pct == null ? num(k.gb, 1) + ' GB'
      : num(k.gb, 1) + ' / ' + num(k.share_gb, 1) + ' GB (' + pct + '%)', bad ? 'color:var(--bad)' : '') +
      (pct == null ? '' : `<div class="bar"><i style="width:${Math.min(100, pct)}%${bad ? ';background:var(--bad)' : ''}"></i></div>`);
  }).join('') + row(T.disk_free, num(d.free_gb, 1) + ' GB'));
}

// clock-based figure (Android hides real CPU use), then each of our services' share of the whole
function drawCpu(y) {
  const p = y ? y.cpu_pct : null;
  $('cpu').textContent = p != null ? p + '%' : '–';
  $('cpu').style.color = p == null ? '' : p >= 95 ? BAD : p >= 80 ? WARN : '';
  $('cpu_bar').style.width = (p || 0) + '%';
  if (!y) return;
  set('cpu_more', `<div class="sub" style="margin:4px 0 2px">${T.cpu_each}</div>` +
    (y.services || []).map(v => row(T.svc[v.name] || esc(v.name), num(v.cpu_pct, 1) + '%') +
      `<div class="bar"><i style="width:${Math.min(100, v.cpu_pct)}%"></i></div>`).join('') +
    `<div class="sub" style="margin-top:6px">${T.cpu_note}</div>`);
}

// what a folded section shows in its heading
function drawSums(s, h) {
  const sl = h.starlink, last = s.speed && s.speed.last, b = s.battery || {}, cpu = s.system && s.system.cpu_pct;
  $('net_sum').textContent = [sl && !sl.error ? sl.latency_ms + ' ms' : '', last ? '🚀 ⬇ ' + mb(last[1]) + ' Mbps' : '']
    .filter(Boolean).join(' · ');
  const rc = s.recorder, rs = s.recordings;
  $('cams_sum').textContent = !s.cameras ? '' : [T.n_cams.replace('{n}', s.cameras.names.length),
    rc ? T.rec_sum.replace('{n}', rc.today).replace('{gb}', num(rc.bytes / 1e9, 1)) : rs ? T.not_rec : ''].filter(Boolean).join(' · ');
  const people = Array.isArray(h.people) ? h.people : [];
  $('pp_sum').textContent = T.n_home.replace('{a}', people.filter(x => x.home).length).replace('{b}', people.length);
  $('srv_sum').textContent = [b.percentage != null ? '🔋 ' + b.percentage + '%' : '', b.temperature != null ? num(b.temperature, 1) + ' °C' : '',
    cpu != null ? T.cpu.toLowerCase() + ' ' + cpu + '%' : ''].filter(Boolean).join(' · ');
}

function drawOverall(s, h) {
  const probs = [], t = (s.battery || {}).temperature, sl = h.starlink;
  if (s.battery_stale) probs.push(T.p_battery);
  if (s.plug && s.plug.error) probs.push(T.p_plug);
  // the recorder has its own message below ("recorder stopped"), so its service dot doesn't add a second one
  s.services.filter(v => !v.ok && v.name !== 'Recorder').forEach(v => probs.push(T.p_down.replace('{s}', T.svc[v.name] || v.name)));
  if (t >= 40) probs.push(T.p_hot);
  if (sl && (sl.error || sl.alerts.length)) probs.push(T.p_internet);
  const cams = ((h.devices || {}).devices || []).filter(d => d.kind === 'camera' && !d.online).length;
  if (cams) probs.push(T.p_cams.replace('{n}', cams));
  const rc = s.recorder;
  if (rc && rc.stale) probs.push(T.p_rec_down);  // its last state is old news: only this message
  else if (rc) {
    (rc.cameras || []).forEach(c => {  // a camera that is "off" is off on purpose: no warning
      if (c.state === 'offline') probs.push(T.p_not_rec.replace('{cam}', c.name));
      else if (c.obstructed) probs.push(T.p_obstructed.replace('{cam}', c.name).replace('{what}', c.state === 'paused' ? T.p_paused : T.p_still_rec));
    });
    if (rc.disk_full) probs.push(T.p_disk_full);
  }
  if (s.disk.warn) probs.push(s.disk.warn === 'paused' ? T.p_backup_paused : T.p_backup_near);
  $('overall').textContent = probs.length ? '⚠️ '+ probs.join(' · ') : '✓ ' + T.all_ok;
  $('overall').className = 'overall ' + (probs.length ? 'bad' : 'ok');
}

function drawInternet(sl, sp, now) {
  show('net', sl || sp);
  show('net_now', sl);
  drawSpeed(sp, now);
  if (!sl) { set('net_more', speedRows(sp)); return; }
  if (sl.error) {
    ['net_lat', 'net_down', 'net_up'].forEach(id => set(id, '–'));
    set('net_more', `<div class="sub" style="color:var(--bad)">⚠️ ${T.net_unknown}: ${esc(sl.error)}</div>` + speedRows(sp));
    return;
  }
  const unit = u => ` <span class="unit">${u}</span>`;
  set('net_lat', sl.latency_ms + unit('ms'));
  set('net_down', mb(sl.down_mbps) + unit('Mbps'));
  set('net_up', mb(sl.up_mbps) + unit('Mbps'));
  set('net_more', row(T.obstructed, num(sl.obstructed_pct) + '%') + row(T.dish_up, ago(Math.round(sl.uptime_h * 60))) +
    (sl.alerts.length ? row(T.alerts, '⚠️ ' + esc(sl.alerts.join(', ')), 'color:var(--warn)') : '') +
    `<div class="sub" style="padding-top:6px">${T.use_note}</div>` + speedRows(sp));
}

// speed test: the last result on the card, the last 24 h under Details, a button to test now
// a tiny negative reading must not show as "-0,0"
const mb = v => num(Math.max(0, v), 1);
const mbps = r => `⬇ ${mb(r[1])} ⬆ ${mb(r[2])} Mbps · ${r[3]} ms`;
// what the button says after a tap, kept for a while (browser clock); the phone's clock for the rest
let speedMsg = null, speedMsgUntil = 0;
function drawSpeed(sp, now) {
  show('net_speed', sp);
  show('net_line', sp);
  if (!sp) return;
  const l = sp.last, msg = Date.now() < speedMsgUntil ? speedMsg : null;
  const unit = ' <span class="unit">Mbps</span>';
  set('sp_down', l ? mb(l[1]) + unit : '–');
  set('sp_up', l ? mb(l[2]) + unit : '–');
  set('speed_last', sp.error && !sp.running ? `<span style="color:var(--bad)">⚠️ ${T.speed_fail}</span>`
    : l ? T.speed_ago.replace('{t}', ago(Math.max(0, Math.round((now - l[0]) / 60)))) : T.speed_none);
  const wait = now < sp.next_ok;
  $('speed_btn').textContent = sp.running ? T.testing : msg || (wait ? T.speed_wait : T.test_now);
  $('speed_btn').disabled = sp.running || wait || msg === T.testing;
}
function speedRows(sp) {
  if (!sp) return '';
  const note = (sp.per_day ? (sp.per_day === 1 ? T.speed_every1 : T.speed_every.replace('{n}', sp.per_day)) + ' ' : '') + T.speed_note;
  return `<div class="label" style="padding-top:10px">🚀 ${T.speed_day}</div>` +
    sp.day.slice().reverse().map(r => row(new Date(r[0] * 1000).toLocaleTimeString(LANG, {hour: '2-digit', minute: '2-digit'}), mbps(r))).join('') +
    (sp.error ? `<div class="sub" style="color:var(--bad)">⚠️ ${esc(sp.error)}</div>` : '') +
    `<div class="sub" style="padding-top:6px">${note}</div>`;
}
$('speed_btn').onclick = async () => {
  const say = (m, s) => { speedMsg = m; speedMsgUntil = Date.now() + s * 1000; $('speed_btn').textContent = m; };
  say(T.testing, 10);
  $('speed_btn').disabled = true;
  const r = await fetch('/api/speedtest', {method: 'POST'}).catch(() => null);
  if (!r || r.status === 403) say(T.speed_by_ip, 60);  // opened by a name, not the IP: see same_site()
  else if (r.status === 429) say(T.speed_wait, 60);
  setTimeout(refresh, 2000);
};

// cameras: a still per camera every 2.5 s while the page is visible, tap one for live video
// "Home only: open <link> on the home Wi-Fi", the link being this panel at its home address
function homeOnly(id, selfIp) {
  const url = 'http://' + (selfIp || 'server') + ':' + (location.port || 80);
  const [before, after = ''] = T.cam_away.split('{url}');
  if (!selfIp) { $(id).textContent = before + url + after; return; }  // no address known: no link that goes nowhere
  const a = document.createElement('a');
  a.href = a.textContent = url;
  $(id).textContent = before;
  $(id).append(a, after);
}
let cams = null;
function drawCameras(c, selfIp) {
  cams = c;
  show('cams', c);
  if (!c) return;
  show('cam_grid', c.home);
  show('cam_away', !c.home);
  if (!c.home) {
    homeOnly('cam_away', selfIp);
    return;
  }
  const fresh = !$('cam_grid').dataset.html;
  set('cam_grid', c.names.map((name, i) => `<button class="cam" data-i="${i}"><span class="none">${T.no_image}</span>` +
    `<img alt="" data-n="${i + 1}" style="visibility:hidden"><span class="name">${esc(name)}</span></button>`).join(''));
  if (fresh) stills();
}
function stills() {
  if (!cams || !cams.home || isShut('cams') || document.visibilityState !== 'visible') return;
  document.querySelectorAll('#cam_grid img').forEach(async img => {
    if (img.dataset.busy) return;  // a slow answer must not pile up requests
    img.dataset.busy = 1;
    try {
      const r = await fetch('/api/camera/' + img.dataset.n + '.jpg?t=' + Date.now());
      if (r.status !== 200) { img.style.visibility = 'hidden'; return; }  // 204: no fresh still
      // free the previous picture whatever happens: on a wall tablet this runs all day
      if (img.dataset.url) URL.revokeObjectURL(img.dataset.url);
      img.dataset.url = URL.createObjectURL(await r.blob());
      img.onerror = () => { img.style.visibility = 'hidden'; };
      img.src = img.dataset.url;
      img.style.visibility = '';
    } catch (e) {
      img.style.visibility = 'hidden';
    } finally { delete img.dataset.busy; }
  });
}
setInterval(stills, 2500);
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') stills(); else if (liveAt >= 0) closeLive();
});
$('cam_grid').onclick = e => { const b = e.target.closest('.cam'); if (b) openLive(+b.dataset.i); };

// recordings: nothing is fetched until the section is opened (and again each time it is)
let recHome = false, recLoaded = false, recs = [], recCam = 0, recDay = null, recClips = [], clipAt = -1;
const enc = encodeURIComponent;
const ymd = d => d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
const recUrl = (c, d, f) => '/rec/' + enc(c) + '/' + enc(d) + '/' + enc(f);
// inside the cameras card: a row that says "off" while nothing is recorded, else the clips under a fold
function drawRecordings(r, rc, selfIp) {
  show('rc', r);
  show('rc_off', r && r.off);
  show('rc_det', r && !r.off);
  recHome = !!(r && r.home);
  if (!r || r.off) return;
  $('rc_sum').textContent = rc ? T.rec_sum.replace('{n}', rc.today).replace('{gb}', num(rc.bytes / 1e9, 1)) : T.rec_off;
  show('rc_body', recHome);
  show('rc_away', !recHome);
  if (!recHome) homeOnly('rc_away', selfIp);
  else if ($('rc_det').open) loadRecs();
}
function dayName(d) {
  const t = new Date(), y = new Date(t.getFullYear(), t.getMonth(), t.getDate() - 1);
  return d === ymd(t) ? T.rec_today : d === ymd(y) ? T.rec_yesterday : d;
}
async function loadRecs() {
  if (!recHome || recLoaded) return;
  recLoaded = true;
  try {
    recs = (await (await fetch('/api/recordings')).json()).cameras;
    recCam = Math.max(0, recs.findIndex(c => c.days.length));
    await pickDay(recs.length ? recs[recCam].days[0] || null : null);
  } catch (e) { recLoaded = false; $('rc_body').textContent = '⚠️ ' + e; }
}
async function pickDay(day) {
  recDay = day;
  recClips = [];
  if (day) recClips = (await (await fetch('/api/recordings/' + enc(recs[recCam].folder) + '/' + enc(day))).json()).clips;
  drawRecs();
}
function drawRecs() {
  const cam = recs[recCam];
  if (!cam || !cam.days.length) { $('rc_body').innerHTML = `<div class="sub">${T.rec_none}</div>`; return; }
  const pick = (on, attr, label) => `<button class="pick${on ? ' on' : ''}" ${attr}>${esc(label)}</button>`;
  $('rc_body').innerHTML =
    (recs.length > 1 ? `<div class="picks">${recs.map((c, i) => pick(i === recCam, `data-cam="${i}"`, c.name)).join('')}</div>` : '') +
    `<div class="picks">${cam.days.map(d => pick(d === recDay, `data-day="${esc(d)}"`, dayName(d))).join('')}</div>` +
    (recClips.length ? `<button class="link" data-delday="1">🗑️ ${T.rec_del_day}</button>` : '') +
    (recClips.length ? `<div class="clips">${recClips.map((c, i) => `<button class="clip" data-i="${i}">` +
      (c.thumb ? `<img alt="" loading="lazy" src="${recUrl(cam.folder, recDay, c.file.slice(0, -4) + '.jpg')}">` : '') +
      `<span class="name">${esc(c.time)} · ${c.len}s</span></button>`).join('')}</div>` : `<div class="sub" style="margin-top:8px">${T.rec_none}</div>`);
}
document.addEventListener('toggle', e => {
  if (e.target !== $('rc_det')) return;
  if (e.target.open) loadRecs(); else recLoaded = false;
}, true);
$('rc_body').onclick = async e => {
  const b = e.target.closest('button');
  if (!b) return;
  try {
    if (b.dataset.cam != null) { recCam = +b.dataset.cam; await pickDay(recs[recCam].days[0] || null); }
    else if (b.dataset.day) await pickDay(b.dataset.day);
    else if (b.dataset.delday) await deleteDay();
    else if (b.dataset.i != null) openClip(+b.dataset.i);
  } catch (err) { $('rc_body').textContent = '⚠️ ' + err; }
};

// deleting asks first (twice for a whole day), then the lists reload
async function deleteRec(url) {
  const r = await fetch(url, {method: 'DELETE'}).catch(() => null);
  if (!r || !r.ok) alert(T.rec_del_fail);
  return !!(r && r.ok);
}
async function reloadRecs() {
  const folder = recs[recCam] && recs[recCam].folder, day = recDay;
  recs = (await (await fetch('/api/recordings')).json()).cameras;
  const i = recs.findIndex(c => c.folder === folder);
  recCam = i >= 0 ? i : Math.max(0, recs.findIndex(c => c.days.length));
  const cam = recs[recCam];
  await pickDay(cam ? (cam.days.includes(day) ? day : cam.days[0] || null) : null);
}
async function deleteDay() {
  const b = recClips.reduce((a, c) => a + (c.bytes || 0), 0), size = b >= 1e9 ? num(b / 1e9, 1) + ' GB' : Math.max(1, Math.round(b / 1e6)) + ' MB';
  const when = new Date(recDay + 'T12:00').toLocaleDateString(LANG, {day: 'numeric', month: 'numeric'});
  const q = T[recClips.length === 1 ? 'rec_del_day_q1' : 'rec_del_day_q'].replace('{n}', recClips.length).replace('{size}', size).replace('{cam}', recs[recCam].name).replace('{day}', when);
  if (!confirm(q) || !confirm(T.rec_del_sure)) return;
  if (await deleteRec('/api/recordings/' + enc(recs[recCam].folder) + '/' + enc(recDay))) await reloadRecs();
}
$('clip_del').onclick = async () => {
  const c = recClips[clipAt];
  if (!c || !confirm(T.rec_del_one) || !await deleteRec(recUrl(recs[recCam].folder, recDay, c.file))) return;
  const at = clipAt;
  recClips.splice(at, 1);
  if (recClips.length) { openClip(Math.min(at, recClips.length - 1)); drawRecs(); }
  else { closeClip(); await reloadRecs(); }
};

// clip player: full screen like live view; the back button closes it
function openClip(i) {
  if (!recClips.length) return;
  if (clipAt < 0) history.pushState({clip: 1}, '');
  clipAt = (i + recClips.length) % recClips.length;
  const c = recClips[clipAt], v = $('clip_video');
  show('clip', true);
  $('clip_name').textContent = recs[recCam].name + ' · ' + dayName(recDay) + ' ' + c.time;
  $('clip_msg').textContent = '';
  v.src = recUrl(recs[recCam].folder, recDay, c.file);
  v.play().catch(() => {});  // a blocked autoplay is fine; a broken video fires the error event below
}
$('clip_video').addEventListener('error', () => {
  if (clipAt < 0) return;  // closing empties the source, which fires this too
  const c = recClips[clipAt], msg = $('clip_msg');
  msg.textContent = T.rec_cant_play;
  const a = document.createElement('a');
  a.href = recUrl(recs[recCam].folder, recDay, c.file);
  a.download = c.file;
  a.textContent = T.rec_download;
  msg.append(a);
});
function closeClip(fromBack) {
  const v = $('clip_video');
  clipAt = -1;
  v.pause();
  v.removeAttribute('src');
  v.load();
  show('clip', false);
  if (!fromBack) history.back();
}
window.addEventListener('popstate', () => { if (clipAt >= 0) closeClip(true); });
$('clip_close').onclick = () => closeClip();
$('clip_prev').onclick = () => openClip(clipAt - 1);
$('clip_next').onclick = () => openClip(clipAt + 1);

// live view: go2rtc's player, through the panel (/live/...), one camera at a time
let liveAt = -1, player = null, Player = null;
const zoom = {s: 1, x: 0, y: 0};
async function openLive(i) {
  if (!Player) {
    try {
      const {VideoRTC} = await import('/live/video-rtc.js');
      Player = class extends VideoRTC {};
      customElements.define('cam-live', Player);
    } catch (e) { alert(T.no_video); return; }
  }
  if (liveAt < 0) history.pushState({live: 1}, '');  // the back button closes it
  liveAt = (i + cams.names.length) % cams.names.length;
  show('live', true);
  $('live_name').textContent = cams.names[liveAt];
  play(liveAt + 1, true);
}
function play(n, hd) {
  stopPlayer();
  Object.assign(zoom, {s: 1, x: 0, y: 0});
  $('live_msg').textContent = T.connecting;
  const el = document.createElement('cam-live');
  Object.assign(el, {mode: 'mse', media: 'video', visibilityCheck: false});
  $('live_view').prepend(el);
  el.video.controls = false;
  el.video.muted = true;
  el.src = new URL('/live/ws?src=cam' + n + (hd ? '_hd' : ''), location.href).href;
  player = el;
  // a weak screen can't decode the big stream: drop to the small one. The timer belongs to this
  // player: a closed one still fires events, and must not touch the next one's timer
  const fallback = () => { if (player !== el) return; clearTimeout(el.timer); if (hd) play(n, false); else $('live_msg').textContent = T.no_video; };
  el.video.addEventListener('playing', () => { if (player !== el) return; clearTimeout(el.timer); $('live_msg').textContent = ''; });
  el.video.addEventListener('error', fallback);
  el.timer = setTimeout(fallback, hd ? 5000 : 10000);
}
function stopPlayer() {
  if (!player) return;
  clearTimeout(player.timer);
  player.ondisconnect();
  player.remove();
  player = null;
}
function closeLive(fromBack) {
  stopPlayer();
  show('live', false);
  liveAt = -1;
  if (!fromBack) history.back();
}
window.addEventListener('popstate', () => { if (liveAt >= 0) closeLive(true); });
$('live_close').onclick = () => closeLive();
$('live_prev').onclick = () => openLive(liveAt - 1);
$('live_next').onclick = () => openLive(liveAt + 1);

// pinch to zoom, drag to look around, double-tap to reset, swipe to change camera
const touches = new Map();
let gesture = null, lastTap = 0;
function setZoom() { if (player) player.video.style.transform = `translate(${zoom.x}px,${zoom.y}px) scale(${zoom.s})`; }
function snapshot() {
  const p = [...touches.values()];
  const mid = p.length > 1 ? {x: (p[0].x + p[1].x) / 2, y: (p[0].y + p[1].y) / 2} : p[0];
  const dist = p.length > 1 ? Math.hypot(p[0].x - p[1].x, p[0].y - p[1].y) : 0;
  return {mid, dist, z: {...zoom}, start: p[0], moved: false, count: p.length};
}
const view = $('live_view');
view.addEventListener('pointerdown', e => {
  if (e.target.closest('button')) return;
  touches.set(e.pointerId, {x: e.clientX, y: e.clientY});
  view.setPointerCapture(e.pointerId);
  gesture = snapshot();
});
view.addEventListener('pointermove', e => {
  if (!touches.has(e.pointerId) || !gesture) return;
  touches.set(e.pointerId, {x: e.clientX, y: e.clientY});
  const now = snapshot(), g = gesture;
  if (Math.hypot(now.mid.x - g.mid.x, now.mid.y - g.mid.y) > 10 || now.count > 1) g.moved = true;
  if (now.count > 1 && g.dist) {
    const s = Math.min(5, Math.max(1, g.z.s * now.dist / g.dist));
    zoom.x = now.mid.x - (g.mid.x - g.z.x) * s / g.z.s;
    zoom.y = now.mid.y - (g.mid.y - g.z.y) * s / g.z.s;
    zoom.s = s;
  } else if (zoom.s > 1) {
    zoom.x = g.z.x + now.mid.x - g.mid.x;
    zoom.y = g.z.y + now.mid.y - g.mid.y;
  }
  if (zoom.s === 1) { zoom.x = 0; zoom.y = 0; }
  setZoom();
});
const lift = e => {
  if (!touches.delete(e.pointerId) || !gesture) return;
  const g = gesture, dx = e.clientX - g.start.x, dy = e.clientY - g.start.y;
  if (touches.size) { gesture = snapshot(); gesture.moved = true; return; }
  gesture = null;
  if (g.count === 1 && zoom.s === 1 && Math.abs(dx) > 60 && Math.abs(dy) < 60) openLive(liveAt + (dx < 0 ? 1 : -1));
  else if (!g.moved) {
    if (Date.now() - lastTap < 300) { Object.assign(zoom, {s: 1, x: 0, y: 0}); setZoom(); }
    lastTap = Date.now();
  }
};
view.addEventListener('pointerup', lift);
view.addEventListener('pointercancel', lift);

function wifiText(d) {
  const weak = d.signal != null && d.signal < -75;
  const ghz = parseFloat(d.conn);
  const how = (d.conn === 'wired' ? T.wired : isNaN(ghz) ? T.wifi : num(ghz) + ' GHz') + (d.signal != null && d.conn !== 'wired' ? ' · ' + d.signal + ' dBm' : '');
  return !d.online ? T.offline + ' · ' + T.seen.replace('{m}', ago(d.seen_min_ago))
       : !d.ip ? '⚠️ ' + T.no_ip
       : esc(d.ip) + ' · ' + how + (weak ? ' ⚠️ ' + T.weak : '');
}

function backupRows(f, mb_s, label) {
  const fill = x => x.replace('{p}', f.pct).replace('{gb}', num(f.need_gb)).replace('{n}', f.need_files);
  const st = !f.need_files ? T.up_to_date
           : f.online ? fill(T.receiving) + (mb_s ? ' · ' + num(mb_s) + ' MB/s' : '') : fill(T.waiting);
  return row(`${dot(f.online ? OK : OFF)}📷 ${label || esc(f.label)}`, st) +
    (f.need_files ? `<div class="bar"><i style="width:${f.pct}%"></i></div>` : '');
}

// each person's phone: home or away, and inside, its Wi-Fi and photo backup
function drawPeople(people, h) {
  const devs = (h.devices || {}).devices || [], bk = h.backup || {}, folders = bk.folders || [];
  const from = f => f.from.split(', ');
  show('pp', people);
  if (people) set('pp_list', people.map(x => {
    const d = devs.find(d => d.last_ip === x.ip), mine = folders.filter(f => from(f).includes(x.name));
    // the dot says home or away; the right side says how the photo backup goes (when the server has one)
    const photos = !h.backup || h.backup.error ? '' : T.bk + ': ' + (!mine.length ? T.bk_none
      : mine.every(f => !f.need_files) ? T.bk_ok : Math.min(...mine.map(f => f.pct)) + '%');
    const seen = !x.home && x.seen_min_ago != null ? `<div class="sub">${T.seen.replace('{m}', ago(x.seen_min_ago))}</div>` : '';
    let body = (d && d.online ? row(T.wifi, wifiText(d)) : '') + mine.map(f => backupRows(f, bk.mb_s, mine.length > 1 ? '' : T.photos)).join('');
    if (!body) body = seen || `<div class="sub">${T.no_details}</div>`;
    return fold('p:' + x.name, `${dot(x.home ? OK : OFF)}<b${x.home ? '' : ' style="color:var(--muted)"'}>${esc(x.name)}</b>` +
      `<span class="sub right">${photos}</span>`, body);
  }).join(''));
  // folders from phones that aren't a person above get their own card
  const names = people ? people.map(x => x.name) : [];
  const rest = folders.filter(f => !from(f).some(n => names.includes(n)));
  show('bk', rest.length);
  set('bk_list', rest.map(f => backupRows(f, bk.mb_s)).join(''));
  $('bk_sum').textContent = !rest.length ? '' : rest.every(f => !f.need_files) ? T.up_to_date : Math.min(...rest.map(f => f.pct)) + '%';
}

// the server's own Wi-Fi, from the router's list, on the right of the Server heading
const routerDev = (dv, ip) => ip && ((dv && dv.devices) || []).find(d => d.last_ip === ip);
function drawServerWifi(dv, ip) {
  const d = routerDev(dv, ip);
  set('srv_wifi', d ? '📶 ' + wifiText(d) : '');
}

// the smart plug's card: on or off, and that the panel can reach it; its rule and Wi-Fi under Details
function drawPlug(sp, dv, ip) {
  show('plugbox', sp);
  if (!sp) return;
  $('plug').textContent = sp.error ? T.plug_noanswer : sp.on ? T.plug_on : T.plug_off;
  $('plug').style.color = sp.error ? BAD : '';
  set('plugsub', sp.error ? '' : dot(OK) + T.plug_reach);
  const d = routerDev(dv, ip);
  set('plug_more', (sp.error ? `<div class="sub" style="color:var(--bad)">⚠️ ${esc(sp.error)}</div>`
      : row(T.plug_now, sp.on ? T.plug_to_high.replace('{high}', sp.high) + (sp.watts != null ? ' · ' + num(sp.watts) + ' W' : '')
                              : T.plug_to_low.replace('{low}', sp.low))) +
    (d ? row(T.wifi, wifiText(d)) : '') +
    (sp.error ? '' : `<div class="sub" style="padding-top:6px">${T.plug_rule.replace('{high}', sp.high).replace('{low}', sp.low)}</div>`));
}

// the RAM tile's details: what each of our services holds, then Android and every other app
function drawRam(m, y) {
  const used = m.total_mb - m.available_mb, svcs = ((y && y.services) || []).slice().sort((a, b) => b.mem_mb - a.mem_mb);
  const ours = svcs.reduce((a, v) => a + v.mem_mb, 0);
  const bar = mb => `<div class="bar"><i style="width:${Math.min(100, mb * 100 / m.total_mb)}%"></i></div>`;
  set('ram_more', `<div class="sub" style="margin:4px 0 2px">${T.ram_each}</div>` +
    svcs.map(v => row(T.svc[v.name] || esc(v.name), v.mem_mb + ' MB') + bar(v.mem_mb)).join('') +
    (used > ours ? row(T.ram_rest, num((used - ours) / 1024, 1) + ' GB') + bar(used - ours) : ''));
}

const KINDS = ['camera', 'computer', 'phone', 'network', 'other'];
const ICON = {camera: '📹', computer: '💻', phone: '📱', network: '🌐', other: '🔌'};
// tapping a device opens a box under it to name it, or to delete it from the list once it's offline
let dvOpen = null, dvLast = [], dvHome = false;
function drawDevices(dv, hide) {
  dvLast = [dv, hide];
  show('dv', dv && dv.devices);
  if (!(dv && dv.devices)) return;
  if (document.activeElement && document.activeElement.closest('.dvx')) return;  // don't redraw under the typing
  // a device that never got an address has no last_ip: never hide it by matching a missing one
  const list = dv.devices.filter(d => !(d.last_ip && hide.includes(d.last_ip)));
  $('dv_title').textContent = '📶 ' + T.devices + (dv.ssid ? ' ' + T.on + ' ' + dv.ssid : '');
  $('dv_sum').textContent = T.n_of.replace('{a}', list.filter(d => d.online).length).replace('{b}', list.length);
  set('dv_list', KINDS.map(k => {
    const g = list.filter(d => d.kind === k);
    if (!g.length) return '';
    const on = g.filter(d => d.online).length, noip = g.some(d => d.online && !d.ip);
    const sum = `${ICON[k]} ${T[k]}<span class="sub right">${T.n_of.replace('{a}', on).replace('{b}', g.length)}` +
      `${k === 'camera' && (on < g.length || noip) ? ' ⚠️' : ''}</span>`;
    return fold('k:' + k, sum, g.map(d => {
      // offline is normal (a phone that left): grey, not red; a weak signal only matters while connected
      const weak = d.online && d.signal != null && d.signal < -75;
      const sel = d.mac === dvOpen;
      return row(dot(d.online && d.ip ? OK : d.online ? WARN : OFF) + esc(d.name), wifiText(d), weak ? 'color:var(--warn)' : '')
        .replace('<div class="svc">', `<div class="svc dvr${sel ? ' sel' : ''}" data-mac="${esc(d.mac)}" role="button" tabindex="0" aria-expanded="${sel}">`) +
        (sel ? deviceBox(d) : '');
    }).join(''));
  }).join(''));
}

function deviceBox(d) {
  const named = d.name !== d.last_ip && d.name !== d.mac;  // without a name the list shows its address
  const info = `<div class="sub">MAC ${esc(d.mac)} · ${d.host ? esc(T.dv_router_calls.replace('{n}', () => d.host)) : T.dv_router_none}</div>`;
  if (!dvHome) return `<div class="dvx">${info}<div class="sub">${T.dv_away}</div></div>`;
  return `<div class="dvx">${info}
    <form data-mac="${esc(d.mac)}"><input maxlength="40" value="${named ? esc(d.name) : ''}" placeholder="${esc(T.dv_name_ph)}" aria-label="${esc(T.dv_name)}">` +
    `<button class="pill save">${T.dv_save}</button></form>` +
    (d.online ? '' : `<button class="pill del" data-mac="${esc(d.mac)}" data-name="${esc(d.name)}">🗑️ ${T.dv_forget}</button>`) + '</div>';
}
async function changeDevice(mac, init) {
  const r = await fetch('/api/devices/' + mac + (init.method === 'POST' ? '/name' : ''), init).catch(() => null);
  if (!r || !r.ok) { alert(r && r.status === 403 ? T.dv_away : T.dv_fail); return; }
  dvOpen = null;
  document.activeElement.blur();
  drawDevices((await r.json()).devices, dvLast[1]);
}
$('dv_list').addEventListener('click', e => {
  const del = e.target.closest('button.del'), r = e.target.closest('.dvr');
  if (del && confirm(T.dv_forget_q.replace('{n}', () => del.dataset.name))) changeDevice(del.dataset.mac, {method: 'DELETE'});
  if (!r) return;
  dvOpen = r.dataset.mac === dvOpen ? null : r.dataset.mac;
  if (document.activeElement) document.activeElement.blur();
  drawDevices(...dvLast);
});
$('dv_list').addEventListener('keydown', e => {
  if (e.target.classList.contains('dvr') && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); e.target.click(); }
});
$('dv_list').addEventListener('submit', e => {
  e.preventDefault();
  changeDevice(e.target.dataset.mac, {method: 'POST', headers: {'Content-Type': 'application/json'},
                                      body: JSON.stringify({name: e.target.querySelector('input').value})});
});

const INK = {black: '#222', cyan: '#06b6d4', magenta: '#d946ef', yellow: '#facc15'};
function drawPrinter(pr) {
  show('pr', pr);
  if (!pr) return;
  const inks = pr.inks || [];
  const low = inks.reduce((a, k) => !a || k.level < a.level ? k : a, null);
  $('pr_sum').textContent = pr.error ? T.printer_off
    : low ? T.lowest.replace('{c}', T[low.color] || low.color).replace('{p}', low.level) : '';
  $('pr_sum').style.color = !pr.error && low && low.level <= 15 ? WARN : '';
  set('pr_ink', inks.map(k =>
    `<div title="${esc(T[k.color] || k.color)}"><div class="tank"><i style="height:${k.level}%;background:${INK[k.color] || '#888'}"></i></div>${k.level}%</div>`).join(''));
}

// one line over the last 24 h, from bottom to top of the scale; two labels on the right
// (the svg stretches, so the labels sit outside it). band = [lo, hi] shaded, or null
function drawLine(id, rows, bottom, top, labels, band, unit) {
  const svg = $(id);
  if (!rows.length) { svg.innerHTML = ''; return; }
  const t0 = rows[0][0], t1 = Math.max(rows[rows.length - 1][0], t0 + 1);
  const x = t => (t - t0) / (t1 - t0) * 300, y = v => 100 - (v - bottom) * 100 / (top - bottom);
  const pts = rows.map(r => x(r[0]).toFixed(1) + ',' + y(r[1]).toFixed(1)).join(' ');
  [['_hi', labels[1]], ['_lo', labels[0]]].forEach(([k, v]) => { $(id + k).textContent = v + unit; $(id + k).style.top = y(v) + '%'; });
  svg.innerHTML = (band ? `<rect x="0" y="${y(band[1])}" width="300" height="${y(band[0]) - y(band[1])}" fill="var(--ok)" opacity="0.08"/>` : '') +
    `<polyline points="${pts}" fill="none" stroke="var(--line)" stroke-width="2" vector-effect="non-scaling-stroke"/>`;
}
function drawCharts(h, plug) {
  const lo = plug && !plug.error ? plug.low : 30, hi = plug && !plug.error ? plug.high : 80;
  drawLine('chart', h.map(r => [r[0], r[1]]), 0, 100, [lo, hi], [lo, hi], '%');   // the healthy charge band
  // temperature: a scale a little wider than the day's lowest and highest (rows without one are 0)
  const t = h.filter(r => r[2] > 0).map(r => [r[0], r[2]]), v = t.map(r => r[1]);
  const min = Math.floor(Math.min(...v)), max = Math.ceil(Math.max(...v));
  if (t.length) drawLine('tchart', t, min - 2, Math.max(max, min + 3) + 2, [min, Math.max(max, min + 3)], null, ' °C');
}
refresh(); setInterval(refresh, 10000);
</script>
</body></html>"""


# the icon for "Add to Home screen"
ICONS = {name: Path(__file__).with_name(name)
         for name in ("icon-192.png", "icon-512.png", "icon-maskable.png", "apple-touch-icon.png")}


def manifest():
    title = CONFIG / "title"
    name = title.read_text().strip() if title.exists() else TEXT.get(LANG, TEXT["en"])["title"]
    return json.dumps({"name": name, "short_name": name, "start_url": "/", "display": "standalone",
                       "background_color": "#f6f7f9", "theme_color": "#2563eb",
                       "icons": [{"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
                                 {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"},
                                 {"src": "/icon-maskable.png", "sizes": "512x512", "type": "image/png",
                                  "purpose": "maskable"}]}).encode()


def tabs():
    """PANEL_TABS in .env (written by scripts/08-panel.sh): Label=self or Label=home-url|away-url per line.
    Fewer than two tabs, or none marked self, shows no tab bar."""
    path = CONFIG / "tabs"
    out = []
    for line in path.read_text().splitlines() if path.exists() else []:
        label, _, target = (part.strip() for part in line.partition("="))
        if not label:
            continue
        if target == "self":
            out.append({"label": label[:40], "self": True})
            continue
        urls = [u.strip() for u in target.split("|")]
        if 1 <= len(urls) <= 2 and all(re.fullmatch(r"https?://[^\s\"'<>]+", u) for u in urls):
            out.append({"label": label[:40], "home": urls[0], "away": urls[-1]})
    return out if len(out) > 1 and any(t.get("self") for t in out) else []


def render():
    text = TEXT.get(LANG, TEXT["en"])
    title = CONFIG / "title"  # PANEL_TITLE in .env, written by scripts/08-panel.sh
    text = dict(text, title=title.read_text().strip() if title.exists() else text["title"])
    page = PAGE.replace("__LANG__", LANG)
    for key, value in text.items():
        if isinstance(value, str):
            page = page.replace(f"__{key.upper()}__", html.escape(value))
    # the JSON goes in last, so a placeholder inside a name is never filled in;
    # "<" escaped so no text can close the <script> it sits in
    return (page.replace("__TEXT__", json.dumps(text).replace("<", "\\u003c"))
            .replace("__TABS__", json.dumps(tabs()).replace("<", "\\u003c")).encode())


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        cam = CAMERA_PATH.fullmatch(self.path)
        live = LIVE_PATH.fullmatch(self.path)
        if cam or live or self.path == "/live/video-rtc.js":
            n = int((cam or live).group(1)) if cam or live else 1
            if not STILLS or n > STILLS.count:
                self.send_error(404)
            elif not is_home(self.client_address[0]) or not self.same_site():
                self.send_error(403)  # cameras are home-only, and only for the panel's own page
            elif cam:
                self.camera(n)
            elif live:
                self.live(self.path.split("=", 1)[1])
            else:
                self.player()
            return
        if self.path.startswith(("/api/recordings", "/rec/")):
            self.recordings()
            return
        if self.path == "/api/status":
            body, kind = json.dumps(status(self.client_address[0])).encode(), "application/json"
        elif self.path in ("/", "/index.html"):
            body, kind = render(), "text/html; charset=utf-8"
        elif self.path == "/manifest.json":
            body, kind = manifest(), "application/manifest+json"
        elif self.path.lstrip("/") in ICONS and ICONS[self.path.lstrip("/")].exists():
            body, kind = ICONS[self.path.lstrip("/")].read_bytes(), "image/png"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path.startswith("/api/devices/"):
            self.device(forget=False)
            return
        # "Test now": only from the panel's own page, so another site can't burn ~100 MB per visit
        if self.path != "/api/speedtest" or speed_per_day() is None:
            self.send_error(404)
        elif not self.same_site():
            self.send_error(403)
        elif not start_speedtest():
            self.send_error(429)  # one running, or the last one was a few minutes ago
        else:
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def device(self, forget):
        """Name a device (POST /api/devices/MAC/name, {"name": ...}) or forget an offline one (DELETE
        /api/devices/MAC), from the devices card. Anyone at home may, like deleting recordings; the
        page asks before forgetting."""
        m = DEVICE_PATH.fullmatch(self.path)
        if not m or bool(m.group(2)) == forget or not (CONFIG / "router").exists():
            self.send_error(404)
            return
        if not is_home(self.client_address[0]) or not self.same_site():
            self.send_error(403)
            return
        name = None
        if not forget:
            try:
                size = int(self.headers.get("Content-Length", 0))
                name = json.loads(self.rfile.read(size) if 0 < size <= 1000 else b"")["name"]
            except (ValueError, KeyError, TypeError):
                self.send_error(400)
                return
            if not isinstance(name, str):
                self.send_error(400)
                return
            name = " ".join("".join(c if c.isprintable() else " " for c in name).split())[:40]
        if (devices_now := change_device(m.group(1), name, forget)) is not None:
            self.send_json({"devices": devices_now})
        else:
            self.send_error(404)

    def same_site(self):
        """The request comes from the panel's own page. Browsers don't stop other sites from opening
        websockets here, and a site's name pointed at the phone (DNS rebinding) would read the stills,
        so: the address typed must be a plain IP, and a page asking must be from that same address."""
        host = self.headers.get("Host", "")
        try:
            ipaddress.ip_address(urllib.parse.urlsplit("//" + host).hostname or "")
        except ValueError:
            return False
        origin = self.headers.get("Origin")
        return origin is None or origin == "http://" + host

    def recordings_allowed(self):
        """Recordings shown, asked from home and from the panel's own page; else answers 404/403."""
        if not recordings_shown():
            self.send_error(404)
            return False
        if not is_home(self.client_address[0]) or not self.same_site():
            self.send_error(403)  # recordings are home-only, like live view
            return False
        return True

    def do_DELETE(self):
        """A device from the devices card (see device()), or a clip or one camera's whole day from the
        recordings section. Anyone at home may (owner's call); the page asks first. Only the recorder's
        clips and thumbnails, never a part being recorded."""
        if self.path.startswith("/api/devices/"):
            self.device(forget=True)
            return
        if not self.recordings_allowed():
            return
        path, done = self.path.split("?", 1)[0], None
        if m := REC_FILE.fullmatch(path):
            done = STORE.delete_clip(*(urllib.parse.unquote(g) for g in m.groups()))
        elif m := REC_DAY.fullmatch(path):
            done = STORE.delete_day(*(urllib.parse.unquote(g) for g in m.groups()))
        if done and done["bytes"]:
            self.send_json(done)
        else:
            self.send_error(404)

    def recordings(self):
        path = self.path.split("?", 1)[0]
        if not self.recordings_allowed():
            return
        # each segment is decoded once; folder names hold a literal % themselves
        if path == "/api/recordings":
            self.send_json({"cameras": STORE.cameras()})
        elif m := REC_DAY.fullmatch(path):
            folder, day = (urllib.parse.unquote(g) for g in m.groups())
            if FOLDER.fullmatch(folder) and DAY.fullmatch(day):
                self.send_json({"clips": STORE.clips(folder, day)})
            else:
                self.send_error(404)
        elif m := REC_FILE.fullmatch(path):
            folder, day, name = (urllib.parse.unquote(g) for g in m.groups())
            found = STORE.file(folder, day, name)
            if found is None:
                self.send_error(404)
            else:
                self.send_file(found, "video/mp4" if CLIP.fullmatch(name) else "image/jpeg")
        else:
            self.send_error(404)

    def send_json(self, data):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path, kind):
        """A file with single-range support, so the browser can seek in a clip."""
        try:
            f = open(path, "rb")
        except OSError:  # gone since the lookup (the recorder trims old clips)
            self.send_error(404)
            return
        with f:
            size = os.fstat(f.fileno()).st_size
            start, end, code = 0, size - 1, 200
            m = RANGE.fullmatch(self.headers.get("Range", "").strip())
            if m and (m.group(1) or m.group(2)):
                if m.group(1):
                    start = int(m.group(1))
                    end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
                else:  # bytes=-n: the last n bytes
                    start, end = max(size - int(m.group(2)), 0), size - 1
                if start >= size or start > end:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                code = 206
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "private, max-age=86400")
            if code == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Content-Length", str(end - start + 1))
            self.end_headers()
            try:
                f.seek(start)
                left = end - start + 1
                while left > 0 and (chunk := f.read(min(CHUNK, left))):
                    self.wfile.write(chunk)
                    left -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True  # the viewer left mid-clip

    def camera(self, n):
        image = STILLS.get(n)
        if image is None:  # no fresh still yet, or the camera is offline
            self.send_response(204)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(image)))
        self.end_headers()
        self.wfile.write(image)

    def player(self):
        """go2rtc's player script, so the page loads it from its own address."""
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{GO2RTC_PORT}/video-rtc.js", timeout=5) as r:
                body = r.read()
        except OSError:
            self.send_error(502)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/javascript; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def live(self, source):
        """Pass a live-video websocket through to go2rtc, byte for byte."""
        # only a websocket: a plain request would let the browser talk to go2rtc's API directly
        if (self.headers.get("Upgrade", "").lower() != "websocket"
                or "upgrade" not in self.headers.get("Connection", "").lower()):
            self.send_error(400)
            return
        try:
            up = socket.create_connection(("127.0.0.1", GO2RTC_PORT), timeout=5)
        except OSError:
            self.send_error(502)
            return
        # only the websocket handshake headers; no Origin, go2rtc refuses websockets from other origins
        headers = "".join(f"{k}: {v}\r\n" for k, v in self.headers.items() if k.lower() in LIVE_HEADERS and "\r" not in v and "\n" not in v)
        self.close_connection = True
        try:
            up.sendall(f"GET /api/ws?src={source} HTTP/1.1\r\nHost: 127.0.0.1:{GO2RTC_PORT}\r\n{headers}\r\n".encode())
            answer = b""
            while b"\r\n\r\n" not in answer and len(answer) < 16384:
                if not (data := up.recv(4096)):
                    break
                answer += data
            self.connection.sendall(answer)
        except OSError:
            up.close()
            return
        if not answer.startswith(b"HTTP/1.1 101"):  # turned down: hang up, nothing else goes through
            up.close()
            return
        # a camera that goes silent, or a tablet that drops off the Wi-Fi, must not hold the line forever
        up.settimeout(LIVE_IDLE_S)
        browser = self.connection
        browser.settimeout(None)
        browser.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        for opt, value in (("TCP_KEEPIDLE", 20), ("TCP_KEEPINTVL", 5), ("TCP_KEEPCNT", 3), ("TCP_USER_TIMEOUT", 20000)):
            if hasattr(socket, opt):
                browser.setsockopt(socket.IPPROTO_TCP, getattr(socket, opt), value)

        def pipe(read, sock):
            try:
                while data := read(65536):
                    sock.sendall(data)
            except OSError:
                pass
            for s in (up, self.connection):  # one side closed: close both
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

        back = threading.Thread(target=pipe, args=(up.recv, self.connection), daemon=True)
        back.start()
        pipe(self.rfile.read1, up)  # read1: whatever the browser sent, including bytes already buffered
        back.join()
        up.close()

    def log_message(self, *args):
        pass  # keep Termux quiet


if __name__ == "__main__":
    # the first battery read can take a while; serve the page meanwhile
    threading.Thread(target=battery_logger, daemon=True).start()
    start_home_readers()
    if PLUG_CONFIG.exists():
        threading.Thread(target=plug_keeper, daemon=True).start()
    threading.Thread(target=speed_scheduler, daemon=True).start()
    SAMPLER.start()
    CAMERA_NAMES = load_names(CONFIG / "cameras")  # names only; the codes stay in go2rtc's config
    if CAMERA_NAMES:
        kill_leftovers(DATA / "cams")
        STILLS = Stills(len(CAMERA_NAMES), DATA / "cams", borrowed=DATA / "recorder-stills")
        STILLS.start_reaper()
        # each ffmpeg has its own process group: stopping the panel must stop them too
        signal.signal(signal.SIGTERM, lambda *_: (STILLS.stop_all(), os._exit(0)))
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
