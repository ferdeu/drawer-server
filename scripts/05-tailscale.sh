#!/usr/bin/env bash
# Step 5 - Tailscale: reach the phone from outside your home.
# Opening router ports doesn't work on Starlink and many mobile/fiber ISPs (CGNAT),
# so we use Tailscale: a private network that works from anywhere, free for home use.
source "$(dirname "$0")/lib.sh"

require_device
load_phone_env

APP=com.tailscale.ipn
has_app() { adb shell pm list packages "$APP" | grep -q "$APP"; }
ts_ip() { adb shell ip -4 addr show tun0 2>/dev/null | tr -d '\r' | sed -n 's/.*inet \(100\.[0-9.]*\)\/.*/\1/p'; }
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

say "Phone's Tailscale address: $TS_IP"
cat <<EOF
  To reach the phone from outside home, install Tailscale on your computer or other phone
  (same account) and use:
     ssh -i ~/.ssh/drawer_server_ed25519 -p 8022 $TERMUX_USER@$TS_IP
EOF

if phone_ssh "$TS_IP" true 2>/dev/null; then
  say "SSH over Tailscale works from this computer."
else
  warn "This computer can't reach $TS_IP yet - normal if Tailscale isn't installed here."
fi
