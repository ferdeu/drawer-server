#!/usr/bin/env bash
# Bring the server back if Android force-stopped Termux (SSH says "Connection refused").
# Needs the USB cable and the phone unlocked.
source "$(dirname "$0")/lib.sh"

require_device
load_phone_env

say "Opening Termux (its startup restarts the server)"
adb shell input keyevent KEYCODE_WAKEUP
adb shell am start -n com.termux/.app.TermuxActivity >/dev/null
sleep 6
# older installs don't have the auto-restart in ~/.bashrc yet, so also type it
adb shell input text 'sh%s~/.termux/boot/10-sshd.sh'
adb shell input keyevent KEYCODE_ENTER
sleep 4

adb forward tcp:8022 tcp:8022 >/dev/null
phone_ssh 127.0.0.1 'echo "  server is back: $(pgrep -x sshd >/dev/null && echo sshd running)"'
