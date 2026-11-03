#!/usr/bin/env bash
# Step 12 (optional) - Motion recording for the step 11 cameras: when something moves, the phone saves
# a short clip (a few seconds before and after too). The clips stay on the phone, in ~/recordings,
# and show up in the panel's Recordings section, at home only. Nothing goes to the cloud.
#
# The recorder runs around the clock and reads every camera all the time, so the phone works harder
# and runs warmer (see docs/path-a.md). Check the panel's temperature after the first day.
#
# Before running it:
#   1. Step 11 must be done (bash scripts/11-cameras.sh).
#   2. In .env: RECORDER=yes. Everything else is optional (see .env.example): RECORD_CAMERAS,
#      RECORD_BEFORE, RECORD_AFTER, RECORD_SENSITIVITY, RECORD_CHECK, RECORD_OBSTRUCTED, and the
#      DISK_* lines of step 8 that say how much room the clips may take.
#
#   bash scripts/12-recorder.sh     (safe to re-run; changes in .env apply when you run it again)
# To turn it off: take RECORDER=yes out of .env and run it again. The clips stay on the phone.
source "$(dirname "$0")/lib.sh"

load_phone_env
HOST="${PHONE_LAN_IP:?run scripts/04-network.sh first}"

phone_ssh "$HOST" 'test -f ~/.config/drawer-server/cameras && test -f ~/.termux/boot/60-cameras.sh' ||
  die "Run step 11 first (bash scripts/11-cameras.sh)"

# Stop the recorder: ask nicely, wait up to 5 s, then kill it and any ffmpeg it left behind.
# The pid is only signalled if it really is the recorder (after a reboot the number may belong to
# something else); the pkill pattern is written [-]user_agent so it doesn't match this very command.
# shellcheck disable=SC2016  # runs on the phone
STOP_RECORDER='P=~/panel/recorder.pid
is_recorder() { tr "\0" " " 2>/dev/null < "/proc/$1/cmdline" | grep -q "recorder\.py"; }
RPID=""
[ -f "$P" ] && RPID="$(cat "$P")"
case "$RPID" in *[!0-9]*) RPID="" ;; esac
if [ -n "$RPID" ] && is_recorder "$RPID"; then
  kill "$RPID" 2>/dev/null || true
  for i in 1 2 3 4 5 6 7 8 9 10; do
    is_recorder "$RPID" || break
    sleep 0.5
  done
  if is_recorder "$RPID"; then
    kill -9 "$RPID" 2>/dev/null || true
    pkill -f -- "[-]user_agent drawer-recorder" || true
  fi
fi
rm -f "$P"'

if [ "${RECORDER:-}" != yes ]; then
  if phone_ssh "$HOST" 'test -f ~/.termux/boot/70-recorder.sh'; then
    say "Turning the recorder off (the clips stay on the phone)"
    phone_ssh "$HOST" "$STOP_RECORDER; rm -f ~/.termux/boot/70-recorder.sh ~/.config/drawer-server/recorder ~/.cache/drawer-server/recorder.json"
    echo "  The recorder is off and won't start again on boot."
    echo "  The clips are still on the phone, in ~/recordings (reach them with SFTP)."
    echo "  To delete them: ssh into the phone and run   rm -r ~/recordings"
    bash "$REPO_ROOT/scripts/08-panel.sh" | tail -3
    exit 0
  fi
  warn "Skipped: RECORDER isn't yes in .env. Optional step."
  exit 0
fi

# Camera names from PANEL_CAMERAS, parsed like step 11
NAMES="$(tr ',' '\n' <<<"${PANEL_CAMERAS:-}" |
  sed -n 's/^ *\([^=|]*[^=| ]\) *= *[0-9.]\{1,\}:[A-Za-z0-9._~-]\{1,\} *$/\1/p')"
[ -n "$NAMES" ] || die "PANEL_CAMERAS is empty or wrong in .env: the recorder uses the cameras of step 11"

CHOSEN=""
if [ -n "${RECORD_CAMERAS:-}" ]; then
  while IFS= read -r cam; do
    cam="$(sed 's/^ *//; s/ *$//' <<<"$cam")"
    [ -n "$cam" ] || continue
    grep -qxF -- "$cam" <<<"$NAMES" ||
      die "RECORD_CAMERAS: no camera called '$cam'. The cameras in PANEL_CAMERAS are: $(paste -sd, - <<<"$NAMES")"
    CHOSEN="${CHOSEN:+$CHOSEN,}$cam"
  done < <(tr ',' '\n' <<<"$RECORD_CAMERAS")
fi

in_range() { # in_range <name> <value> <min> <max>
  [[ -z "$2" ]] && return 0
  [[ "$2" =~ ^[0-9]+$ ]] && [ "$2" -ge "$3" ] && [ "$2" -le "$4" ] ||
    die "$1 should be a whole number from $3 to $4 (got '$2')"
}
in_range RECORD_BEFORE "${RECORD_BEFORE:-}" 0 30
in_range RECORD_AFTER "${RECORD_AFTER:-}" 2 60
in_range RECORD_SENSITIVITY "${RECORD_SENSITIVITY:-}" 1 10
[[ "${RECORD_CHECK:-}" =~ ^(fast|light)?$ ]] || die "RECORD_CHECK should be fast or light (got '${RECORD_CHECK:-}')"
[[ "${RECORD_OBSTRUCTED:-}" =~ ^(keep|pause)?$ ]] || die "RECORD_OBSTRUCTED should be keep or pause (got '${RECORD_OBSTRUCTED:-}')"

