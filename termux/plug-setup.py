"""Find a Tuya / Smart Life plug and save what the panel needs to talk to it locally.

Reads from stdin, one per line: Tuya Access ID, Access Secret, region, plug name (may be empty).
The cloud is used once to get the plug's local key; the secret is not saved.
Writes "<id> <ip> <local key> <protocol version>" to the file given as the first argument.
Run by scripts/10-smart-plug.sh.
"""
import sys

import tinytuya

access_id, secret, region, name = [sys.stdin.readline().strip() for _ in range(4)]
devs = tinytuya.Cloud(apiRegion=region, apiKey=access_id, apiSecret=secret).getdevices()
if not isinstance(devs, list):
    sys.exit(f"Tuya cloud said: {devs}")
devs = [d for d in devs if d.get("key") and (not name or d.get("name") == name)]
if len(devs) != 1:
    sys.exit(f"Found {len(devs)} devices. Set TUYA_PLUG_NAME in .env to the plug's name in Smart Life.")
d = devs[0]

found = tinytuya.find_device(d["id"])
if not found.get("ip"):
    sys.exit("The plug is not answering on the Wi-Fi. Is it on and paired?")
plug = tinytuya.OutletDevice(d["id"], found["ip"], d["key"], version=float(found["version"]))
dps = plug.status().get("dps") or {}
if "1" not in dps:
    sys.exit(f"The plug answered but not as expected: {dps}")
# after a power cut, come back on (charging) instead of staying off
if dps.get("38") in ("off", "memory"):
    plug.set_value(38, "on")

with open(sys.argv[1], "w") as f:
    f.write(" ".join([d["id"], found["ip"], d["key"], str(found["version"])]) + "\n")
state = "on" if dps["1"] else "off"
print(f"  {d['name']} at {found['ip']} (protocol {found['version']}), currently {state}")
