"""Everything a TP-Link router knows about each device, merged by MAC address.

Reads from stdin: router URL, admin password, then 'MAC Name' lines (the names from PANEL_DEVICE_NAMES).
Merges what's connected now, the DHCP leases, the address reservations and the devices the panel has
seen before. Prints a table and writes the full detail as JSON to the file given as the first argument.
Run by scripts/router-devices.sh.
"""
import json
import sys
import time
from pathlib import Path

from tplinkrouterc6u import TplinkRouterProvider

url, password = sys.stdin.readline().strip(), sys.stdin.readline().strip()
names = {}
for line in sys.stdin.read().splitlines():
    if line.strip():
        mac, name = line.split(None, 1)
        names[mac.upper().replace(":", "-")] = name.strip()


def plain(obj):
    """A library object as a dict of simple values (enums by name, addresses as text)."""
    out = {}
    for k, v in vars(obj).items():
        k = k.lstrip("_")
        if v is None or isinstance(v, (bool, int, float, str)):
            out[k] = v
        else:
            out[k] = getattr(v, "name", None) or str(v)
    return out


router = TplinkRouterProvider.get_client(url, password)
for attempt in range(3):
    try:
        router.authorize()  # one admin at a time: the panel's own check may be logged in for a moment
        break
    except Exception as e:
        if attempt == 2:
            sys.exit(f"Couldn't log into the router: {e}")
        time.sleep(10)
try:
    connected = [plain(d) for d in router.get_status().devices]
    leases = [plain(d) for d in router.get_ipv4_dhcp_leases()]
    reservations = [plain(d) for d in router.get_ipv4_reservations()]
finally:
    router.logout()

seen_file = Path.home() / ".cache" / "drawer-server" / "devices.json"  # the panel's history
seen = json.loads(seen_file.read_text()) if seen_file.exists() else {}

devices = {}


def entry(mac):
    mac = str(mac).upper().replace(":", "-")
    return devices.setdefault(mac, {"mac": mac, "panel_name": names.get(mac)})


for d in connected:
    entry(d.get("macaddr") or d.get("macaddress"))["connected"] = d
for d in leases:
    entry(d.get("macaddr") or d.get("macaddress"))["lease"] = d
for d in reservations:
    entry(d.get("macaddr") or d.get("macaddress"))["reservation"] = d
for mac, d in seen.items():
    entry(mac)["panel_history"] = d

try:  # the group the panel will put it in, from the same rules
    sys.path.insert(0, str(Path.home() / "panel"))
    from panel import device_kind
except Exception:
    device_kind = None

PLACEHOLDERS = ("", "--", "network device")  # what TP-Link shows when the device gave no name


def real_name(*candidates):
    return next((n for n in candidates if n and n not in PLACEHOLDERS), None)


for mac, d in devices.items():
    c, r, l = d.get("connected", {}), d.get("reservation", {}), d.get("lease", {})
    # the panel's history keeps a name the device reported on an earlier visit
    d["router_name"] = real_name(c.get("hostname"), r.get("hostname"), l.get("hostname"),
                                 d.get("panel_history", {}).get("host"))
    d["private_mac"] = mac[1:2] in "26AE"  # phones make one up per Wi-Fi network
    if device_kind:
        d["panel_group"] = device_kind(d["panel_name"] or d["router_name"] or "", mac)

Path(sys.argv[1]).write_text(json.dumps(sorted(devices.values(), key=lambda d: d["mac"]), indent=1))

rows = []
for mac, d in sorted(devices.items(), key=lambda kv: (kv[1].get("panel_group") or "", kv[0])):
    c, r, l = d.get("connected", {}), d.get("reservation", {}), d.get("lease", {})
    ip = c.get("ipaddr") or c.get("ipaddress") or l.get("ipaddr") or l.get("ipaddress") or ""
    if ip in ("0.0.0.0", "None"):
        ip = ""
    if r:
        ip = f"{ip or '-'} (fixed {r.get('ipaddr') or r.get('ipaddress')})" if ip != (r.get("ipaddr") or r.get("ipaddress")) else f"{ip} (fixed)"
    conn = c.get("type", "").replace("HOST_", "").replace("GUEST_", "guest ").replace("2G", "2.4").replace("5G", "5")
    sig = f"{c['signal']} dBm" if c.get("signal") else ""
    if c:
        state = f"online {(c.get('online_time') or 0) / 3600:.1f} h"  # online_time is in seconds
    elif d.get("panel_history", {}).get("last"):
        state = f"seen {round((time.time() - d['panel_history']['last']) / 3600)} h ago"
    else:
        state = "offline"
    mb = f"{c['traffic_usage'] / 1e6:.0f} MB" if c.get("traffic_usage") else ""
    rows.append((d.get("panel_group") or "", mac, d["panel_name"] or "", d["router_name"] or "", ip,
                 conn.lower(), c.get("ap_name") or "", sig, state, mb))

# names come from the devices themselves: drop control characters before they reach the terminal
rows = [tuple("".join(ch for ch in str(x) if ch.isprintable()) for x in row) for row in rows]
head = ("group", "MAC", "name in .env", "name it reports", "IP", "conn", "AP", "signal", "now", "traffic")
widths = [max(len(str(x)) for x in col) for col in zip(head, *rows)]
for row in (head, *rows):
    print("  ".join(x.ljust(w) for x, w in zip(row, widths)).rstrip())
print(f"\n{len(connected)} connected now, {len(devices)} known in all")
unnamed = [m for m, d in devices.items() if not d["panel_name"] and not d["router_name"]]
if unnamed:
    print("No name anywhere (add them to PANEL_DEVICE_NAMES): " + ", ".join(unnamed))
