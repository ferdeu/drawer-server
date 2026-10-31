#!/usr/bin/env bash
# Runs the Python tests on the phone (they need Linux): copies termux/panel and tests/ to
# ~/drawer-tests and runs unittest there. Over Wi-Fi, no cable.
#   bash tests/run-on-phone.sh
source "$(dirname "$0")/../scripts/lib.sh"

load_phone_env
HOST="${PHONE_LAN_IP:?run scripts/04-network.sh first}"
phone_ssh "$HOST" 'rm -rf ~/drawer-tests; mkdir -p ~/drawer-tests/termux'
scp -q -r -i "$KEY" -P 8022 -o StrictHostKeyChecking=accept-new \
  "$REPO_ROOT/termux/panel" "$REPO_ROOT/tests" "$TERMUX_USER@$HOST:drawer-tests/"
phone_ssh "$HOST" 'cd ~/drawer-tests && mv panel termux/ && python -m unittest discover -s tests 2>&1'
