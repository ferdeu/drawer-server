#!/usr/bin/env bash
# Step 8 - Status panel: a web page on the phone with battery, temperature, memory, disk,
# which services are alive, and a 24-hour battery chart.
#
#   bash scripts/08-panel.sh       then open http://<phone-ip>:8080
#   PANEL_LANG=es in .env shows it in Spanish; PANEL_TITLE="Our house" names it
source "$(dirname "$0")/lib.sh"

load_phone_env
HOST="${PHONE_LAN_IP:?run scripts/04-network.sh first}"
PANEL_PORT="${PANEL_PORT:-8080}"
PANEL_LANG="${PANEL_LANG:-en}"
# the smart plug (step 10) keeps the battery between these, in %
CHARGE_LOW="${CHARGE_LOW:-30}"
CHARGE_HIGH="${CHARGE_HIGH:-80}"
# too low and the phone dies before the plug turns back on
[[ "$CHARGE_LOW" =~ ^[0-9]+$ && "$CHARGE_HIGH" =~ ^[0-9]+$ ]] && [ "$CHARGE_LOW" -ge 10 ] &&
  [ $((CHARGE_HIGH - CHARGE_LOW)) -ge 10 ] && [ "$CHARGE_HIGH" -le 100 ] ||
  die "CHARGE_LOW and CHARGE_HIGH: whole numbers, low at least 10, high at most 100, at least 10 apart (got $CHARGE_LOW and $CHARGE_HIGH)"

say "Copying the panel to the phone"
phone_ssh "$HOST" 'mkdir -p ~/panel'
scp -q -i "$KEY" -P 8022 -o StrictHostKeyChecking=accept-new \
  "$REPO_ROOT"/termux/panel/*.py "$REPO_ROOT"/termux/panel/*.png "$TERMUX_USER@$HOST:panel/"

# Optional home cards, configured from .env:
#   PANEL_STARLINK=yes                      read the Starlink dish (192.168.100.1)
#   PANEL_PRINTER_IP=192.168.1.30           Epson ink levels
#   PANEL_PEOPLE="Ana=192.168.1.20,Bo=192.168.1.21"   who's home (give their phones fixed IPs)
#   PANEL_ROUTER=tplink                     every device on the Wi-Fi, from a TP-Link router's web API
#                                           (uses ROUTER_URL and ROUTER_PASSWORD)
#   PANEL_DEVICE_NAMES="F4-70-18-00-00-01=Doorbell,..."   names for devices that don't report one
#                                           (names given in the panel itself win over these)
#   PANEL_DEVICE_HIDE="F4-70-18-00-00-03,..."   devices to leave out, e.g. a camera's Wi-Fi turned off on purpose
#   PANEL_SPEEDTEST=4                       speed tests a day, 0-6 (0: only the "Test again" button);
#                                           each one moves ~100 MB
#   PANEL_RECORDINGS=no                     hide the motion recordings section (step 12)
#   PANEL_TABS="Home=self,School=http://192.168.1.200:8765/|http://school-pc:8765/"   tabs on top to
#                                           other pages: the home address, then the Tailscale one
#   PANEL_ADDABLE=no                        hide the "Can be added: …" line at the bottom
#   DISK_RECORDINGS_GB, DISK_BACKUP_GB, DISK_KEEP_FREE_GB, DISK_BACKUP_PAUSE   disk split (see .env.example)
# The fridge tablet page (http://<phone-ip>:8080/fridge):
#   FRIDGE_CAL_1="Home|#5ee1ff|https://calendar.google.com/calendar/ical/.../basic.ics"   up to
#                                           FRIDGE_CAL_12: name, color and the calendar's secret iCal address
#   FRIDGE_DIM=00:00-07:00                  the page dims itself between these hours
#   FRIDGE_BACK_S=120                       back to the first screen after this many seconds untouched
#   (Spotify: bash scripts/spotify-login.sh, once; the tablet plays through https://<phone-ip>:8443/fridge,
#    with a certificate this script makes in local/https/)
PEOPLE_LINES="$(tr ',' '\n' <<<"${PANEL_PEOPLE:-}" | sed -n 's/^ *\([^=]*[^= ]\) *= *\([0-9.]*\) *$/\1 \2/p')"

[[ "${PANEL_PRINTER_IP:-}" =~ ^([0-9.]+)?$ ]] || die "PANEL_PRINTER_IP should be an address like 192.168.1.40"
[[ "${PANEL_SPEEDTEST:-}" =~ ^[0-6]?$ ]] || die "PANEL_SPEEDTEST should be how many speed tests a day, 0 to 6"
[[ "${PANEL_DEVICE_HIDE:-}" =~ ^([0-9A-Fa-f:-]{17}( *, *[0-9A-Fa-f:-]{17})*)?$ ]] ||
  die "PANEL_DEVICE_HIDE should be MACs separated by commas, like F4-70-18-00-00-03,F4-70-18-00-00-04"

DISK_NUM='^([0-9]+(\.[0-9]+)?)?$'
for v in DISK_RECORDINGS_GB DISK_BACKUP_GB DISK_KEEP_FREE_GB; do
  [[ "${!v:-}" =~ $DISK_NUM ]] || die "$v should be a number of GB like 20 or 7.5 (got ${!v})"
done
[[ "${DISK_BACKUP_PAUSE:-}" =~ ^(yes|no)?$ ]] || die "DISK_BACKUP_PAUSE should be yes or no"
[[ "${PANEL_RECORDINGS:-}" =~ ^(yes|no)?$ ]] || die "PANEL_RECORDINGS should be yes or no"
[[ "${PANEL_ADDABLE:-}" =~ ^(yes|no)?$ ]] || die "PANEL_ADDABLE should be yes or no"

# same rules as tabs() in panel.py: two or more tabs, exactly one self, only http(s) addresses
TAB_LINES="$(tr ',' '\n' <<<"${PANEL_TABS:-}" | sed 's/^ *//; s/ *$//' | grep . || true)"
url="https?://[^ |\"'<>]+"
if [ -n "$TAB_LINES" ] && { grep -qvE "^[^=]+= *(self|$url( *\| *$url)?)$" <<<"$TAB_LINES" ||
    [ "$(grep -cE '^[^=]+= *self$' <<<"$TAB_LINES")" -ne 1 ] || [ "$(wc -l <<<"$TAB_LINES")" -lt 2 ]; }; then
  die "PANEL_TABS: Label=self for this panel, and Label=home-address|away-address for each other page, comma separated"
