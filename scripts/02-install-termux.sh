#!/usr/bin/env bash
# Step 2 - Download Termux + Termux:Boot + Termux:API from F-Droid and install them.
# Uses F-Droid's "suggested" (stable) version, not betas.
source "$(dirname "$0")/lib.sh"

require_device

APK_DIR="$REPO_ROOT/apks"
mkdir -p "$APK_DIR"

PKGS="com.termux com.termux.boot com.termux.api"

for p in $PKGS; do
  code="$(curl -sSf "https://f-droid.org/api/v1/packages/$p" | sed -n 's/.*"suggestedVersionCode":\([0-9]*\).*/\1/p')"
  [ -n "$code" ] || die "Could not read the F-Droid version for $p"
  apk="${p}_${code}.apk"
  if [ ! -s "$APK_DIR/$apk" ]; then
    say "Downloading $apk"
    curl -sSfL -o "$APK_DIR/$apk" "https://f-droid.org/repo/$apk"
  fi
  say "Installing $apk"
  warn "Google Play Protect will probably say 'Blocked unsafe app ... built for an older version of Android'."
  warn "On the phone tap the small 'Install anyway' text, NOT the big 'Got it' button (that cancels)."
  warn "See docs/path-a.md for why that warning is expected."
  adb install -r "$(localpath "$APK_DIR/$apk")"
done

say "Excluding the Termux apps from battery optimization and allowing background work"
for p in $PKGS; do
  adb shell "dumpsys deviceidle whitelist +$p >/dev/null
    cmd appops set $p RUN_ANY_IN_BACKGROUND allow
    cmd appops set $p RUN_IN_BACKGROUND allow"
done
adb shell 'pm grant com.termux android.permission.READ_EXTERNAL_STORAGE
  pm grant com.termux android.permission.WRITE_EXTERNAL_STORAGE
  pm grant com.termux android.permission.POST_NOTIFICATIONS' || true

say "Installed:"
adb shell 'pm list packages | grep termux' | tr -d '\r'
