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
for v in s.get("services", []):
    detail = f" ({v['detail']})" if v.get("detail") else ""
    print(f"  {'OK  ' if v.get('ok') else 'DOWN'} {v['name']}{detail}")
if s.get("plug"):
    print(f"plug: {json.dumps(s['plug'])}")