fi

[[ "${FRIDGE_DIM:-}" =~ ^([0-9]{2}:[0-9]{2}-[0-9]{2}:[0-9]{2})?$ ]] || die "FRIDGE_DIM should be two hours like 00:00-07:00"
[[ "${FRIDGE_BACK_S:-}" =~ ^[0-9]*$ ]] || die "FRIDGE_BACK_S should be a number of seconds, 30 to 3600"
# without quotes, the | in a calendar line is read as a pipe and the line (and the next one) silently vanish
UNQUOTED="$(grep -oE '^FRIDGE_CAL_[0-9]+=[^"'\''[:space:]]' "$REPO_ROOT/.env" 2>/dev/null | cut -d= -f1 | tr '\n' ' ' || true)"
[ -z "$UNQUOTED" ] || die "Put the whole line in double quotes in .env: $UNQUOTED(like FRIDGE_CAL_1=\"Home|#5ee1ff|https://…\")"
# the calendar addresses are secrets: a bad one is named, never printed
CAL_LINE='^[^|]+\|#[0-9a-fA-F]{6}\|https://[^ |]+$'
CAL_LINES=""
for n in 1 2 3 4 5 6 7 8 9 10 11 12; do
  v="FRIDGE_CAL_$n"
  [ -n "${!v:-}" ] || continue
  [[ "${!v}" =~ $CAL_LINE ]] || die "$v should be Name|#rrggbb|https://… (the calendar's secret iCal address)"
  CAL_LINES+="${!v}"$'\n'
done

# the router password, names and title go over stdin, never inside a command line
phone_ssh "$HOST" 'mkdir -p ~/.config/drawer-server; rm -f ~/.config/drawer-server/router ~/.config/drawer-server/device-names ~/.config/drawer-server/device-hide ~/.config/drawer-server/title ~/.config/drawer-server/people ~/.config/drawer-server/tabs ~/.config/drawer-server/calendars'
if [ -n "$CAL_LINES" ]; then
  printf '%s' "$CAL_LINES" | phone_ssh "$HOST" 'umask 077; cat > ~/.config/drawer-server/calendars'
  phone_ssh "$HOST" "python -c 'import recurring_ical_events' 2>/dev/null || pip install -q recurring-ical-events"
fi
# the fridge page re-reads these on every poll
printf 'dim=%s\nback_s=%s\n' "${FRIDGE_DIM:-}" "${FRIDGE_BACK_S:-}" | phone_ssh "$HOST" 'cat > ~/.config/drawer-server/fridge'
if [ -n "${PANEL_TITLE:-}" ]; then
  printf '%s\n' "$PANEL_TITLE" | phone_ssh "$HOST" 'cat > ~/.config/drawer-server/title'
