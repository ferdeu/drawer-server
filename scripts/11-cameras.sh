#!/usr/bin/env bash
# Step 11 (optional) - Security cameras in the status panel, at home only: a still of each camera
# that refreshes every ~2.5 s, and live video when you tap one. No cloud, no vendor app, no login.
#
# go2rtc (github.com/AlexxIT/go2rtc) talks to the cameras over RTSP and hands live video to the
# panel; it only listens on the phone itself. The panel serves the stills and passes live video on,
# only to devices on the home network.
#
# Before running it:
#   1. Give each camera a fixed IP in the router.
#   2. Put them in .env, one entry per camera:  PANEL_CAMERAS="Front=192.168.1.50:ABCDEF,Back=192.168.1.52:GHIJKL"
#      For Ezviz and Hikvision cameras the code is the verification code on the camera's sticker.
#      Other brands: CAMERA_USER, CAMERA_MAIN_PATH and CAMERA_SUB_PATH (see .env.example).
#
#   bash scripts/11-cameras.sh     (safe to re-run; without PANEL_CAMERAS it skips itself)
# The videos are H.265: most phones, tablets and Chrome on computers play them; some browsers don't.
source "$(dirname "$0")/lib.sh"

GO2RTC_VERSION=1.9.15
GO2RTC_SHA256=af416f22b21a24ab83b8d78642190b4932ae695b4e386853f11d1b0319781763  # GitHub's digest for go2rtc_linux_arm64

load_phone_env
HOST="${PHONE_LAN_IP:?run scripts/04-network.sh first}"
if [ -z "${PANEL_CAMERAS:-}" ]; then
  warn "Skipped: no PANEL_CAMERAS in .env (see the top of this script). Optional step."
  exit 0
fi
USER_="${CAMERA_USER:-admin}"
MAIN="${CAMERA_MAIN_PATH:-/ch1/main/av_stream}"
SUB="${CAMERA_SUB_PATH:-/ch1/sub/av_stream}"

# Name=IP:CODE -> "Name|IP|CODE"; codes go into a URL, so only characters that need no escaping
ENTRIES="$(tr ',' '\n' <<<"$PANEL_CAMERAS" | grep -c '[^ ]' || true)"
CAMS="$(tr ',' '\n' <<<"$PANEL_CAMERAS" |
  sed -n 's/^ *\([^=|]*[^=| ]\) *= *\([0-9]\{1,3\}\(\.[0-9]\{1,3\}\)\{3\}\):\([A-Za-z0-9._~-]\{1,\}\) *$/\1|\2|\4/p')"
[ -n "$CAMS" ] && [ "$(wc -l <<<"$CAMS")" -eq "$ENTRIES" ] ||
  die "PANEL_CAMERAS: each entry is Name=IP:CODE, comma separated (code: letters, numbers, . _ ~ -)"

say "Installing ffmpeg and go2rtc $GO2RTC_VERSION on the phone (first time: ~1 minute)"
# the download only runs if its checksum matches the one pinned above
phone_ssh "$HOST" "set -e
command -v ffmpeg >/dev/null || pkg install -y ffmpeg >/dev/null 2>&1
mkdir -p ~/go2rtc ~/.cache ~/.config/drawer-server ~/.termux/boot
cd ~/go2rtc
if ! echo '$GO2RTC_SHA256  go2rtc' | sha256sum -c --status 2>/dev/null; then
  curl -sSfL -o go2rtc.new https://github.com/AlexxIT/go2rtc/releases/download/v$GO2RTC_VERSION/go2rtc_linux_arm64
  echo '$GO2RTC_SHA256  go2rtc.new' | sha256sum -c --status || { rm -f go2rtc.new; echo 'go2rtc download does not match its checksum: not installed' >&2; exit 1; }
  mv go2rtc.new go2rtc
  chmod 700 go2rtc
fi"

say "Writing the camera settings (codes go over stdin and stay on the phone)"
{
  # "/" lets through only go2rtc's static files (the player script); config and stream edits stay blocked
  printf 'api:\n  listen: "127.0.0.1:1984"\n  allow_paths: [/api/ws, /]\n'
  printf 'rtsp:\n  listen: "127.0.0.1:8554"\nwebrtc:\n  listen: ""\nsrtp:\n  listen: ""\nstreams:\n'
  n=0
  while IFS='|' read -r _ ip code; do
    n=$((n + 1))
    printf '  cam%s: rtsp://%s:%s@%s:554%s\n' "$n" "$USER_" "$code" "$ip" "$SUB"
    printf '  cam%s_hd: rtsp://%s:%s@%s:554%s\n' "$n" "$USER_" "$code" "$ip" "$MAIN"
  done <<<"$CAMS"
} | phone_ssh "$HOST" 'umask 077; cat > ~/.config/drawer-server/go2rtc.yaml'
cut -d'|' -f1 <<<"$CAMS" | phone_ssh "$HOST" 'cat > ~/.config/drawer-server/cameras'

say "Starting go2rtc (starts on boot too)"
phone_ssh "$HOST" "set -e
cat > ~/.termux/boot/60-cameras.sh <<'EOF'
#!/data/data/com.termux/files/usr/bin/sh
# start go2rtc (live video for the panel's cameras) unless it's already running
PID=\$HOME/.cache/go2rtc.pid
if [ -f \$PID ] && kill -0 \"\$(cat \$PID)\" 2>/dev/null; then exit 0; fi
umask 077  # its log can mention camera addresses with their codes
nohup \$HOME/go2rtc/go2rtc -config \$HOME/.config/drawer-server/go2rtc.yaml > \$HOME/.cache/go2rtc.log 2>&1 &
echo \$! > \$PID
EOF
chmod +x ~/.termux/boot/60-cameras.sh
[ -f ~/.cache/go2rtc.pid ] && kill \"\$(cat ~/.cache/go2rtc.pid)\" 2>/dev/null || true
rm -f ~/.cache/go2rtc.pid
sleep 1
sh ~/.termux/boot/60-cameras.sh
for i in 1 2 3 4 5 6 7 8 9 10; do curl -sf -o /dev/null http://127.0.0.1:1984/video-rtc.js && exit 0; sleep 1; done
tail -5 ~/.cache/go2rtc.log | sed 's#//[^@]*@#//***@#g'; exit 1"

say "Restarting the panel, which now shows the cameras"
bash "$REPO_ROOT/scripts/08-panel.sh" | tail -3
