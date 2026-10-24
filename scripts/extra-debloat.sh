#!/usr/bin/env bash
# Optional - Free RAM by removing preinstalled apps the server doesn't need.
# On the test phone this raised available RAM from 4.9 GB to 5.7 GB.
#
#   bash scripts/extra-debloat.sh               remove preinstalled bloat (REVERSIBLE)
#   bash scripts/extra-debloat.sh --revert      bring all of it back
#   bash scripts/extra-debloat.sh --user-apps   ALSO uninstall every app you installed
#                                               (games, banks, WhatsApp...). NOT reversible:
#                                               their data is gone. Only for a phone you
#                                               dedicate to being a server.
#
# Preinstalled apps are removed with "pm uninstall -k --user 0": the app stays in the system
# image, just hidden and stopped for your user, so --revert (or a factory reset) restores it.
# Kept on purpose: Google Play services + Play Store (they update Tailscale), WebView (Tailscale
# login), the keyboard, Motorola system updates, and everything the system needs to boot.
source "$(dirname "$0")/lib.sh"

require_device
mkdir -p "$REPO_ROOT/local"
LOG="$REPO_ROOT/local/removed-system.txt"

BLOAT="
com.facebook.appmanager com.facebook.services com.facebook.system
com.inmobi.installer com.aura.oobe.motorola com.dti.motorola com.taboola.ody com.digitalturbine.ignite
com.lenovo.lsf.user
com.motorola.timeweatherwidget com.motorola.motocare com.motorola.genie com.motorola.help
com.motorola.demo com.motorola.gamemode com.motorola.livewallpaper3 com.motorola.motocit
com.ape.fmradio com.ape.soundrecorder com.ape.personalize com.ape.faceunlock com.myos.camera
com.goodix.gftest com.fingerprints.sensortesttool
com.android.chrome com.google.android.googlequicksearchbox com.google.android.apps.googleassistant
com.google.android.apps.maps com.google.android.apps.messaging com.google.android.apps.docs
com.google.android.apps.photos com.google.android.apps.tachyon com.google.android.apps.turbo
com.google.android.apps.wellbeing com.google.android.apps.youtube.music com.google.android.youtube
com.google.android.videos com.google.android.calendar com.google.android.gm com.google.android.keep
com.google.android.calculator com.google.android.deskclock com.google.android.projection.gearhead
com.google.android.apps.restore com.google.android.feedback com.google.android.marvin.talkback
com.google.android.accessibility.switchaccess com.google.android.apps.wallpaper
com.google.android.as com.google.android.as.oss com.google.ambient.streaming
com.google.android.apps.nbu.files com.google.android.gms.location.history
com.google.android.printservice.recommendation com.google.android.apps.carrier.carrierwifi
com.google.android.apps.safetyhub com.google.android.tts com.google.android.contacts com.google.android.dialer
"
KEEP_USER_APPS='^(com\.termux|com\.termux\.boot|com\.termux\.api|com\.tailscale\.ipn)$'

if [ "${1:-}" = "--revert" ]; then
  say "Restoring preinstalled apps"
  for p in $BLOAT; do adb shell cmd package install-existing "$p" >/dev/null 2>&1 && echo "  restored $p"; done
  exit 0
fi

say "Saving the current app lists to local/ (so you know what was there)"
adb shell pm list packages -3 > "$REPO_ROOT/local/pkgs-user-before.txt"
adb shell pm list packages -s > "$REPO_ROOT/local/pkgs-system-before.txt"

if [ "${1:-}" = "--user-apps" ]; then
  warn "Uninstalling EVERY app you installed except Termux and Tailscale. Their data will be lost."
  for p in $(adb shell pm list packages -3 | tr -d '\r' | sed 's/package://' | grep -vE "$KEEP_USER_APPS"); do
    printf '  %-50s %s\n' "$p" "$(adb shell pm uninstall "$p" | tr -d '\r')"
  done
fi

say "Removing preinstalled bloat (reversible with --revert)"
installed="$(adb shell pm list packages | tr -d '\r' | sed 's/package://')"
n=0
for p in $BLOAT; do
  grep -qxF "$p" <<<"$installed" || continue
  if [ "$(adb shell pm uninstall -k --user 0 "$p" | tr -d '\r')" = "Success" ]; then
    echo "$p" >> "$LOG"; n=$((n + 1))
  fi
done
echo "  removed $n apps"

say "RAM available now"
adb shell grep MemAvailable /proc/meminfo | tr -d '\r'
