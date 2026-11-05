#!/usr/bin/env bash
# Step 5 - Tailscale: reach the phone from outside your home.
# Opening router ports doesn't work on Starlink and many mobile/fiber ISPs (CGNAT),
# so we use Tailscale: a private network that works from anywhere, free for home use.
source "$(dirname "$0")/lib.sh"

require_device
load_phone_env

APP=com.tailscale.ipn
has_app() { adb shell pm list packages "$APP" | grep -q "$APP"; }
# the VPN interface is tun0 on some phones, tun1 on others (Edge 40)
ts_ip() { adb shell ip -4 addr 2>/dev/null | tr -d '\r' | sed -n 's/.*inet \(100\.[0-9.]*\)\/.* tun[0-9]*$/\1/p' | head -1; }
has_ts_ip() { [ -n "$(ts_ip)" ]; }

if ! has_app; then
  say "Opening Tailscale in the Play Store"
  adb shell input keyevent KEYCODE_WAKEUP
  adb shell am start -a android.intent.action.VIEW -d "market://details?id=$APP" >/dev/null
  wait_for "Tap 'Install' in the Play Store (the phone needs a Google account signed in)." 900 has_app
fi

adb shell dumpsys deviceidle whitelist +$APP >/dev/null

if ! has_ts_ip; then
  say "Opening Tailscale"
  adb shell monkey -p "$APP" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
  wait_for "Log in (Google account is fine), accept the VPN permission, and turn Tailscale ON." 900 has_ts_ip
fi

say "Making Tailscale an always-on VPN, so it reconnects after reboots"
adb shell settings put secure always_on_vpn_app "$APP"

TS_IP="$(ts_ip)"
{ grep -v '^PHONE_TS_IP=' "$REPO_ROOT/local/phone.env"; echo "PHONE_TS_IP=$TS_IP"; } > "$REPO_ROOT/local/phone.env.tmp"
mv "$REPO_ROOT/local/phone.env.tmp" "$REPO_ROOT/local/phone.env"

# Always-on doesn't always bring the VPN back (seen on Android 15: down for hours, no reboot).
# The Tailscale app takes a "connect" broadcast from any app, so Termux can do it.
say "Installing a watcher that reconnects Tailscale if it drops (checks every 2 minutes, starts on boot)"
phone_ssh "${PHONE_LAN_IP:?run scripts/04-network.sh first}" "set -e
command -v ifconfig >/dev/null || pkg install -y net-tools >/dev/null 2>&1 || { echo '  could not install net-tools (ifconfig)' >&2; exit 1; }
mkdir -p ~/bin ~/.cache ~/.termux/boot
cat > ~/bin/tailscale-watch.sh <<'EOF'
#!/data/data/com.termux/files/usr/bin/sh
# Every 2 minutes: no Tailscale address on a tun interface means the VPN is down, so ask the app to connect.
# 'tailscale-watch.sh check' only answers whether it's up (exit 0) or not.
LOG=\$HOME/.cache/tailscale-watch.log
up() { ifconfig 2>/dev/null | awk '/^tun/{t=1;next} /^[^ \t]/{t=0} t && /inet (addr:)?100\./{f=1} END{exit !f}'; }
[ \"\${1:-}\" = check ] && { up; exit; }
down=0
while true; do
  if up; then
    [ \$down = 1 ] && echo \"\$(date '+%F %T') back up\" >> \$LOG
    down=0
  else
    echo \"\$(date '+%F %T') down, asking Tailscale to connect\" >> \$LOG
    am broadcast -a com.tailscale.ipn.CONNECT_VPN -n com.tailscale.ipn/.IPNReceiver >/dev/null 2>&1
    down=1
    tail -n 200 \$LOG > \$LOG.tmp && mv \$LOG.tmp \$LOG
  fi
  sleep 120
done
EOF
chmod +x ~/bin/tailscale-watch.sh
cat > ~/.termux/boot/15-tailscale-watch.sh <<'EOF'
#!/data/data/com.termux/files/usr/bin/sh
# start the Tailscale watcher unless it's already running (matched by its exact command line, not a pid file)
pgrep -f \"^sh \$HOME/bin/tailscale-watch.sh\$\" >/dev/null && exit 0
nohup sh \$HOME/bin/tailscale-watch.sh >/dev/null 2>&1 &
EOF
chmod +x ~/.termux/boot/15-tailscale-watch.sh
rm -f ~/.cache/tailscale-watch.pid  # older versions used one
# Tailscale is up right now, so a 'down' here means the watcher can't read the address on this phone
sh ~/bin/tailscale-watch.sh check || { echo '  the watcher cannot see the Tailscale address on this phone (ifconfig)' >&2; exit 1; }
# restart it, so a re-run picks up a newer watcher
pkill -f \"^sh \$HOME/bin/tailscale-watch.sh\$\" && sleep 1 || true
sh ~/.termux/boot/15-tailscale-watch.sh
sleep 1
pgrep -f \"^sh \$HOME/bin/tailscale-watch.sh\$\" >/dev/null && echo '  watcher running: yes' || { echo '  watcher did not start' >&2; exit 1; }" ||
  die "The Tailscale watcher isn't working (see above). Tailscale itself is set up; run this step again later."

say "Phone's Tailscale address: $TS_IP"
cat <<EOF
  To reach the phone from outside home, install Tailscale on your computer or other phone
  (same account) and use:
     ssh -i ~/.ssh/drawer_server_ed25519 -p 8022 $TERMUX_USER@$TS_IP

  IMPORTANT: Tailscale logs every device out after 180 days, and nobody is there to log the
  server back in. Open https://login.tailscale.com/admin/machines, find this phone, tap the
  "..." menu on its row and choose "Disable key expiry".
EOF

if phone_ssh "$TS_IP" true 2>/dev/null; then
  say "SSH over Tailscale works from this computer."
else
  warn "This computer can't reach $TS_IP yet - normal if Tailscale isn't installed here."
fi