fi
if [ -n "$TAB_LINES" ]; then
  printf '%s\n' "$TAB_LINES" | phone_ssh "$HOST" 'cat > ~/.config/drawer-server/tabs'
fi
if [ -n "$PEOPLE_LINES" ]; then
  printf '%s\n' "$PEOPLE_LINES" | phone_ssh "$HOST" 'cat > ~/.config/drawer-server/people'
fi
# disk split and the recordings section: the panel and the recorder re-read these every 30 s
printf 'recordings_gb=%s
backup_gb=%s
backup_pause=%s
keep_free_gb=%s
'   "${DISK_RECORDINGS_GB:-}" "${DISK_BACKUP_GB:-}" "${DISK_BACKUP_PAUSE:-}" "${DISK_KEEP_FREE_GB:-}" |
  phone_ssh "$HOST" 'cat > ~/.config/drawer-server/disk'
printf 'show=%s
' "${PANEL_RECORDINGS:-}" | phone_ssh "$HOST" 'cat > ~/.config/drawer-server/panel-recordings'

# The fridge page's https door (Spotify only plays inside https pages, and the screen only stays on there).
# A home certificate made once (local/https/ca.pem, 10 years), which the tablet trusts once, signs the
# phone's own certificate (397 days: Android browsers refuse longer ones), remade here when it nears its
# end or the phone's IP changed. The home certificate's key never leaves this computer, and it can only
# vouch for home addresses (192.168..., 10..., 172.16-31...), never for a website.
# Optional: if openssl fails, the panel still starts, without the https door.
HTTPS_URL=""
make_https() {
  local tls="$REPO_ROOT/local/https"
  mkdir -p "$tls" || return 1
  # relative names inside the folder: Git Bash's openssl doesn't understand /c/... paths
  cd "$tls" || return 1
  if [ ! -f ca.pem ] || ! openssl x509 -in ca.pem -noout -text 2>/dev/null | grep -q "Name Constraints"; then
    say "Making the home certificate for the fridge tablet"
    rm -f ca.pem ca.key ca.srl server.pem
    (umask 077 && openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj "/O=Drawer server home" \
      -addext "basicConstraints=critical,CA:TRUE" -addext "keyUsage=critical,keyCertSign,cRLSign" \
      -addext "nameConstraints=critical,permitted;IP:192.168.0.0/255.255.0.0,permitted;IP:10.0.0.0/255.0.0.0,permitted;IP:172.16.0.0/255.240.0.0,permitted;DNS:home.invalid" \
      -keyout ca.key -out ca.pem 2>/dev/null) || return 1
  fi
  if ! { [ -f server.pem ] && openssl x509 -in server.pem -noout -checkend 2592000 >/dev/null &&
         openssl x509 -in server.pem -noout -text | grep -qE "IP Address:${HOST//./\.}(,|$| )"; }; then
    say "Making the phone's https certificate"
    # no CN: a name there would be checked against "DNS:home.invalid" by some browsers
    (umask 077 &&
      printf 'subjectAltName=IP:%s\nbasicConstraints=CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n' \
        "$HOST" > server.ext &&
      openssl req -newkey rsa:2048 -nodes -subj "/O=Drawer server" -keyout server.key -out server.csr 2>/dev/null &&
      openssl x509 -req -in server.csr -CA ca.pem -CAkey ca.key -CAcreateserial -days 397 -sha256 \
        -extfile server.ext -out server.pem 2>/dev/null &&
      openssl verify -CAfile ca.pem server.pem >/dev/null) || return 1
  fi
  phone_ssh "$HOST" 'umask 077; cat > ~/.config/drawer-server/https.key' < server.key &&
    phone_ssh "$HOST" 'cat > ~/.config/drawer-server/https.pem' < server.pem &&
    phone_ssh "$HOST" 'cat > ~/.config/drawer-server/https-ca.pem' < ca.pem
}
if ! command -v openssl >/dev/null; then
  warn "openssl not found: no https page for the fridge tablet (it can show Spotify, not play it)"
elif (make_https); then
  HTTPS_URL="https://$HOST:8443/fridge"
else
  warn "openssl could not make the fridge tablet's certificates: no https page (it can show Spotify, not play it)"
