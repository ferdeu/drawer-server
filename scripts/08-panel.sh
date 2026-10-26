#!/usr/bin/env bash
# Step 8 - Status panel: a web page on the phone with battery, temperature, memory, disk,
# which services are alive, and a 24-hour battery chart.
#
#   bash scripts/08-panel.sh       then open http://<phone-ip>:8080
#   PANEL_LANG=es in .env shows it in Spanish
source "$(dirname "$0")/lib.sh"

load_phone_env
HOST="${PHONE_LAN_IP:?run scripts/04-network.sh first}"
PANEL_PORT="${PANEL_PORT:-8080}"
PANEL_LANG="${PANEL_LANG:-en}"

say "Copying the panel to the phone"
phone_ssh "$HOST" 'mkdir -p ~/panel'
scp -q -i "$KEY" -P 8022 -o StrictHostKeyChecking=accept-new \
  "$REPO_ROOT/termux/panel/panel.py" "$TERMUX_USER@$HOST:panel/panel.py"

# Optional home cards, configured from .env:
#   PANEL_STARLINK=yes                      read the Starlink dish (192.168.100.1)
#   PANEL_PRINTER_IP=192.168.1.30           Epson ink levels
#   PANEL_PEOPLE="Ana=192.168.1.20,Bo=192.168.1.21"   who's home (give their phones fixed IPs)
#   PANEL_ROUTER=tplink                     every device on the Wi-Fi, from a TP-Link router's web API
#                                           (uses ROUTER_URL and ROUTER_PASSWORD)
#   PANEL_DEVICE_NAMES="F4-70-18-00-00-01=Doorbell,..."   names for devices that don't report one
PEOPLE_LINES="$(tr ',' '\n' <<<"${PANEL_PEOPLE:-}" | sed -n 's/^ *\([^=]*[^= ]\) *= *\([0-9.]*\) *$/\1 \2/p')"

# the router password and the device names go over stdin, never inside a command line
phone_ssh "$HOST" 'mkdir -p ~/.config/drawer-server; rm -f ~/.config/drawer-server/router ~/.config/drawer-server/device-names'
if [ "${PANEL_ROUTER:-}" = tplink ]; then
  say "Router card: installing the TP-Link client (first time: ~2 minutes)"
  [ -n "${ROUTER_URL:-}" ] && [ -n "${ROUTER_PASSWORD:-}" ] || die "PANEL_ROUTER=tplink needs ROUTER_URL and ROUTER_PASSWORD in .env"
  printf '%s\n%s\n' "$ROUTER_URL" "$ROUTER_PASSWORD" | phone_ssh "$HOST" 'umask 077; cat > ~/.config/drawer-server/router'
  phone_ssh "$HOST" "python -c 'import tplinkrouterc6u' 2>/dev/null || pip install -q tplinkrouterc6u"
  if [ -n "${PANEL_DEVICE_NAMES:-}" ]; then
    tr ',' '\n' <<<"$PANEL_DEVICE_NAMES" | sed -n 's/^ *\([0-9A-Fa-f:-]\{17\}\) *= *\(.*[^ ]\) *$/\1 \2/p' |
      phone_ssh "$HOST" 'cat > ~/.config/drawer-server/device-names'
  fi
fi

say "Installing tools and starting the panel (starts on boot too)"
phone_ssh "$HOST" "set -e
command -v python >/dev/null || pkg install -y python >/dev/null 2>&1
command -v grpcurl >/dev/null || pkg install -y grpcurl >/dev/null 2>&1
command -v snmpget >/dev/null || pkg install -y net-snmp >/dev/null 2>&1
C=~/.config/drawer-server
rm -f \$C/starlink \$C/printer \$C/people
[ '${PANEL_STARLINK:-}' = yes ] && touch \$C/starlink
[ -n '${PANEL_PRINTER_IP:-}' ] && echo '${PANEL_PRINTER_IP:-}' > \$C/printer
[ -n '$PEOPLE_LINES' ] && printf '%s\n' '$PEOPLE_LINES' > \$C/people
true
cat > ~/.termux/boot/40-panel.sh <<'EOF'
#!/data/data/com.termux/files/usr/bin/sh
# start the status panel unless it's already running
PID=\$HOME/panel/panel.pid
if [ -f \$PID ] && kill -0 \"\$(cat \$PID)\" 2>/dev/null; then exit 0; fi
PANEL_PORT=$PANEL_PORT PANEL_LANG=$PANEL_LANG nohup python \$HOME/panel/panel.py > \$HOME/panel/panel.log 2>&1 &
echo \$! > \$PID
EOF
chmod +x ~/.termux/boot/40-panel.sh
# restart so a new panel.py takes effect
[ -f ~/panel/panel.pid ] && kill \"\$(cat ~/panel/panel.pid)\" 2>/dev/null || true
rm -f ~/panel/panel.pid
sh ~/.termux/boot/40-panel.sh
sleep 4
curl -sf http://127.0.0.1:$PANEL_PORT/api/status >/dev/null || { cat ~/panel/panel.log; exit 1; }"

say "Panel ready"
echo "  At home:        http://$HOST:$PANEL_PORT"
[ -n "${PHONE_TS_IP:-}" ] && echo "  From anywhere:  http://$PHONE_TS_IP:$PANEL_PORT  (with Tailscale on your device)"
