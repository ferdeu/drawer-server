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
    """termux-battery-status (Termux:API). Slow-ish (~1 s), so callers use the cached copy."""
    try:
        out = subprocess.run(["termux-battery-status"], capture_output=True, text=True, timeout=15)
        return json.loads(out.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {}


def battery_logger():
    global _battery
    while True:
        b = battery()
        if b:
            _battery = b
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


def status():
    services = [
        {"name": "SSH", "ok": process_running("sshd")},
        {"name": "NextDNS", "ok": pid_alive(HOME / ".cache" / "nextdns-link.pid"), "detail": nextdns_last()},
    ]
    if (HOME / "luanti").exists():
        players = luanti_players()
        services.append({"name": "Luanti", "ok": pid_alive(HOME / "luanti" / "server.pid") and process_running("luantiserver"),
                         "players": players})
    history = []
    if BATTERY_LOG.exists():
        day_ago = time.time() - 24 * 3600
        for row in csv.reader(BATTERY_LOG.read_text().splitlines()):
            if len(row) >= 3 and row[1] and int(row[0]) >= day_ago:
                history.append([int(row[0]), float(row[1]), float(row[2] or 0)])
    return {"battery": _battery, "memory": memory(), "disk": disk(), "uptime_h": uptime_hours(),
            "services": services, "history": history, "time": int(time.time())}


TEXT = {
    "en": {"title": "Drawer server", "battery": "Battery", "temp": "Temperature", "ram": "Free memory",
           "disk": "Free storage", "uptime": "Up for", "hours": "h", "services": "Services",
           "players": "playing", "nobody": "nobody playing", "history": "Battery, last 24 h",
           "charging": "charging", "not_charging": "on battery", "updated": "updated"},
    "es": {"title": "Servidor del cajón", "battery": "Batería", "temp": "Temperatura", "ram": "Memoria libre",
           "disk": "Espacio libre", "uptime": "Prendido hace", "hours": "h", "services": "Servicios",
           "players": "jugando", "nobody": "nadie jugando", "history": "Batería, últimas 24 h",
           "charging": "cargando", "not_charging": "a batería", "updated": "actualizado"},
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
</style></head>
<body>
<h1>📱 __TITLE__</h1>
<div class="grid">
  <div class="card"><div class="label">🔋 __BATTERY__</div><div class="big" id="bat">–</div><div class="sub" id="plug"></div></div>
  <div class="card"><div class="label">🌡️ __TEMP__</div><div class="big" id="temp">–</div></div>
  <div class="card"><div class="label">🧠 __RAM__</div><div class="big" id="ram">–</div><div class="sub" id="ramsub"></div></div>
  <div class="card"><div class="label">💾 __DISK__</div><div class="big" id="disk">–</div><div class="sub" id="up"></div></div>
  <div class="card wide"><div class="label">⚙️ __SERVICES__</div><div id="svcs"></div></div>
  <div class="card wide"><div class="label">📈 __HISTORY__</div><svg id="chart" viewBox="0 0 300 100" preserveAspectRatio="none"></svg></div>
</div>
<div class="foot" id="foot"></div>
<script>
const T = __TEXT__;
const $ = id => document.getElementById(id);
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
      if (v.players) detail = v.players.length ? v.players.length + ' ' + T.players + ': ' + v.players.join(', ') : T.nobody;
      return `<div class="svc"><span><span class="dot" style="background:${color(v.ok)}"></span>${v.name}</span><span class="sub">${detail}</span></div>`;
    }).join('');
    drawChart(s.history);
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
refresh(); setInterval(refresh, 10000);
</script>
</body></html>"""


def render():
    text = TEXT.get(LANG, TEXT["en"])
    page = PAGE.replace("__TEXT__", json.dumps(text)).replace("__LANG__", LANG)
    for key in ("title", "battery", "temp", "ram", "disk", "services", "history"):
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
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