fi
if [ "${PANEL_ROUTER:-}" = tplink ]; then
  say "Router card: installing the TP-Link client (first time: ~2 minutes)"
  [ -n "${ROUTER_URL:-}" ] && [ -n "${ROUTER_PASSWORD:-}" ] || die "PANEL_ROUTER=tplink needs ROUTER_URL and ROUTER_PASSWORD in .env"
  printf '%s\n%s\n' "$ROUTER_URL" "$ROUTER_PASSWORD" | phone_ssh "$HOST" 'umask 077; cat > ~/.config/drawer-server/router'
  phone_ssh "$HOST" "python -c 'import tplinkrouterc6u' 2>/dev/null || pip install -q tplinkrouterc6u"
  if [ -n "${PANEL_DEVICE_NAMES:-}" ]; then
    tr ',' '\n' <<<"$PANEL_DEVICE_NAMES" | sed -n 's/^ *\([0-9A-Fa-f:-]\{17\}\) *= *\(.*[^ ]\) *$/\1 \2/p' |
      phone_ssh "$HOST" 'cat > ~/.config/drawer-server/device-names'
  fi
  if [ -n "${PANEL_DEVICE_HIDE:-}" ]; then
    tr ',' '\n' <<<"$PANEL_DEVICE_HIDE" | grep -oE '[0-9A-Fa-f:-]{17}' |
      phone_ssh "$HOST" 'cat > ~/.config/drawer-server/device-hide'
  fi
fi

say "Installing tools and starting the panel (starts on boot too)"
phone_ssh "$HOST" "set -e
command -v python >/dev/null || pkg install -y python >/dev/null 2>&1
command -v grpcurl >/dev/null || pkg install -y grpcurl >/dev/null 2>&1
command -v snmpget >/dev/null || pkg install -y net-snmp >/dev/null 2>&1
C=~/.config/drawer-server
rm -f \$C/starlink \$C/printer \$C/speedtest \$C/addable-off
[ '${PANEL_STARLINK:-}' = yes ] && touch \$C/starlink
[ '${PANEL_ADDABLE:-}' = no ] && touch \$C/addable-off
[ -n '${PANEL_PRINTER_IP:-}' ] && echo '${PANEL_PRINTER_IP:-}' > \$C/printer
if [ -n '${PANEL_SPEEDTEST:-}' ]; then
  command -v speedtest-go >/dev/null || pkg install -y speedtest-go >/dev/null 2>&1
  command -v speedtest-go >/dev/null || echo 'WARNING: could not install speedtest-go; no speed test card'
  echo '${PANEL_SPEEDTEST:-}' > \$C/speedtest
fi
true
cat > ~/.termux/boot/40-panel.sh <<'EOF'
#!/data/data/com.termux/files/usr/bin/sh
# start the status panel unless it's already running
PID=\$HOME/panel/panel.pid
if [ -f \$PID ] && kill -0 \"\$(cat \$PID)\" 2>/dev/null; then exit 0; fi
PANEL_PORT=$PANEL_PORT PANEL_LANG=$PANEL_LANG CHARGE_LOW=$CHARGE_LOW CHARGE_HIGH=$CHARGE_HIGH nohup python \$HOME/panel/panel.py > \$HOME/panel/panel.log 2>&1 &
echo \$! > \$PID
EOF
chmod +x ~/.termux/boot/40-panel.sh
# restart so a new panel.py takes effect
if [ -f ~/panel/panel.pid ]; then
  OLD=\$(cat ~/panel/panel.pid)
  kill \"\$OLD\" 2>/dev/null || true
  # wait until it lets go of the port (it stops its camera ffmpegs first), at most 10 s
  for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do kill -0 \"\$OLD\" 2>/dev/null || break; sleep 0.5; done
fi
rm -f ~/panel/panel.pid
sh ~/.termux/boot/40-panel.sh
sleep 4
curl -sf http://127.0.0.1:$PANEL_PORT/api/status >/dev/null || { cat ~/panel/panel.log; exit 1; }"

say "Panel ready"
echo "  At home:        http://$HOST:$PANEL_PORT"
[ -n "${PHONE_TS_IP:-}" ] && echo "  From anywhere:  http://$PHONE_TS_IP:$PANEL_PORT  (with Tailscale on your device)"
if [ -n "$HTTPS_URL" ]; then
  echo "  Fridge tablet:  $HTTPS_URL  (once on the tablet: http://$HOST:$PANEL_PORT/ca.crt, see docs/panel.md)"
else
  echo "  Fridge tablet:  http://$HOST:$PANEL_PORT/fridge"
fi