say "Writing the recorder settings"
phone_ssh "$HOST" 'mkdir -p ~/.config/drawer-server ~/.cache/drawer-server ~/.termux/boot ~/panel'
printf 'cameras=%s\nbefore=%s\nafter=%s\nsensitivity=%s\ncheck=%s\nobstructed=%s\n' \
  "$CHOSEN" "${RECORD_BEFORE:-}" "${RECORD_AFTER:-}" "${RECORD_SENSITIVITY:-}" "${RECORD_CHECK:-}" "${RECORD_OBSTRUCTED:-}" |
  phone_ssh "$HOST" 'cat > ~/.config/drawer-server/recorder'

say "Copying the recorder to the phone"
scp -q -i "$KEY" -P 8022 -o StrictHostKeyChecking=accept-new \
  "$REPO_ROOT"/termux/panel/*.py "$TERMUX_USER@$HOST:panel/"
phone_ssh "$HOST" 'cat > ~/.termux/boot/70-recorder.sh && chmod +x ~/.termux/boot/70-recorder.sh' <<'EOF'
#!/data/data/com.termux/files/usr/bin/sh
# start the camera recorder unless it's already running
PID=$HOME/panel/recorder.pid
# after a reboot the old number may belong to another process: only a live recorder.py counts
if [ -f $PID ] && tr "\0" " " 2>/dev/null < "/proc/$(cat $PID)/cmdline" | grep -q "recorder\.py"; then exit 0; fi
nohup python $HOME/panel/recorder.py > $HOME/.cache/drawer-server/recorder.crash 2>&1 &
echo $! > $PID
EOF

say "Starting the recorder (starts on boot too)"
phone_ssh "$HOST" "$STOP_RECORDER"
# the clock is read after the old recorder is gone, so only the new one can satisfy the poll
SINCE="$(phone_ssh "$HOST" 'date +%s')"
phone_ssh "$HOST" 'sh ~/.termux/boot/70-recorder.sh'

# Ready = a state file written after the restart, every recorded camera has a picture and its HD
# video has started arriving, and is watching or recording. Clips left over from before a crash are mended first, which can take a while.
# With "lenient", a camera that is offline doesn't hold the rest back (the last try, after a minute).
check_state() {
  phone_ssh "$HOST" "python - $SINCE ${1:-strict}" <<'PY'
import json, os, sys
since, lenient = int(sys.argv[1]), sys.argv[2] == "lenient"
home = os.path.expanduser("~")
cfg, data = home + "/.config/drawer-server/", home + "/.cache/drawer-server/"
def lines(path):
    try:
        return [l.strip() for l in open(path) if l.strip()]
    except OSError:
        return []
all_names = lines(cfg + "cameras")
chosen = ""
for l in lines(cfg + "recorder"):
    if l.startswith("cameras="):
        chosen = l[8:]
want = [n.strip() for n in chosen.split(",") if n.strip()] or all_names
try:
    st = json.load(open(data + "recorder.json"))
except (OSError, ValueError):
    sys.exit(1)
rows = {c.get("name"): c for c in st.get("cameras", [])}
ok = st.get("time", 0) >= since
for n in want:
    c = rows.get(n)
    print(n, c.get("state") if c else "waiting")
    if lenient and c and c.get("state") == "offline":
        continue
    if (not c or c.get("state") not in ("watching", "recording") or not c.get("last_frame")
            or not c.get("last_fragment")):
        ok = False
sys.exit(0 if ok else 1)
PY
}

STATE=""
READY=0
for _ in $(seq 20); do
  if STATE="$(check_state)"; then READY=1; break; fi
  READY=0
  sleep 3
done
if [ "$READY" != 1 ] && STATE="$(check_state lenient)"; then
  READY=1
  while IFS= read -r line; do
    case "$line" in *" offline") warn "${line% offline}: no video from the camera. Check it and step 11; the others are recording." ;; esac
  done <<<"$STATE"
fi
if [ "$READY" != 1 ]; then
  warn "The recorder is still starting. This can just be slow (it first mends clips left from a crash)."
  warn "Run step 12 again in a minute. If it keeps failing, this is what the phone says:"
  phone_ssh "$HOST" 'tail -5 ~/.cache/drawer-server/recorder.log 2>/dev/null; tail -5 ~/.cache/drawer-server/recorder.crash 2>/dev/null' || true
  exit 1
fi

say "Recorder running"
while IFS= read -r line; do echo "  $line"; done <<<"$STATE"
echo "  Clips are saved on the phone in ~/recordings (reach them with SFTP)."
if [ -n "${DISK_RECORDINGS_GB:-}" ]; then LIMIT="$DISK_RECORDINGS_GB GB"; else LIMIT="10% of the phone's storage"; fi
echo "  They may use up to $LIMIT (DISK_RECORDINGS_GB in .env). The oldest are deleted first."

say "Restarting the panel, which now shows the recordings"
bash "$REPO_ROOT/scripts/08-panel.sh" | tail -3
