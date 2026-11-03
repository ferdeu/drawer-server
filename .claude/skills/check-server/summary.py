"""Turns the panel's /api/status JSON (stdin) into a few readable lines, skipping the long history."""
import json
import sys

s = json.load(sys.stdin)
b = s.get("battery") or {}
line = f"battery: {b.get('percentage')}% {str(b.get('status', '')).lower()}, {b.get('temperature')} C, health {b.get('health')}"
if s.get("battery_stale"):
    line += "  (stale reading: Termux:API may be stopped)"
print(line)

m, d = s.get("memory") or {}, s.get("disk") or {}
print(f"memory free: {m.get('available_mb')} of {m.get('total_mb')} MB; storage free: {d.get('free_gb')} of {d.get('total_gb')} GB")
# how the storage is shared (photo backup, recordings), and the one warning the panel can raise
for k in d.get("kinds", []):
    share = f" of {k['share_gb']} GB" if k.get("share_gb") else ""
    print(f"  storage {k.get('kind')}: {k.get('gb')} GB{share}")
if d.get("warn"):
    print(f"  storage warning: {d['warn']} (near = photo backup over 90% of its share; paused = the panel paused it at 100%)")
for v in s.get("services", []):
    detail = f" ({v['detail']})" if v.get("detail") else ""
    print(f"  {'OK  ' if v.get('ok') else 'DOWN'} {v['name']}{detail}")
if s.get("plug"):
    print(f"plug: {json.dumps(s['plug'])}")
r = s.get("recorder")  # None when the motion recorder (step 12) isn't installed
if r:
    if r.get("stale"):
        print("recorder: NOT RUNNING (no news from it for over a minute)")
    else:
        print(f"recorder: running, {r.get('today')} clips today, {round(r.get('bytes', 0) / 1e9, 1)} GB used")
    if r.get("disk_full"):
        print("  recorder: disk almost full, recording stopped")
    for c in r.get("cameras", []):
        cause = f", looks obstructed ({c['obstructed']})" if c.get("obstructed") else ""
        print(f"  camera {c.get('name')}: {c.get('state')}{cause}")
