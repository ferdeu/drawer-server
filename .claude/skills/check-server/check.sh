#!/usr/bin/env bash
# Short health report of the phone server, read from the panel's /api/status (no cable needed).
# Tries the home Wi-Fi first, then Tailscale.
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$HERE/../../.." && pwd)"
# shellcheck disable=SC1091
source "$REPO_ROOT/local/phone.env" 2>/dev/null || { echo "No local/phone.env yet: run steps 03 and 04 first."; exit 1; }
PORT="${PANEL_PORT:-8080}"
py=python; python -c '' >/dev/null 2>&1 || py=python3

for ip in "${PHONE_LAN_IP:-}" "${PHONE_TS_IP:-}"; do
  [ -n "$ip" ] || continue
  json="$(curl -s -m 6 "http://$ip:$PORT/api/status")"
  [ -n "$json" ] || { echo "panel: no answer at $ip:$PORT"; continue; }
  echo "panel: answering at $ip:$PORT"
  printf '%s' "$json" | "$py" "$HERE/summary.py"
  exit 0
done

echo "Can't reach the panel. Next checks: is the phone on and on Wi-Fi? Then try SSH;"
echo "if SSH says 'Connection refused', Android stopped Termux: plug the cable and run scripts/restart-server.sh"
exit 1
