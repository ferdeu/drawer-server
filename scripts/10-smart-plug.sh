#!/usr/bin/env bash
# Step 10 (optional) - A Wi-Fi smart plug (Tuya / Smart Life) that cycles the charger:
# off at 80%, back on at 30% (CHARGE_HIGH / CHARGE_LOW in .env, then re-run step 8). Without root Android can't stop charging by itself, and a phone
# kept at 100% all day wears its battery out (it can even swell).
#
# Before running it:
#   1. Pair the plug with the Smart Life app (2.4 GHz Wi-Fi) and plug the phone's charger into it.
#   2. Get the plug's local key (one time, free): create an account at iot.tuya.com,
#      Cloud > Development > Create Cloud Project (Smart Home, your region's data center),
#      Devices > Link App Account (scan the QR with Smart Life: Me > scan icon).
#   3. Copy the project's Access ID and Access Secret into .env: TUYA_ACCESS_ID, TUYA_ACCESS_SECRET,
#      TUYA_REGION (us = Western America, eu, in, cn). TUYA_PLUG_NAME if you have more than one device.
#
#   bash scripts/10-smart-plug.sh
# After that the phone talks to the plug over the home network only; the cloud isn't needed.
source "$(dirname "$0")/lib.sh"

load_phone_env
HOST="${PHONE_LAN_IP:?run scripts/04-network.sh first}"
[ -n "${TUYA_ACCESS_ID:-}" ] && [ -n "${TUYA_ACCESS_SECRET:-}" ] || die "Put TUYA_ACCESS_ID and TUYA_ACCESS_SECRET in .env (see the top of this script)"

say "Installing the Tuya client on the phone (first time: ~1 minute)"
phone_ssh "$HOST" "python -c 'import tinytuya' 2>/dev/null || { pkg install -y python-cryptography >/dev/null 2>&1 && pip install -q tinytuya; }"

say "Finding the plug (asks Tuya's cloud for its key once, then looks for it on the Wi-Fi)"
scp -q -i "$KEY" -P 8022 -o StrictHostKeyChecking=accept-new \
  "$REPO_ROOT/termux/plug-setup.py" "$TERMUX_USER@$HOST:panel/plug-setup.py"
# the cloud secret goes over stdin and is not stored on the phone; only the plug's local key is
printf '%s\n%s\n%s\n%s\n' "$TUYA_ACCESS_ID" "$TUYA_ACCESS_SECRET" "${TUYA_REGION:-us}" "${TUYA_PLUG_NAME:-}" |
  phone_ssh "$HOST" 'umask 077; mkdir -p ~/.config/drawer-server; python ~/panel/plug-setup.py ~/.config/drawer-server/plug'

say "Restarting the panel, which now runs the charge cycling"
bash "$REPO_ROOT/scripts/08-panel.sh" | tail -3
echo "  Give the plug a fixed IP in the router so the phone always finds it."
