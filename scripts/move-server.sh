#!/usr/bin/env bash
# Move the server to a new phone without losing anything: same photos, game worlds, settings,
# smart plug, Syncthing identity (family phones reconnect by themselves), same home IP and
# Tailscale IP. The step-by-step guide for humans is docs/new-phone.md.
#
#   1. bash scripts/move-server.sh save-old   BEFORE step 3 on the new phone: remembers the old one
#   2. Set up the new phone: steps 0-8 and 11 (skip 9 and 10, their state is copied below)
#   3. bash scripts/move-server.sh copy       copies photos while the old server keeps working
#                                             (long: ~20 GB took a night on 2.4 GHz Wi-Fi; re-runnable)
#   4. bash scripts/move-server.sh switch     stops the old server, copies the rest, starts the new
#                                             one; then prints what to change by hand (router, Tailscale)
#   5. bash scripts/move-server.sh finish     after those changes: checks the new phone answers on the
#                                             old addresses and points this computer at them
#
# The old phone keeps SSH and all its files; only its services stop, and they don't come back on
# reboot (its ~/.termux/boot scripts move to ~/.termux/boot.moved).
source "$(dirname "$0")/lib.sh"

OLD_ENV="$REPO_ROOT/local/old-phone.env"
PHONE_ENV="$REPO_ROOT/local/phone.env"

case "${1:-}" in
  save-old)
    [ -f "$PHONE_ENV" ] || die "No local/phone.env: nothing to save."
    [ -f "$OLD_ENV" ] && die "local/old-phone.env already exists. Delete it first if you really mean it."
    cp "$PHONE_ENV" "$OLD_ENV"
    say "Saved the old server's addresses in local/old-phone.env. Now set up the new phone (step 0 onwards)."
    exit 0 ;;
  copy|switch|finish) ;;
  *) die "Usage: bash scripts/move-server.sh save-old | copy | switch | finish   (guide: docs/new-phone.md)" ;;
esac

[ -f "$OLD_ENV" ] || die "Run 'bash scripts/move-server.sh save-old' first (before step 3 on the new phone)."
OLD_USER="$(sed -n 's/^TERMUX_USER=//p' "$OLD_ENV")"
OLD_IP="$(sed -n 's/^PHONE_LAN_IP=//p' "$OLD_ENV")"
OLD_TS_IP="$(sed -n 's/^PHONE_TS_IP=//p' "$OLD_ENV")"
load_phone_env
NEW_IP="${PHONE_LAN_IP:?run scripts/04-network.sh on the new phone first}"

set_phone_env() {  # set_phone_env NAME value
  { grep -v "^$1=" "$PHONE_ENV"; echo "$1=$2"; } > "$PHONE_ENV.tmp"
  mv "$PHONE_ENV.tmp" "$PHONE_ENV"
}

if [ "$1" = finish ]; then
  # the new phone's SSH fingerprint, learned while setting it up: whoever shows it at an
  # address is the new phone
  NEW_KEY="$(ssh-keygen -F "[$NEW_IP]:8022" 2>/dev/null | awk '$2 == "ssh-ed25519" {print $3; exit}')"
  [ -n "$NEW_KEY" ] || die "This computer doesn't know the new phone's SSH fingerprint at $NEW_IP. Run step 4 on it again, then this."
  is_new_phone() { [ "$(ssh-keyscan -p 8022 -T 5 -t ed25519 "$1" 2>/dev/null | awk '!/^#/ {print $3; exit}')" = "$NEW_KEY" ]; }

  say "Is the new phone at $OLD_IP?"
  is_new_phone "$OLD_IP" || die "Not yet. Check the router reservation, then turn the new phone's Wi-Fi off and on by hand (docs/new-phone.md, part 5)."
  ssh-keygen -R "[$OLD_IP]:8022" >/dev/null 2>&1 || true   # the old phone's fingerprint for that address
  set_phone_env PHONE_LAN_IP "$OLD_IP"
  phone_ssh "$OLD_IP" 'echo "  yes: $(getprop ro.product.model)"'

  if [ -n "$OLD_TS_IP" ]; then
    say "Is the new phone at Tailscale $OLD_TS_IP?"
    if is_new_phone "$OLD_TS_IP"; then
      ssh-keygen -R "[$OLD_TS_IP]:8022" >/dev/null 2>&1 || true
      set_phone_env PHONE_TS_IP "$OLD_TS_IP"
      phone_ssh "$OLD_TS_IP" 'echo "  yes: $(getprop ro.product.model)"'
    else
      warn "Not yet (or this computer isn't on Tailscale). Do part 6 of docs/new-phone.md, then run finish again."
    fi
  fi
  say "Done: this computer now uses the new phone. Last check: bash .claude/skills/check-server/check.sh"
  exit 0
