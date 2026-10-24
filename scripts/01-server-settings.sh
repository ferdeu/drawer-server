#!/usr/bin/env bash
# Step 1 - Make Android stop killing background programs.
# Reversible: run with --revert to put the factory values back.
source "$(dirname "$0")/lib.sh"

require_device

if [ "${1:-}" = "--revert" ]; then
  say "Reverting to Android defaults"
  adb shell 'settings put global settings_enable_monitor_phantom_procs true
    device_config put activity_manager max_phantom_processes 32
    device_config set_sync_disabled_for_tests none
    settings put global adaptive_battery_management_enabled 1
    settings delete global battery_tip_constants'
  exit 0
fi

say "Turning off the 'phantom process killer' (Android 12+ kills Termux child processes otherwise)"
adb shell 'settings put global settings_enable_monitor_phantom_procs false
  device_config set_sync_disabled_for_tests persistent
  device_config put activity_manager max_phantom_processes 2147483647'

say "Turning off Adaptive Battery (it learns which apps you don't open and freezes them)"
adb shell settings put global adaptive_battery_management_enabled 0

# The "Battery manager" restricts apps it thinks drain battery. It restricted Termux:Boot and
# Termux:API on the test phone, and since the three Termux apps share one Linux user, that
# force-stopped Termux too (SSH went down).
say "Turning off the Battery manager's automatic app restrictions"
adb shell settings put global battery_tip_constants app_restriction_enabled=false

say "Result"
adb shell 'echo "  phantom process monitor: $(settings get global settings_enable_monitor_phantom_procs)"
  echo "  max phantom processes:   $(device_config get activity_manager max_phantom_processes)"
  echo "  adaptive battery:        $(settings get global adaptive_battery_management_enabled)"
  echo "  battery manager:         $(settings get global battery_tip_constants)"' | tr -d '\r'
