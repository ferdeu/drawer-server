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
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cameras import Stills, is_home, kill_leftovers, load_names

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


def my_ip():
    """This phone's address on the home network (a UDP connect sends nothing, it only picks the route)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return None


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
    if re.search(r"desktop|laptop|lenovo|notebook|macbook|imac|compu|\bpc\b", n):
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
        # last_ip lets the page match a device to a person's phone even while it's away
        result.append({"name": name, "kind": device_kind(name, mac), "ip": d["ip"] if mac in online else None,
                       "last_ip": d["ip"], "conn": d["conn"], "signal": d["signal"], "online": mac in online,
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
    history = []
    if BATTERY_LOG.exists():
        day_ago = time.time() - 24 * 3600
        for row in csv.reader(BATTERY_LOG.read_text().splitlines()):
            if len(row) >= 3 and row[1] and int(row[0]) >= day_ago:
                history.append([int(row[0]), float(row[1]), float(row[2] or 0)])
    # Android sometimes puts Termux:API to sleep; then battery readings silently stop
    battery_stale = time.time() - _battery_ok_at > 600
    return {"battery": {} if battery_stale else _battery, "battery_stale": battery_stale, "memory": memory(), "disk": disk(), "uptime_h": uptime_hours(),
            "services": services, "history": history,
            "home": _home, "plug": _plug, "time": int(time.time()),
            "cameras": {"names": CAMERA_NAMES, "home": is_home(client_ip)} if CAMERA_NAMES else None,
            # the server and its plug show in the server section, not with the other devices
            "self_ip": my_ip(), "plug_ip": PLUG_CONFIG.read_text().split()[1] if PLUG_CONFIG.exists() else None}


TEXT = {
    "en": {"title": "Drawer server", "battery": "Battery", "temp": "Temperature", "ram": "Free memory",
           "disk": "Free storage", "uptime": "on for", "hours": "h", "services": "Services",
           "players": "playing", "nobody": "nobody playing", "history": "Battery, last 24 h",
           "charging": "charging", "not_charging": "on battery", "updated": "updated",
           "unplug": "🔌 Battery at {p}%: unplug the charger (keeping it between 30 and 80% makes it last longer)",
           "plug": "🔌 Battery at {p}%: plug the charger in (unplug it at 80%)",
           "plug_on": "smart plug on", "plug_off": "smart plug off until {low}%",
           "plug_error": "⚠️ Can't reach the smart plug ({e}). Is it on and on the Wi-Fi?",
           "latency": "latency", "obstructed": "Sky blocked", "dish_up": "Dish on for", "alerts": "Dish alerts",
           "printer": "Printer", "people": "Who's home", "home": "home", "away": "away",
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
           "connection": "Connection", "this_server": "Server", "the_plug": "Smart plug",
           "svc": {"SSH": "Remote access", "NextDNS": "Ad blocking", "Luanti": "Kids' game", "Syncthing": "Photo backup",
                   "Cameras": "Cameras"},
           "use_note": "The dish reports how much is being used right now, not the top speed of the connection.",
           "server": "Server", "show_chart": "📈 24 h", "n_of": "{a} of {b} online", "wifi": "Wi-Fi",
           "photos": "Photos", "no_details": "No details while away.",
           "printer_off": "not answering (off?)", "lowest": "lowest: {c} {p}%",
           "day_ago": "24 h ago", "now": "now",
           "p_battery": "battery not read", "p_plug": "smart plug not answering", "p_down": "{s} down",
           "p_hot": "server hot", "p_internet": "internet with alerts", "p_cams": "{n} camera(s) offline",
           "cam_away": "Home only: open {url} on the home Wi-Fi", "no_image": "no image",
           "connecting": "connecting…", "no_video": "Can't show this camera live on this screen"},
    "es": {"title": "Servidor del cajón", "battery": "Batería", "temp": "Temperatura", "ram": "Memoria libre",
           "disk": "Espacio libre", "uptime": "prendido hace", "hours": "h", "services": "Servicios",
           "players": "jugando", "nobody": "nadie jugando", "history": "Batería, últimas 24 h",
           "charging": "cargando", "not_charging": "a batería", "updated": "actualizado",
           "unplug": "🔌 Batería al {p}%: desenchufá el cargador (entre 30 y 80% dura muchos más años)",
           "plug": "🔌 Batería al {p}%: enchufá el cargador (y sacalo al 80%)",
           "plug_on": "enchufe prendido", "plug_off": "enchufe apagado hasta el {low}%",
           "plug_error": "⚠️ No puedo hablar con el enchufe ({e}). ¿Está prendido y en el WiFi?",
           "latency": "latencia", "obstructed": "Cielo tapado", "dish_up": "Antena prendida hace", "alerts": "Alertas de la antena",
           "printer": "Impresora", "people": "¿Quién está en casa?", "home": "en casa", "away": "afuera",
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
           "connection": "Conexión", "this_server": "Servidor", "the_plug": "Enchufe",
           "svc": {"SSH": "Acceso remoto", "NextDNS": "Bloqueo de publicidad", "Luanti": "Juego de los chicos", "Syncthing": "Backup de fotos",
                   "Cameras": "Cámaras"},
           "use_note": "La antena dice cuánto se está usando en este momento, no la velocidad máxima de la conexión.",
           "server": "Servidor", "show_chart": "📈 24 h", "n_of": "{a} de {b} conectados", "wifi": "WiFi",
           "photos": "Fotos", "no_details": "Sin detalles mientras está afuera.",
           "printer_off": "no contesta (¿apagada?)", "lowest": "la más baja: {c} {p}%",
           "day_ago": "hace 24 h", "now": "ahora",
           "p_battery": "no leo la batería", "p_plug": "el enchufe no contesta", "p_down": "{s} caído",
           "p_hot": "server caliente", "p_internet": "internet con alertas", "p_cams": "{n} cámara(s) desconectada(s)",
           "cam_away": "Solo en casa: abrí {url} en el WiFi de casa", "no_image": "sin imagen",
           "connecting": "conectando…", "no_video": "No puedo mostrar esta cámara en vivo en esta pantalla"},
}

PAGE = """<!doctype html>
<html lang="__LANG__"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root { --bg:#f6f7f9; --card:#fff; --ink:#1d2330; --muted:#6b7280; --ok:#16a34a; --bad:#dc2626; --warn:#d97706; --line:#2563eb; --soft:#8882; }
  @media (prefers-color-scheme: dark) { :root { --bg:#0f1218; --card:#181c24; --ink:#e6e8ee; --muted:#9aa3b2; --line:#60a5fa; } }
  * { box-sizing:border-box; }
  body { margin:0; padding:16px; background:var(--bg); color:var(--ink); font:16px/1.4 system-ui, sans-serif; }
  main { max-width:760px; margin:0 auto; display:flex; flex-direction:column; gap:12px; }
  h1 { font-size:24px; margin:0; }
  h2 { font-size:15px; margin:8px 0 0; color:var(--muted); font-weight:600; display:flex; justify-content:space-between; align-items:baseline; }
  .overall { font-weight:600; margin-top:4px; }
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
  .bar { background:var(--soft); border-radius:4px; height:6px; overflow:hidden; margin:2px 0 6px; }
  .bar i { display:block; height:100%; background:var(--ok); }
  details { border-bottom:1px solid var(--soft); }
  details:last-child, .card > details { border:0; }
  summary { list-style:none; cursor:pointer; display:flex; align-items:center; gap:8px; padding:8px 0; }
  summary::-webkit-details-marker { display:none; }
  summary::after { content:'›'; color:var(--muted); font-size:20px; line-height:1; transition:transform .15s; }
  details[open] > summary::after { transform:rotate(90deg); }
  .right { margin-left:auto; text-align:right; }
  .stats { display:flex; flex-wrap:wrap; gap:4px 20px; }
  .stats .big { font-size:26px; }
  .unit { font-size:15px; font-weight:600; color:var(--muted); }
  .more { padding:0 0 8px 18px; }
  .chips { display:flex; flex-wrap:wrap; gap:6px 14px; margin-top:6px; }
  .chips > span { display:inline-flex; align-items:center; }
  .chips .sub { margin-left:4px; }
  button.link { background:none; border:0; padding:0; margin-top:6px; color:var(--line); font:inherit; font-size:13px; cursor:pointer; }
  .cams { display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); gap:8px; margin-top:8px; }
  .cam { position:relative; aspect-ratio:16/9; background:var(--soft); border:0; border-radius:10px; padding:0; overflow:hidden; cursor:pointer; }
  .cam img { position:absolute; inset:0; width:100%; height:100%; object-fit:cover; }
  .cam .none { position:absolute; inset:0; display:flex; align-items:center; justify-content:center; color:var(--muted); font-size:13px; }
  .cam .name { position:absolute; left:6px; bottom:6px; background:#0009; color:#fff; font-size:12px; padding:2px 7px; border-radius:6px; }
  .live { position:fixed; inset:0; z-index:10; background:#000; color:#fff; display:flex; flex-direction:column; }
  .live.hidden { display:none; }
  .live_top { display:flex; align-items:center; justify-content:space-between; padding:8px 14px; }
  .live_top button { background:none; border:0; color:#fff; font-size:26px; cursor:pointer; }
  .live_view { flex:1; position:relative; overflow:hidden; touch-action:none; }
  .live_view video { width:100%; height:100%; object-fit:contain; transform-origin:0 0; }
  .live_msg { position:absolute; inset:0; display:flex; align-items:center; justify-content:center; color:#ccc; pointer-events:none; }
  .nav { position:absolute; top:50%; transform:translateY(-50%); width:48px; height:48px; border:0; border-radius:50%;
         background:#0007; color:#fff; font-size:20px; cursor:pointer; }
  .nav.prev { left:8px; } .nav.next { right:8px; }
</style></head>
<body><main>
<header><h1>🏡 __TITLE__</h1><div class="overall" id="overall"></div></header>
<div class="alert" id="alert"></div>

<section class="card hidden" id="net">
  <div class="label">🌐 __INTERNET__</div>
  <div class="stats">
    <div><div class="big" id="net_lat">–</div><div class="sub">__LATENCY__</div></div>
    <div><div class="big" id="net_down">–</div><div class="sub">⬇ __DOWN_NOW__</div></div>
    <div><div class="big" id="net_up">–</div><div class="sub">⬆ __UP_NOW__</div></div>
  </div>
  <details data-k="net"><summary class="sub">__DETAILS__</summary><div class="more" id="net_more"></div></details>
</section>

<section class="card hidden" id="cams"><div class="label">📷 __CAMERA__</div>
  <div class="cams" id="cam_grid"></div><div class="sub hidden" id="cam_away"></div></section>
<div class="live hidden" id="live">
  <div class="live_top"><b id="live_name"></b><button id="live_close" aria-label="close">✕</button></div>
  <div class="live_view" id="live_view"><div class="live_msg" id="live_msg"></div>
    <button class="nav prev" id="live_prev" aria-label="previous">◀</button><button class="nav next" id="live_next" aria-label="next">▶</button></div>
</div>

<section class="card hidden" id="pp"><div class="label">🏠 __PEOPLE__</div><div id="pp_list"></div></section>
<section class="card hidden" id="bk"><div class="label">📷 __BACKUP__</div><div id="bk_list"></div></section>

<h2><span>🖥️ __SERVER__</span><span class="sub" id="up"></span></h2>
<div class="grid">
  <div class="card"><div class="label">🔋 __BATTERY__</div><div class="big" id="bat">–</div><div class="sub" id="plug"></div>
    <button class="link" id="chart_btn">__SHOW_CHART__</button></div>
  <div class="card"><div class="label">🌡️ __TEMP__</div><div class="big" id="temp">–</div></div>
  <div class="card"><div class="label">🧠 __RAM__</div><div class="big" id="ram">–</div><div class="sub" id="ramsub"></div></div>
  <div class="card"><div class="label">💾 __DISK__</div><div class="big" id="disk">–</div><div class="sub" id="disksub"></div></div>
  <div class="card wide hidden" id="chartbox"><div class="label">📈 __HISTORY__</div>
    <svg id="chart" viewBox="0 0 300 100" preserveAspectRatio="none"></svg>
    <div class="axis sub"><span>__DAY_AGO__</span><span>__NOW__</span></div></div>
  <div class="card wide"><div class="label">⚙️ __SERVICES__</div><div class="chips" id="svcs"></div></div>
  <div class="card wide hidden" id="cn"><div class="label">📶 __CONNECTION__</div><div id="cn_list"></div></div>
</div>

<section class="card hidden" id="dv"><div class="label" id="dv_title"></div><div id="dv_list"></div></section>
<section class="card hidden" id="pr"><details data-k="printer"><summary>🖨️ __PRINTER__<span class="sub right" id="pr_sum"></span></summary>
  <div class="ink" id="pr_ink"></div></details></section>
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
$('chart_btn').onclick = () => { remember('chart', !open.has('chart')); show('chartbox', open.has('chart')); };
show('chartbox', open.has('chart'));

async function refresh() {
  try {
    const s = await (await fetch('/api/status')).json();
    const h = s.home || {}, b = s.battery || {}, sp = s.plug;
    $('bat').textContent = b.percentage != null ? b.percentage + '%' : '–';
    $('plug').textContent = (b.plugged && b.plugged !== 'UNPLUGGED' ? '⚡ ' + T.charging : T.not_charging) +
      (sp && !sp.error ? ' · ' + (sp.on ? T.plug_on + (sp.watts != null ? ' ' + num(sp.watts) + ' W' : '') : T.plug_off.replace('{low}', sp.low)) : '');
    const t = b.temperature;
    $('temp').textContent = t != null ? num(t, 1) + '°C' : '–';
    $('temp').style.color = t == null ? '' : t >= 40 ? BAD : t >= 35 ? WARN : '';
    $('ram').textContent = num(s.memory.available_mb / 1024, 1) + ' GB';
    $('ramsub').textContent = '/ ' + num(s.memory.total_mb / 1024, 1) + ' GB';
    $('disk').textContent = num(s.disk.free_gb) + ' GB';
    $('disksub').textContent = '/ ' + num(s.disk.total_gb) + ' GB';
    $('up').textContent = s.uptime_h != null ? T.uptime + ' ' + ago(Math.round(s.uptime_h * 60)) : '';
    set('svcs', s.services.map(v => {
      let detail = '';
      if (v.players) detail = v.players.length ? ' · ' + v.players.length + ' ' + T.players + ': ' + esc(v.players.join(', ')) : ' · ' + T.nobody;
      return `<span>${dot(v.ok ? OK : BAD)}${T.svc[v.name] || v.name}<span class="sub">${detail}</span></span>`;
    }).join(''));
    drawChart(s.history, sp);
    // charge-cycling reminder, unless a smart plug does it automatically
    const p = b.percentage, plugged = b.plugged && b.plugged !== 'UNPLUGGED';
    $('alert').textContent = s.battery_stale ? T.api_asleep
                           : sp && sp.error ? T.plug_error.replace('{e}', sp.error)
                           : sp ? ''
                           : p == null ? '' : plugged && p >= 80 ? T.unplug.replace('{p}', p)
                           : !plugged && p <= 30 ? T.plug.replace('{p}', p) : '';
    const people = Array.isArray(h.people) ? h.people : null;
    drawInternet(h.starlink);
    drawCameras(s.cameras, s.self_ip);
    drawPeople(people, h);
    drawConnection(h.devices, s);
    drawDevices(h.devices, (people ? people.map(x => x.ip) : []).concat([s.self_ip, s.plug_ip]));
    drawPrinter(h.printer);
    drawOverall(s, h);
    $('foot').textContent = T.updated + ' ' + new Date(s.time * 1000).toLocaleTimeString(LANG);
  } catch (e) { $('foot').textContent = '⚠️ ' + e; }
}

function drawOverall(s, h) {
  const probs = [], t = (s.battery || {}).temperature, sl = h.starlink;
  if (s.battery_stale) probs.push(T.p_battery);
  if (s.plug && s.plug.error) probs.push(T.p_plug);
  s.services.filter(v => !v.ok).forEach(v => probs.push(T.p_down.replace('{s}', T.svc[v.name] || v.name)));
  if (t >= 40) probs.push(T.p_hot);
  if (sl && (sl.error || sl.alerts.length)) probs.push(T.p_internet);
  const cams = ((h.devices || {}).devices || []).filter(d => d.kind === 'camera' && !d.online).length;
  if (cams) probs.push(T.p_cams.replace('{n}', cams));
  $('overall').textContent = probs.length ? '⚠️ ' + probs.join(' · ') : '✓ ' + T.all_ok;
  $('overall').className = 'overall ' + (probs.length ? 'bad' : 'ok');
}

function drawInternet(sl) {
  show('net', sl);
  if (!sl) return;
  if (sl.error) {
    ['net_lat', 'net_down', 'net_up'].forEach(id => set(id, '–'));
    set('net_more', `<div class="sub" style="color:var(--bad)">⚠️ ${T.net_unknown}: ${esc(sl.error)}</div>`);
    return;
  }
  const unit = u => ` <span class="unit">${u}</span>`;
  set('net_lat', sl.latency_ms + unit('ms'));
  set('net_down', num(sl.down_mbps, 1) + unit('Mbps'));
  set('net_up', num(sl.up_mbps, 1) + unit('Mbps'));
  set('net_more', row(T.obstructed, num(sl.obstructed_pct) + '%') + row(T.dish_up, ago(Math.round(sl.uptime_h * 60))) +
    (sl.alerts.length ? row(T.alerts, '⚠️ ' + esc(sl.alerts.join(', ')), 'color:var(--warn)') : '') +
    `<div class="sub" style="padding-top:6px">${T.use_note}</div>`);
}

// cameras: a still per camera every 2.5 s while the page is visible, tap one for live video
let cams = null;
function drawCameras(c, selfIp) {
  cams = c;
  show('cams', c);
  if (!c) return;
  show('cam_grid', c.home);
  show('cam_away', !c.home);
  if (!c.home) {
    $('cam_away').textContent = T.cam_away.replace('{url}', 'http://' + (selfIp || 'server') + ':' + (location.port || 80));
    return;
  }
  const fresh = !$('cam_grid').dataset.html;
  set('cam_grid', c.names.map((name, i) => `<button class="cam" data-i="${i}"><span class="none">${T.no_image}</span>` +
    `<img alt="" data-n="${i + 1}" style="visibility:hidden"><span class="name">${esc(name)}</span></button>`).join(''));
  if (fresh) stills();
}
function stills() {
  if (!cams || !cams.home || document.visibilityState !== 'visible') return;
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
  const how = d.conn === 'wired' ? T.wired : d.conn + ' GHz' + (d.signal != null ? ' · ' + d.signal + ' dBm' : '');
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
    const where = x.home ? T.home : T.away + (x.seen_min_ago != null ? ' · ' + T.seen.replace('{m}', ago(x.seen_min_ago)) : '');
    const photos = !mine.length ? '' : ' · 📷 ' + (mine.every(f => !f.need_files) ? '✓' : Math.min(...mine.map(f => f.pct)) + '%');
    let body = (d && d.online ? row(T.wifi, wifiText(d)) : '') + mine.map(f => backupRows(f, bk.mb_s, mine.length > 1 ? '' : T.photos)).join('');
    if (!body) body = `<div class="sub">${T.no_details}</div>`;
    return fold('p:' + x.name, `${dot(x.home ? OK : OFF)}<b>${esc(x.name)}</b><span class="sub right">${where}${photos}</span>`, body);
  }).join(''));
  // folders from phones that aren't a person above get their own card
  const names = people ? people.map(x => x.name) : [];
  const rest = folders.filter(f => !from(f).some(n => names.includes(n)));
  show('bk', rest.length);
  set('bk_list', rest.map(f => backupRows(f, bk.mb_s)).join(''));
}

// the server's own Wi-Fi and its plug's, from the router's list
function drawConnection(dv, s) {
  const devs = (dv && dv.devices) || [];
  const rows = [['📱 ' + T.this_server, s.self_ip], ['🔌 ' + T.the_plug, s.plug_ip]]
    .map(([name, ip]) => [name, ip && devs.find(d => d.last_ip === ip)]).filter(([, d]) => d);
  show('cn', rows.length);
  set('cn_list', rows.map(([name, d]) => row(dot(d.online ? OK : BAD) + name, wifiText(d))).join(''));
}

const KINDS = ['camera', 'computer', 'phone', 'network', 'other'];
const ICON = {camera: '📷', computer: '💻', phone: '📱', network: '🌐', other: '🔌'};
function drawDevices(dv, hide) {
  show('dv', dv && dv.devices);
  if (!(dv && dv.devices)) return;
  // a device that never got an address has no last_ip: never hide it by matching a missing one
  const list = dv.devices.filter(d => !(d.last_ip && hide.includes(d.last_ip)));
  $('dv_title').textContent = '📶 ' + T.devices + (dv.ssid ? ' ' + T.on + ' ' + dv.ssid : '') +
    ' (' + list.filter(d => d.online).length + ')';
  set('dv_list', KINDS.map(k => {
    const g = list.filter(d => d.kind === k);
    if (!g.length) return '';
    const on = g.filter(d => d.online).length, noip = g.some(d => d.online && !d.ip);
    const sum = `${ICON[k]} ${T[k]}<span class="sub right">${T.n_of.replace('{a}', on).replace('{b}', g.length)}` +
      `${k === 'camera' && (on < g.length || noip) ? ' ⚠️' : ''}</span>`;
    return fold('k:' + k, sum, g.map(d => {
      const weak = d.signal != null && d.signal < -75;
      return row(dot(d.online && d.ip ? OK : d.online ? WARN : BAD) + esc(d.name), wifiText(d), weak ? 'color:var(--warn)' : '');
    }).join(''));
  }).join(''));
}

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

function drawChart(h, plug) {
  const svg = $('chart');
  if (!h.length) { svg.innerHTML = ''; return; }
  const t0 = h[0][0], t1 = Math.max(h[h.length - 1][0], t0 + 1);
  const x = t => (t - t0) / (t1 - t0) * 300, y = p => 100 - p;
  const lo = plug && !plug.error ? plug.low : 30, hi = plug && !plug.error ? plug.high : 80;
  const pts = h.map(r => x(r[0]).toFixed(1) + ',' + y(r[1]).toFixed(1)).join(' ');
  svg.innerHTML =
    `<rect x="0" y="${y(hi)}" width="300" height="${hi - lo}" fill="var(--ok)" opacity="0.08"/>` +   // the healthy charge band
    `<polyline points="${pts}" fill="none" stroke="var(--line)" stroke-width="2" vector-effect="non-scaling-stroke"/>`;
}
refresh(); setInterval(refresh, 10000);
</script>
</body></html>"""


def render():
    text = TEXT.get(LANG, TEXT["en"])
    title = CONFIG / "title"  # PANEL_TITLE in .env, written by scripts/08-panel.sh
    text = dict(text, title=title.read_text().strip() if title.exists() else text["title"])
    # "<" escaped so no text can close the <script> it sits in
    page = PAGE.replace("__TEXT__", json.dumps(text).replace("<", "\\u003c")).replace("__LANG__", LANG)
    for key, value in text.items():
        if isinstance(value, str):
            page = page.replace(f"__{key.upper()}__", html.escape(value))
    return page.encode()


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
        if self.path == "/api/status":
            body, kind = json.dumps(status(self.client_address[0])).encode(), "application/json"
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
    CAMERA_NAMES = load_names(CONFIG / "cameras")  # names only; the codes stay in go2rtc's config
    if CAMERA_NAMES:
        kill_leftovers(DATA / "cams")
        STILLS = Stills(len(CAMERA_NAMES), DATA / "cams")
        STILLS.start_reaper()
        # each ffmpeg has its own process group: stopping the panel must stop them too
        signal.signal(signal.SIGTERM, lambda *_: (STILLS.stop_all(), os._exit(0)))
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
