#!/usr/bin/env bash
# Step 9 (optional) - Photo backup with Syncthing: each family phone sends its camera folder to
# the server over Wi-Fi. The server keeps every photo, even after it's deleted on the phone.
#
#   bash scripts/09-syncthing.sh Ana      pair Ana's phone (run once per person; safe to re-run)
#
# Photos land in the server's storage: Backups/<Name>/<folder>, visible with the Files app.
# Control page: http://<phone-ip>:8384  (user "admin", password SYNCTHING_GUI_PASSWORD in .env)
source "$(dirname "$0")/lib.sh"

load_phone_env
HOST="${PHONE_LAN_IP:?run scripts/04-network.sh first}"
WHO="${1:?say whose phone this is, e.g. bash scripts/09-syncthing.sh Ana}"
case "$WHO" in *[!A-Za-z0-9_-]*) die "Use a simple name (letters, numbers, - or _): $WHO" ;; esac

if [ -z "${SYNCTHING_GUI_PASSWORD:-}" ]; then
  SYNCTHING_GUI_PASSWORD="$(LC_ALL=C tr -dc 'a-km-zA-HJ-NP-Z2-9' </dev/urandom | head -c 16 || true)"
  printf '\n# Syncthing control page (scripts/09-syncthing.sh), user "admin"\nSYNCTHING_GUI_PASSWORD=%s\n' \
    "$SYNCTHING_GUI_PASSWORD" >> "$REPO_ROOT/.env"
  warn "New Syncthing password saved in .env (SYNCTHING_GUI_PASSWORD)"
fi

say "Installing and starting Syncthing on the server (starts on boot too)"
phone_ssh "$HOST" "set -e
command -v syncthing >/dev/null || pkg install -y syncthing >/dev/null 2>&1
command -v qrencode >/dev/null || pkg install -y libqrencode >/dev/null 2>&1
command -v jq >/dev/null || pkg install -y jq >/dev/null 2>&1
ls /sdcard >/dev/null 2>&1 || { echo 'Termux has no storage permission: run termux-setup-storage in Termux and tap Allow'; exit 1; }
mkdir -p /sdcard/Backups
echo '$SYNCTHING_GUI_PASSWORD' | syncthing generate --gui-user=admin --gui-password=- >/dev/null
cat > ~/.termux/boot/50-syncthing.sh <<'EOF'
#!/data/data/com.termux/files/usr/bin/sh
# start Syncthing unless it's already running
PID=\$HOME/.cache/syncthing.pid
if [ -f \$PID ] && kill -0 \"\$(cat \$PID)\" 2>/dev/null; then exit 0; fi
nohup syncthing serve --no-browser --no-upgrade > \$HOME/.cache/syncthing.out 2>&1 &
echo \$! > \$PID
EOF
chmod +x ~/.termux/boot/50-syncthing.sh
sh ~/.termux/boot/50-syncthing.sh
for i in \$(seq 1 20); do syncthing cli show system >/dev/null 2>&1 && break; sleep 2; done
ST='syncthing cli config'
\$ST gui raw-address set 0.0.0.0:8384
# home network + Tailscale only: no router port opening (UPnP), no public discovery or relays
\$ST options natenabled set false
\$ST options global-ann-enabled set false
\$ST options relays-enabled set false
# the stock 'Default Folder' (~/Sync) isn't used
\$ST folders default delete 2>/dev/null || true
syncthing cli show system | jq -r .myID > ~/.cache/syncthing.id"
SERVER_ID="$(phone_ssh "$HOST" 'cat ~/.cache/syncthing.id' | tr -d '\r')"

DEV="$(phone_ssh "$HOST" "syncthing cli config dump-json | jq -r '.devices[] | select(.name==\"$WHO\") | .deviceID'" | tr -d '\r')"
if [ -z "$DEV" ]; then
  say "Pair $WHO's phone"
  phone_ssh "$HOST" "qrencode -t ANSIUTF8 '$SERVER_ID'"
  echo "  Server ID: $SERVER_ID"
  cat <<EOF
  On $WHO's phone:
    1. Install "Syncthing-Fork" (Play Store or F-Droid), open it and allow what it asks.
    2. Devices tab > + > scan the QR code above. Name: Server. Save.
