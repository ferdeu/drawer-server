#!/usr/bin/env bash
# Everything your TP-Link router knows about each device: name, MAC, IP, fixed address or not,
# cable / 2.4 / 5 GHz, signal, and whether the panel has seen it before. Use it to pick names
# for PANEL_DEVICE_NAMES (step 8). Needs the router's admin password, so only the owner can run it.
#
#   Put ROUTER_URL and ROUTER_PASSWORD in .env, then:  bash scripts/router-devices.sh
#
# Prints a table and saves the full detail to local/router-devices.json (gitignored).
# Runs on the server, which is always home. Read-only: it changes nothing on the router.
source "$(dirname "$0")/lib.sh"

load_phone_env
HOST="${PHONE_LAN_IP:?run scripts/04-network.sh first}"
[ -n "${ROUTER_URL:-}" ] && [ -n "${ROUTER_PASSWORD:-}" ] || die "Put ROUTER_URL and ROUTER_PASSWORD in .env (your router's admin page)"

say "Asking the router (logs out a browser open on the router page)"
phone_ssh "$HOST" "mkdir -p ~/panel ~/.cache/drawer-server; python -c 'import tplinkrouterc6u' 2>/dev/null || pip install -q tplinkrouterc6u"
scp -q -i "$KEY" -P 8022 -o StrictHostKeyChecking=accept-new \
  "$REPO_ROOT/termux/router-devices.py" "$TERMUX_USER@$HOST:panel/router-devices.py"
# the password goes over stdin, never inside a command line
{
  printf '%s\n%s\n' "$ROUTER_URL" "$ROUTER_PASSWORD"
  tr ',' '\n' <<<"${PANEL_DEVICE_NAMES:-}" | sed -n 's/^ *\([0-9A-Fa-f:-]\{17\}\) *= *\(.*[^ ]\) *$/\1 \2/p'
} | phone_ssh "$HOST" 'umask 077; python ~/panel/router-devices.py ~/.cache/drawer-server/router-devices.json'

mkdir -p "$REPO_ROOT/local"
scp -q -i "$KEY" -P 8022 "$TERMUX_USER@$HOST:.cache/drawer-server/router-devices.json" \
  "$(localpath "$REPO_ROOT/local/router-devices.json")"
echo "  Full detail: local/router-devices.json"
echo "  To name a device: add MAC=Name to PANEL_DEVICE_NAMES in .env, then bash scripts/08-panel.sh"
