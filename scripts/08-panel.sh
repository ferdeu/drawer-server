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

say "Installing Python and starting the panel (starts on boot too)"
phone_ssh "$HOST" "set -e
command -v python >/dev/null || pkg install -y python >/dev/null 2>&1
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
