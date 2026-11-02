#!/usr/bin/env bash
# Step 0 - Recon. Read-only: prints what phone this is. Changes nothing.
source "$(dirname "$0")/lib.sh"

require_device

say "Phone"
for k in ro.product.model ro.product.device ro.boot.hardware.sku ro.carrier \
         ro.build.version.release ro.build.display.id ro.build.version.security_patch \
         ro.board.platform ro.product.cpu.abi ro.treble.enabled \
         ro.boot.flash.locked ro.boot.verifiedbootstate sys.oem_unlock_allowed; do
  printf '  %-34s %s\n' "$k" "$(prop "$k")"
done

say "Memory, storage, battery"
adb shell 'head -1 /proc/meminfo; df -h /data | tail -1; dumpsys battery | grep -E "level|temperature|health"' | tr -d '\r'

say "Wi-Fi"
adb shell 'ip -4 addr show wlan0 | grep inet' | tr -d '\r' || warn "Wi-Fi is off or not connected"

device="$(prop ro.product.device)"
case "$device" in
  fogorow) say "Moto G24 Power detected - a tested phone (docs/devices/moto-g24-power.md)." ;;
  lyriq)   say "Motorola Edge 40 detected - a tested phone (docs/devices/motorola-edge-40.md)." ;;
  *)
    warn "This repo was tested on a Moto G24 Power (fogorow) and a Motorola Edge 40 (lyriq). Yours is '$device'."
    warn "Path A (no unlock, nothing erased) should still work on most Android 11+ phones,"
    warn "but read docs/path-a.md and go step by step." ;;
esac
