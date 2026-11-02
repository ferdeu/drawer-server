#!/usr/bin/env bash
# Step 4 - Home network. Shows the phone's address and tests SSH over Wi-Fi (no cable).
# The fixed-IP part happens in YOUR router's web page; this script tells you what to type there.
source "$(dirname "$0")/lib.sh"

require_device
load_phone_env

IP="$(adb shell ip -4 addr show wlan0 | tr -d '\r' | sed -n 's/.*inet \([0-9.]*\)\/.*/\1/p')"
[ -n "$IP" ] || die "The phone is not on Wi-Fi. Connect it to your home network first."
WIFI="$(adb shell 'dumpsys wifi 2>/dev/null | grep "mWifiInfo SSID" | head -1' | tr -d '\r' || true)"
MAC="$(sed -n 's/.*MAC: \([0-9a-f:]*\).*/\1/p' <<<"$WIFI")"
RSSI="$(sed -n 's/.*RSSI: \(-[0-9]*\).*/\1/p' <<<"$WIFI")"

say "Phone on Wi-Fi"
echo "  IP address : $IP"
echo "  MAC address: $MAC"
echo "  Signal     : ${RSSI} dBm   (-50 great, -67 fine, below -75 move the phone closer to the router)"
# second hex digit 2, 6, a or e = a made-up "private" MAC; some phones (Edge 40, Android 15)
# change it now and then on the same network, and the router reservation stops matching
case "${MAC:1:1}" in
  [26aeAE]) warn "That MAC is made up by Android for privacy. Some phones change it now and then, and the
    reservation below stops working. Safer: on the phone, Wi-Fi > your network > Privacy (or MAC type) >
    Use device MAC. It reconnects; then run this step again." ;;
esac

say "Testing SSH over Wi-Fi"
phone_ssh "$IP" 'echo "  ok - $(whoami) on $(getprop ro.product.model)"'

{ grep -vE '^PHONE_(LAN_IP|MAC)=' "$REPO_ROOT/local/phone.env"; echo "PHONE_LAN_IP=$IP"; echo "PHONE_MAC=$MAC"; } > "$REPO_ROOT/local/phone.env.tmp"
mv "$REPO_ROOT/local/phone.env.tmp" "$REPO_ROOT/local/phone.env"

say "Now give it a fixed address in your router (DHCP reservation)"
cat <<EOF
  1. Open your router page (TP-Link: http://192.168.0.1 or http://192.168.1.1 or http://tplinkwifi.net).
  2. Find "Address Reservation". TP-Link Archer AX23 (tested): Advanced > Network > DHCP Server
     > Address Reservation > Add. Press Tab after typing the IP, or SAVE stays greyed out.
  3. Add:  MAC = $MAC   IP = $IP
  4. Save. From now on the phone always gets $IP at home.

  To connect from this computer any time:
     ssh -i ~/.ssh/drawer_server_ed25519 -p 8022 $TERMUX_USER@$IP
EOF