fi

[ "$OLD_IP" != "$NEW_IP" ] || die "Old and new server have the same IP ($OLD_IP). Already switched? Then run: bash scripts/move-server.sh finish"

ssh_opts=(-i "$KEY" -p 8022 -o StrictHostKeyChecking=accept-new -o ConnectTimeout=8 -o ServerAliveInterval=30)
old_ssh() { ssh "${ssh_opts[@]}" "$OLD_USER@$OLD_IP" "$@"; }
new_ssh() { ssh "${ssh_opts[@]}" "$TERMUX_USER@$NEW_IP" "$@"; }

old_ssh true || die "Can't reach the old server at $OLD_IP over SSH."
new_ssh true || die "Can't reach the new server at $NEW_IP over SSH."

# "size path" of every photo backup, byte-sorted the same way on both ends
LIST='cd /sdcard && mkdir -p Backups && find Backups -type f -printf "%s %p\n" | LC_ALL=C sort'
TODO="$REPO_ROOT/local/move-server.todo"
# photos the new phone lacks, or has at another size (cut mid-copy)
missing_photos() {
  old_ssh "$LIST" > "$TODO.old" || die "Couldn't list the old phone's photos (connection cut?). Run it again."
  new_ssh "$LIST" > "$TODO.new" || die "Couldn't list the new phone's photos (connection cut?). Run it again."
  LC_ALL=C comm -23 "$TODO.old" "$TODO.new" | cut -d' ' -f2- > "$TODO"
}
copy_photos() {
  missing_photos
  echo "  files to copy: $(wc -l < "$TODO" | tr -d ' ')"
  [ -s "$TODO" ] || return 0
  old_ssh 'cd /sdcard && tar -cf - -T -' < "$TODO" | new_ssh 'tar -C /sdcard -xf -'
  missing_photos
  [ ! -s "$TODO" ] || die "$(wc -l < "$TODO" | tr -d ' ') photos didn't copy (connection cut?). Run the same command again: it continues."
  new_ssh 'du -sh /sdcard/Backups' | sed 's/^/  all there: /'
}

if [ "$1" = copy ]; then
  say "Full backup of the old server's Termux home to this computer (local/old-server-home.tar)"
  # the services keep writing while tar reads; tar's exit code 1 means "a file changed", fine for this
  old_ssh 'tar --warning=no-file-changed -C ~ --exclude=.cache -cf - . || [ $? -eq 1 ]' > "$REPO_ROOT/local/old-server-home.tar"
  ls -lh "$REPO_ROOT/local/old-server-home.tar" | awk '{print "  " $5}'

  say "Copying the photo backups (/sdcard/Backups) old -> new, through this computer"
  copy_photos
  say "Done. When nobody is playing: bash scripts/move-server.sh switch"
  exit 0
fi

# --- switch ---
# [s]yncthing etc.: the pattern must not match this ssh command's own shell
STOP='pkill -f [s]yncthing; pkill -f [l]uantiserver; pkill -f [p]anel.py; pkill -f [g]o2rtc; pkill -f [r]ecorder.py; pkill -f [-]user_agent\ drawer-recorder; pkill -f [n]extdns-link-loop; pkill -f [t]ailscale-watch'
# Luanti saves the world and Syncthing closes its database on the way out: wait for both
STOPPED='for i in $(seq 1 30); do pgrep -f "[s]yncthing|[l]uantiserver" >/dev/null || exit 0; sleep 1; done; exit 1'
say "Stopping the services on both phones"
old_ssh "$STOP; [ -d ~/.termux/boot ] && mkdir -p ~/.termux/boot.moved &&
  find ~/.termux/boot -type f ! -name '10-sshd.sh' -exec mv {} ~/.termux/boot.moved/ \\;; true"