EOF
  # a phone that added the server but isn't accepted yet shows up as "pending"
  pending() { phone_ssh "$HOST" "syncthing cli show pending devices | jq -r 'keys[0] // empty'" | tr -d '\r'; }
  has_pending() { [ -n "$(pending)" ]; }
  wait_for "Add the server on $WHO's phone (scan the QR code)" 900 has_pending
  DEV="$(pending)"
  # device IDs are A-Z, 2-7 and dashes; anything else didn't come from a real Syncthing
  [[ "$DEV" =~ ^[A-Z0-9-]{50,70}$ ]] || die "Unexpected device ID: $DEV"
  n="$(phone_ssh "$HOST" "syncthing cli show pending devices | jq 'length'" | tr -d '
')"
  [ "$n" = "1" ] || die "$n phones are asking to connect. Check them at http://$HOST:8384 and accept $WHO's by hand."
  echo "  $WHO's phone asked to connect: $DEV"
  echo "  (it should match the ID in Syncthing-Fork > Settings > Show device ID on $WHO's phone)"
  phone_ssh "$HOST" "syncthing cli config devices add --device-id '$DEV' --name '$WHO'"
  echo "  paired: $WHO = $DEV"
fi

say "Share the camera folder"
cat <<EOF
  On $WHO's phone, in Syncthing-Fork:
    Folders tab > + > Folder label: Camera, Directory: DCIM/Camera,
    Folder type: Send Only, share with: Server. Save.
  (More folders, like WhatsApp images or Screenshots, can be shared the same way, anytime.)
EOF
pending_folder() { phone_ssh "$HOST" "syncthing cli show pending folders | jq -r '[to_entries[] | select(.value.offeredBy[\"$DEV\"]) | .key + \"|\" + .value.offeredBy[\"$DEV\"].label][0] // empty'" | tr -d '\r'; }
has_folder() { [ -n "$(pending_folder)" ] || phone_ssh "$HOST" "syncthing cli config dump-json | jq -e 'any(.folders[]; any(.devices[]; .deviceID==\"$DEV\"))'" >/dev/null 2>&1; }
wait_for "Share the Camera folder with Server on $WHO's phone" 900 has_folder
# accept every folder this phone offers: receive-only, and phone deletions are ignored
while F="$(pending_folder)"; [ -n "$F" ]; do
  ID="${F%%|*}"; LABEL="${F#*|}"; LABEL="${LABEL:-$ID}"
  # both come from the other phone: never let them reach the shell or the path as-is
  case "$ID" in ''|*[!A-Za-z0-9_.-]*) die "Folder ID with unusual characters ($ID). Accept it by hand at http://$HOST:8384" ;; esac
  LABEL="$(printf '%s' "$LABEL" | tr -c 'A-Za-z0-9 _.-' '_' | sed 's/^[. ]*//')"; LABEL="${LABEL:-folder}"
  phone_ssh "$HOST" "set -e
ST='syncthing cli config folders'
\$ST add --id '$ID' --label '$WHO - $LABEL' --path '/sdcard/Backups/$WHO/$LABEL' --type receiveonly
\$ST '$ID' devices add --device-id '$DEV'
\$ST '$ID' ignore-delete set true"
  echo "  backing up: $LABEL -> Backups/$WHO/$LABEL"
done

say "Syncthing ready"
echo "  Photos go to the server's storage: Backups/$WHO (deleting on the phone doesn't delete them here)"
echo "  Control page:  http://$HOST:8384   user: admin   password: SYNCTHING_GUI_PASSWORD in .env"
[ -n "${PHONE_TS_IP:-}" ] && echo "  From anywhere: http://$PHONE_TS_IP:8384  (with Tailscale on your device)"
