#!/data/data/com.termux/files/usr/bin/python
"""drawer-server status panel.

A tiny web page (standard library only) that shows battery, temperature, memory, disk
and which services are alive. It also logs the battery every 5 minutes so you can see
how an always-plugged phone behaves over a day.

Runs inside Termux:  python ~/panel/panel.py   ->  http://<phone-ip>:8080
"""
import csv
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

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


def memory():
    info = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, value = line.split(":", 1)
        info[key] = int(value.split()[0]) // 1024
    return {"total_mb": info["MemTotal"], "available_mb": info["MemAvailable"]}


def disk():
    d = shutil.disk_usage(HOME)
    return {"total_gb": round(d.total / 1e9, 1), "free_gb": round(d.free / 1e9, 1)}


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


def uptime_hours():
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


def every(seconds, key, reader):
    def loop():
        while True:
            try:
                _home[key] = reader()
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
    home if their phone answered in the last 20 minutes. Config: one 'Name IP' per line."""
    result = []
    for line in (CONFIG / "people").read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        name, ip = line.rsplit(None, 1)
        if ping(ip):
            _last_seen[name] = time.time()
        seen = _last_seen.get(name)
        result.append({"name": name, "home": bool(seen and time.time() - seen < 20 * 60),
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
    folders = []
    for f in get("/rest/config/folders"):
        st = get("/rest/db/status?folder=" + urllib.parse.quote(f["id"]))
        senders = [d["deviceID"] for d in f["devices"] if d["deviceID"] != me]
        total, need = st["globalBytes"], st["needBytes"]
        folders.append({"label": f["label"] or f["id"],
                        "from": ", ".join(names.get(d, d[:7]) for d in senders),
                        "online": any(d in online for d in senders),
                        "pct": 100 if not total else int((total - need) * 100 / total),
                        "need_gb": round(need / 1e9, 1), "need_files": st["needFiles"]})
    return {"folders": folders, "mb_s": round(speed, 1)}


# Ezviz (Hikvision) cameras and doorbells; the rest is guessed from the name the device reports
CAMERA_MACS = ("F4-70-18", "0C-A6-4C")
KINDS = ("camera", "computer", "phone", "network", "other")
DEVICES_SEEN = DATA / "devices.json"


def device_kind(name, mac):
    n = name.lower()
    if mac.startswith(CAMERA_MACS) or re.search(r"cam|timbre|doorbell|ezviz", n):
        return "camera"
    if re.search(r"desktop|laptop|lenovo|notebook|macbook|imac|pc", n):
        return "computer"
    if re.search(r"archer|deco|router|repeater|extender", n):
        return "network"
    # phones make up a "private" MAC per network: the second hex digit is 2, 6, A or E
    if re.search(r"celu|phone|iphone|galaxy|moto|pixel", n) or mac[1:2] in "26AE":
        return "phone"
    return "other"


def devices():
    """Everything connected to the home router (TP-Link, through its web API), plus devices seen
    before that are gone now, so a camera that drops off the Wi-Fi shows up as offline.
    Config: router URL and password in ~/.config/drawer-server/router (one per line), optional
    'MAC Name' lines in ~/.config/drawer-server/device-names."""
    from tplinkrouterc6u import TplinkRouterProvider  # only installed when the router card is on
    url, password = (CONFIG / "router").read_text().splitlines()[:2]
    names = {}
    if (CONFIG / "device-names").exists():
        for line in (CONFIG / "device-names").read_text().splitlines():
            if line.strip():
                mac, name = line.split(None, 1)
                names[mac.upper().replace(":", "-")] = name.strip()
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
    seen = json.loads(DEVICES_SEEN.read_text()) if DEVICES_SEEN.exists() else {}
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
    result = []
    for mac, d in list(seen.items()):
        if now - d["last"] > 30 * 86400:  # forget devices gone for a month
            del seen[mac]
            continue
        name = names.get(mac) or d["host"] or (d["ip"] or mac)
        result.append({"name": name, "kind": device_kind(name, mac), "ip": d["ip"] if mac in online else None,
                       "conn": d["conn"], "signal": d["signal"], "online": mac in online,
                       "seen_min_ago": round((now - d["last"]) / 60)})
    DEVICES_SEEN.write_text(json.dumps(seen))
    result.sort(key=lambda x: (KINDS.index(x["kind"]), not x["online"], x["name"].lower()))
    return {"ssid": ssid, "devices": result}


def start_home_readers():
    if (CONFIG / "starlink").exists():
        every(60, "starlink", starlink)
    if (CONFIG / "printer").exists():
        every(600, "printer", printer)
    if (CONFIG / "people").exists():
        every(120, "people", people)
    if (CONFIG / "router").exists():
        every(300, "devices", devices)
    if SYNCTHING_CONFIG.exists():
        every(30, "backup", backup)


def status():
    services = [
        {"name": "SSH", "ok": process_running("sshd")},
        {"name": "NextDNS", "ok": pid_alive(HOME / ".cache" / "nextdns-link.pid"), "detail": nextdns_last()},
    ]
    if (HOME / "luanti").exists():
        players = luanti_players()
        services.append({"name": "Luanti", "ok": pid_alive(HOME / "luanti" / "server.pid") and process_running("luantiserver"),
                         "players": players})
    if (HOME / ".termux" / "boot" / "50-syncthing.sh").exists():
        services.append({"name": "Syncthing", "ok": pid_alive(HOME / ".cache" / "syncthing.pid")})
    history = []
    if BATTERY_LOG.exists():
        day_ago = time.time() - 24 * 3600
        for row in csv.reader(BATTERY_LOG.read_text().splitlines()):
            if len(row) >= 3 and row[1] and int(row[0]) >= day_ago:
                history.append([int(row[0]), float(row[1]), float(row[2] or 0)])
    # Android sometimes puts Termux:API to sleep; then battery readings silently stop
    battery_stale = time.time() - _battery_ok_at > 600
    return {"battery": {} if battery_stale else _battery, "battery_stale": battery_stale, "memory": memory(), "disk": disk(), "uptime_h": uptime_hours(),
            "services": services, "history": history, "home": _home, "time": int(time.time())}


TEXT = {
    "en": {"title": "Drawer server", "battery": "Battery", "temp": "Temperature", "ram": "Free memory",
           "disk": "Free storage", "uptime": "Up for", "hours": "h", "services": "Services",
           "players": "playing", "nobody": "nobody playing", "history": "Battery, last 24 h",
           "charging": "charging", "not_charging": "on battery", "updated": "updated",
           "unplug": "🔌 Battery at {p}%: unplug the charger (keeping it between 30 and 80% makes it last longer)",
           "plug": "🔌 Battery at {p}%: plug the charger in (unplug it at 80%)",
           "starlink": "Starlink", "latency": "latency", "obstructed": "obstructed", "dish_up": "dish on for",
           "printer": "Printer ink", "people": "Who's home", "home": "home", "away": "away",
           "api_asleep": "⚠️ Can't read the battery: Android put Termux:API to sleep. Run scripts/restart-server.sh with the phone plugged into the computer.",
           "seen": "seen {m} ago", "devices": "Devices",
           "on": "on", "wired": "cable", "no_ip": "connected but the router gave it no address",
           "offline": "offline", "weak": "weak signal",
           "camera": "Cameras", "computer": "Computers", "phone": "Phones", "network": "Network", "other": "Other",
           "backup": "Photo backup",
           "receiving": "receiving {p}%: {gb} GB left ({n} files)", "up_to_date": "up to date ✓",
           "waiting": "{p}%, {gb} GB to go: waiting for the phone (on home Wi-Fi with Syncthing open)", "black": "black", "cyan": "cyan", "magenta": "magenta", "yellow": "yellow"},
    "es": {"title": "Servidor del cajón", "battery": "Batería", "temp": "Temperatura", "ram": "Memoria libre",
           "disk": "Espacio libre", "uptime": "Prendido hace", "hours": "h", "services": "Servicios",
           "players": "jugando", "nobody": "nadie jugando", "history": "Batería, últimas 24 h",
           "charging": "cargando", "not_charging": "a batería", "updated": "actualizado",
           "unplug": "🔌 Batería al {p}%: desenchufá el cargador (entre 30 y 80% dura muchos más años)",
           "plug": "🔌 Batería al {p}%: enchufá el cargador (y sacalo al 80%)",
           "starlink": "Starlink", "latency": "latencia", "obstructed": "obstruido", "dish_up": "antena prendida hace",
           "printer": "Tinta de la impresora", "people": "¿Quién está en casa?", "home": "en casa", "away": "afuera",
           "api_asleep": "⚠️ No puedo leer la batería: Android durmió a Termux:API. Corré scripts/restart-server.sh con el celu enchufado a la compu.",
           "seen": "visto hace {m}", "devices": "Dispositivos",
           "on": "en", "wired": "cable", "no_ip": "conectado pero el router no le dio dirección",
           "offline": "desconectado", "weak": "señal débil",
           "camera": "Cámaras", "computer": "Computadoras", "phone": "Celulares", "network": "Red", "other": "Otros",
           "backup": "Backup de fotos",
           "receiving": "recibiendo {p}%: faltan {gb} GB ({n} archivos)", "up_to_date": "al día ✓",
           "waiting": "{p}%, faltan {gb} GB: esperando al celu (en el WiFi de casa con Syncthing abierto)", "black": "negro", "cyan": "cian", "magenta": "magenta", "yellow": "amarillo"},
}

PAGE = """<!doctype html>
<html lang="__LANG__"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root { --bg:#f6f7f9; --card:#fff; --ink:#1d2330; --muted:#6b7280; --ok:#16a34a; --bad:#dc2626; --warn:#d97706; --line:#2563eb; }
  @media (prefers-color-scheme: dark) { :root { --bg:#0f1218; --card:#181c24; --ink:#e6e8ee; --muted:#9aa3b2; --line:#60a5fa; } }
  * { box-sizing:border-box; }
  body { margin:0; padding:16px; background:var(--bg); color:var(--ink); font:16px/1.4 system-ui, sans-serif; }
  h1 { font-size:22px; margin:0 0 12px; }
  .grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); gap:12px; }
  .card { background:var(--card); border-radius:14px; padding:14px; box-shadow:0 1px 3px #0001; }
  .label { color:var(--muted); font-size:13px; }
  .big { font-size:30px; font-weight:700; font-variant-numeric:tabular-nums; }
  .sub { color:var(--muted); font-size:13px; }
  .svc { display:flex; justify-content:space-between; gap:8px; padding:6px 0; border-bottom:1px solid #8882; }
  .svc:last-child { border:0; }
  .dot { display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:8px; }
  .wide { grid-column:1 / -1; }
  svg { width:100%; height:120px; display:block; }
  .foot { color:var(--muted); font-size:12px; margin-top:12px; }
  .alert { background:#fef3c7; color:#78350f; border-radius:14px; padding:12px 14px; margin-bottom:12px; font-weight:600; }
  .alert:empty { display:none; }
  .ink { display:flex; gap:6px; margin-top:6px; }
  .ink > div { flex:1; min-width:0; text-align:center; font-size:12px; color:var(--muted); font-variant-numeric:tabular-nums; }
  .tank { background:#8882; border-radius:6px; position:relative; height:60px; overflow:hidden; margin-bottom:4px; }
  .tank i { position:absolute; bottom:0; left:0; right:0; border-radius:6px; }
  .hidden { display:none; }
  .kind { color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.04em; margin:10px 0 0; }
  .bar { background:#8882; border-radius:4px; height:6px; overflow:hidden; margin:2px 0 6px; }
  .bar i { display:block; height:100%; background:var(--ok); }
</style></head>
<body>
<h1>📱 __TITLE__</h1>
<div class="alert" id="alert"></div>
<div class="grid">
  <div class="card"><div class="label">🔋 __BATTERY__</div><div class="big" id="bat">–</div><div class="sub" id="plug"></div></div>
  <div class="card"><div class="label">🌡️ __TEMP__</div><div class="big" id="temp">–</div></div>
  <div class="card"><div class="label">🧠 __RAM__</div><div class="big" id="ram">–</div><div class="sub" id="ramsub"></div></div>
  <div class="card"><div class="label">💾 __DISK__</div><div class="big" id="disk">–</div><div class="sub" id="up"></div></div>
  <div class="card wide"><div class="label">⚙️ __SERVICES__</div><div id="svcs"></div></div>
  <div class="card wide hidden" id="sl"><div class="label">🛰️ __STARLINK__</div><div class="big" id="sl_lat"></div><div class="sub" id="sl_sub"></div></div>
  <div class="card wide hidden" id="bk"><div class="label">📷 __BACKUP__</div><div id="bk_list"></div></div>
  <div class="card wide hidden" id="dv"><div class="label" id="dv_title"></div><div id="dv_list"></div></div>
  <div class="card hidden" id="pp"><div class="label">🏠 __PEOPLE__</div><div id="pp_list"></div></div>
  <div class="card hidden" id="pr"><div class="label">🖨️ __PRINTER__</div><div class="ink" id="pr_ink"></div></div>
  <div class="card wide"><div class="label">📈 __HISTORY__</div><svg id="chart" viewBox="0 0 300 100" preserveAspectRatio="none"></svg></div>
</div>
<div class="foot" id="foot"></div>
<script>
const T = __TEXT__;
const LANG_ES = document.documentElement.lang === 'es';
const $ = id => document.getElementById(id);
// names come from config files, game logs and other phones: never insert them as HTML
const ago = m => m < 60 ? m + ' min' : m < 2880 ? Math.round(m / 60) + ' h' : Math.round(m / 1440) + (LANG_ES ? ' días' : ' days');
const esc = v => String(v).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
function color(ok) { return ok ? 'var(--ok)' : 'var(--bad)'; }
async function refresh() {
  try {
    const s = await (await fetch('/api/status')).json();
    const b = s.battery || {};
    $('bat').textContent = b.percentage != null ? b.percentage + '%' : '–';
    $('plug').textContent = b.plugged && b.plugged !== 'UNPLUGGED' ? '⚡ ' + T.charging : T.not_charging;
    const t = b.temperature;
    $('temp').textContent = t != null ? t.toFixed(1) + '°C' : '–';
    $('temp').style.color = t == null ? '' : t >= 40 ? 'var(--bad)' : t >= 35 ? 'var(--warn)' : '';
    $('ram').textContent = (s.memory.available_mb / 1024).toFixed(1) + ' GB';
    $('ramsub').textContent = '/ ' + (s.memory.total_mb / 1024).toFixed(1) + ' GB';
    $('disk').textContent = s.disk.free_gb + ' GB';
    $('up').textContent = s.uptime_h != null ? T.uptime + ' ' + s.uptime_h + T.hours : '';
    $('svcs').innerHTML = s.services.map(v => {
      let detail = '';
      if (v.players) detail = v.players.length ? v.players.length + ' ' + T.players + ': ' + esc(v.players.join(', ')) : T.nobody;
      return `<div class="svc"><span><span class="dot" style="background:${color(v.ok)}"></span>${v.name}</span><span class="sub">${detail}</span></div>`;
    }).join('');
    drawChart(s.history);
    // charge-cycling reminder until a smart plug does it automatically
    const p = b.percentage, plugged = b.plugged && b.plugged !== 'UNPLUGGED';
    $('alert').textContent = s.battery_stale ? T.api_asleep
                           : p == null ? '' : plugged && p >= 80 ? T.unplug.replace('{p}', p)
                           : !plugged && p <= 30 ? T.plug.replace('{p}', p) : '';
    drawHome(s.home || {});
    $('foot').textContent = T.updated + ' ' + new Date(s.time * 1000).toLocaleTimeString();
  } catch (e) { $('foot').textContent = '⚠️ ' + e; }
}
function drawChart(h) {
  const svg = $('chart');
  if (!h.length) { svg.innerHTML = ''; return; }
  const t0 = h[0][0], t1 = Math.max(h[h.length - 1][0], t0 + 1);
  const x = t => (t - t0) / (t1 - t0) * 300, y = p => 100 - p;
  const pts = h.map(r => x(r[0]).toFixed(1) + ',' + y(r[1]).toFixed(1)).join(' ');
  svg.innerHTML =
    `<rect x="0" y="20" width="300" height="40" fill="var(--ok)" opacity="0.08"/>` +   // 40-80% sweet spot
    `<polyline points="${pts}" fill="none" stroke="var(--line)" stroke-width="2" vector-effect="non-scaling-stroke"/>`;
}
const INK = {black:'#222', cyan:'#06b6d4', magenta:'#d946ef', yellow:'#facc15'};
function show(id, on) { $(id).classList.toggle('hidden', !on); }
function drawHome(h) {
  const sl = h.starlink;
  show('sl', sl && !sl.error);
  if (sl && !sl.error) {
    $('sl_lat').textContent = sl.latency_ms + ' ms ' + T.latency;
    $('sl_sub').textContent = `⬇ ${sl.down_mbps} Mbps · ⬆ ${sl.up_mbps} Mbps · ${sl.obstructed_pct}% ${T.obstructed} · ${T.dish_up} ${sl.uptime_h}${T.hours}` +
      (sl.alerts.length ? ' · ⚠️ ' + sl.alerts.join(', ') : '');
  }
  const dv = h.devices;
  show('dv', dv && dv.devices);
  if (dv && dv.devices) {
    $('dv_title').textContent = '📶 ' + T.devices + (dv.ssid ? ' ' + T.on + ' ' + dv.ssid : '') +
      ' (' + dv.devices.filter(d => d.online).length + ')';
    const icon = {camera: '📷', computer: '💻', phone: '📱', network: '🌐', other: '🔌'};
    let kind = '';
    $('dv_list').innerHTML = dv.devices.map(d => {
      const head = d.kind !== kind ? `<div class="kind">${icon[d.kind]} ${T[d.kind]}</div>` : '';
      kind = d.kind;
      const weak = d.signal != null && d.signal < -75;
      const how = d.conn === 'wired' ? T.wired : d.conn + ' GHz' + (d.signal != null ? ' · ' + d.signal + ' dBm' : '');
      const st = !d.online ? T.offline + ' · ' + T.seen.replace('{m}', ago(d.seen_min_ago))
               : !d.ip ? '⚠️ ' + T.no_ip
               : esc(d.ip) + ' · ' + how + (weak ? ' ⚠️ ' + T.weak : '');
      return head + `<div class="svc"><span><span class="dot" style="background:${d.online && d.ip ? 'var(--ok)' : d.online ? 'var(--warn)' : 'var(--bad)'}"></span>${esc(d.name)}</span>` +
        `<span class="sub"${weak ? ' style="color:var(--warn)"' : ''}>${st}</span></div>`;
    }).join('');
  }
  const pp = h.people;
  show('pp', Array.isArray(pp));
  if (Array.isArray(pp)) $('pp_list').innerHTML = pp.map(x =>
    `<div class="svc"><span><span class="dot" style="background:${x.home ? 'var(--ok)' : 'var(--muted)'}"></span>${esc(x.name)}</span>` +
    `<span class="sub">${x.home ? T.home : T.away}${x.seen_min_ago != null && !x.home ? ' · ' + T.seen.replace('{m}', ago(x.seen_min_ago)) : ''}</span></div>`).join('');
  const bk = h.backup;
  show('bk', bk && bk.folders && bk.folders.length);
  if (bk && bk.folders) $('bk_list').innerHTML = bk.folders.map(f => {
    const fill = s => s.replace('{p}', f.pct).replace('{gb}', f.need_gb).replace('{n}', f.need_files);
    const st = !f.need_files ? T.up_to_date
             : f.online ? fill(T.receiving) + (bk.mb_s ? ' · ' + bk.mb_s + ' MB/s' : '') : fill(T.waiting);
    return `<div class="svc"><span><span class="dot" style="background:${f.online ? 'var(--ok)' : 'var(--muted)'}"></span>${esc(f.label)}</span>` +
      `<span class="sub">${st}</span></div>` + (f.need_files ? `<div class="bar"><i style="width:${f.pct}%"></i></div>` : '');
  }).join('');
  const pr = h.printer;
  show('pr', pr && pr.inks);
  if (pr && pr.inks) $('pr_ink').innerHTML = pr.inks.map(k =>
    `<div title="${esc(T[k.color] || k.color)}"><div class="tank"><i style="height:${k.level}%;background:${INK[k.color] || '#888'}"></i></div>${k.level}%</div>`).join('');
}
refresh(); setInterval(refresh, 10000);
</script>
</body></html>"""


def render():
    text = TEXT.get(LANG, TEXT["en"])
    page = PAGE.replace("__TEXT__", json.dumps(text)).replace("__LANG__", LANG)
    for key in ("title", "battery", "temp", "ram", "disk", "services", "history", "starlink", "people", "printer", "backup"):
        page = page.replace(f"__{key.upper()}__", text[key])
    return page.encode()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/status":
            body, kind = json.dumps(status()).encode(), "application/json"
        elif self.path in ("/", "/index.html"):
            body, kind = render(), "text/html; charset=utf-8"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # keep Termux quiet


if __name__ == "__main__":
    # the first battery read can take a while; serve the page meanwhile
    threading.Thread(target=battery_logger, daemon=True).start()
    start_home_readers()
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
