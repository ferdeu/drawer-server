#!/usr/bin/env bash
# Step 3 - Set up SSH so you can control the phone from your computer's keyboard.
# Creates a key on this computer, sends the public half to the phone, opens Termux
# and types the bootstrap command for you. Then tests the connection over USB.
source "$(dirname "$0")/lib.sh"

require_device

if [ ! -f "$KEY" ]; then
  say "Creating an SSH key for this computer ($KEY)"
  mkdir -p "$HOME/.ssh"
  ssh-keygen -t ed25519 -N "" -C "drawer-server@$(hostname)" -f "$KEY"
fi

say "Copying the public key and the bootstrap script to the phone"
adb shell "mkdir -p $PHONE_DIR && rm -f $PHONE_DIR/status"
adb push "$(localpath "$KEY.pub")" "$PHONE_DIR/authorized_keys" >/dev/null
adb push "$(localpath "$REPO_ROOT/termux/bootstrap.sh")" "$PHONE_DIR/bootstrap.sh" >/dev/null

status() { adb shell "cat $PHONE_DIR/status 2>/dev/null" | tr -d '\r'; }

# Termux:Boot only starts working after it has been opened once
adb shell am start -n com.termux.boot/.BootActivity >/dev/null || true
sleep 2

say "Opening Termux on the phone"
warn "Unlock the phone screen and leave it on Termux. Don't touch it until this script says so."
adb shell input keyevent KEYCODE_WAKEUP
adb shell am start -n com.termux/.app.TermuxActivity >/dev/null
# First launch unpacks a mini Linux; give it time before typing.
sleep 25

started=""
for attempt in 1 2 3; do
  say "Typing the bootstrap command into Termux (attempt $attempt)"
  adb shell input text "bash%s$PHONE_DIR/bootstrap.sh"
  adb shell input keyevent KEYCODE_ENTER
  for _ in $(seq 1 10); do
    sleep 2
    if [ -n "$(status)" ]; then started=1; break; fi
  done
  [ -n "$started" ] && break
  warn "Termux didn't start the script yet. Retrying..."
done
[ -n "$started" ] || die "Termux never ran the script. Open Termux by hand and type: bash $PHONE_DIR/bootstrap.sh"

say "Installing packages inside Termux (a few minutes, needs Wi-Fi)"
for _ in $(seq 1 180); do
  s="$(status)"
  case "$s" in
    *ready*) break ;;
    *failed*) die "The bootstrap failed on the phone: $s  (look at the Termux screen)" ;;
  esac
  sleep 5
done
case "$(status)" in *ready*) ;; *) die "Timed out waiting for Termux. Look at the phone screen." ;; esac

TUSER="$(status | sed -n 's/.*ready user=\([^ ]*\).*/\1/p')"
say "Testing SSH over the USB cable (adb forward 8022)"
adb forward tcp:8022 tcp:8022 >/dev/null
ssh -i "$KEY" -p 8022 -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 \
  "$TUSER@127.0.0.1" 'echo "Hello from $(uname -m) Termux, $(nproc) CPU cores, uptime: $(uptime)"'

mkdir -p "$REPO_ROOT/local"
touch "$REPO_ROOT/local/phone.env"
{ grep -v '^TERMUX_USER=' "$REPO_ROOT/local/phone.env"; echo "TERMUX_USER=$TUSER"; } > "$REPO_ROOT/local/phone.env.tmp"
mv "$REPO_ROOT/local/phone.env.tmp" "$REPO_ROOT/local/phone.env"
say "SSH works. Termux user: $TUSER (saved in local/phone.env)"