new_ssh "$STOP; true"
old_ssh "$STOPPED" || die "The old phone's game or Syncthing didn't stop in 30 s. Run switch again."
new_ssh "$STOPPED" || die "The new phone's game or Syncthing didn't stop in 30 s. Run switch again."

say "Copying photos that arrived since 'copy'"
copy_photos

say "Copying game worlds, Syncthing identity, settings and the panel's history"
new_ssh 'rm -rf ~/luanti/worlds ~/.local/state/syncthing'
old_ssh 'cd ~ && tar -cf - --exclude=syncthing.lock --exclude=".syncthing.tmp.*" \
  $(ls -d luanti/worlds luanti/games luanti/*.version .local/state/syncthing .config/drawer-server \
    .cache/drawer-server/devices.json .cache/drawer-server/speed.csv 2>/dev/null)' |
  new_ssh 'tar -C ~ -xf -'
# boot scripts the new phone doesn't have yet (Syncthing from step 9)
old_ssh 'tar -C ~/.termux/boot.moved -cf - .' |
  new_ssh 'mkdir -p ~/.termux/boot.new && tar -C ~/.termux/boot.new -xf - &&
    for f in ~/.termux/boot.new/*; do [ -e ~/.termux/boot/"$(basename "$f")" ] || mv "$f" ~/.termux/boot/; done;
    rm -rf ~/.termux/boot.new; chmod +x ~/.termux/boot/*'

say "Installing what the copied services need on the new phone"
new_ssh '[ -f ~/.termux/boot/50-syncthing.sh ] && ! command -v syncthing >/dev/null && pkg install -y syncthing jq >/dev/null 2>&1
  [ -f ~/.config/drawer-server/plug ] && ! python -c "import tinytuya" 2>/dev/null &&
    { pkg install -y python-cryptography >/dev/null 2>&1 && pip install -q tinytuya; }; true'

say "Starting everything on the new phone"
new_ssh 'for f in ~/.termux/boot/*; do sh "$f" >/dev/null 2>&1; done; sleep 5;
  for p in sshd syncthing luantiserver panel.py go2rtc recorder.py nextdns-link-loop tailscale-watch; do
    if pgrep -f "[${p:0:1}]${p:1}" >/dev/null; then echo "  running: $p"; else echo "  not running: $p"; fi; done'

NEW_MAC="${PHONE_MAC:-(run step 4 to see it)}"
say "The new phone is the server now. What's left is by hand: docs/new-phone.md, parts 5 to 8"
cat <<EOF
  5. Same home address ($OLD_IP):
     a. Old phone: turn its Wi-Fi off (or switch the phone off).
     b. New phone: Settings > Wi-Fi > your network > Privacy (or "MAC type") > "Use device MAC".
     c. Router page, Address Reservation: edit the old phone's line for $OLD_IP and put the new
        phone's MAC: $NEW_MAC   (if you changed it in b, run step 4 again to see the new one).
     d. New phone, BY HAND: Wi-Fi off, wait 5 seconds, Wi-Fi on. Never do this over SSH.
        Still not on $OLD_IP after a minute? Restart the router and do d again.
  6. Same Tailscale address${OLD_TS_IP:+ ($OLD_TS_IP)}: login.tailscale.com/admin/machines >
     old phone "..." > Remove; new phone "..." > Edit machine IPv4 > ${OLD_TS_IP:-the old address};
     new phone "..." > Disable key expiry.
  7. Smart plug: plug the NEW phone's charger into it (the old phone's charger out).
  8. bash scripts/move-server.sh finish
EOF
