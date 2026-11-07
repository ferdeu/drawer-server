#!/usr/bin/env bash
# One-time Spotify login, so the fridge tablet (http://<phone>:8080/fridge) shows what's playing.
# Needs a Spotify app made with a Premium account (docs/panel.md, "Fridge tablet") and, in .env:
#   SPOTIFY_CLIENT_ID=...  SPOTIFY_CLIENT_SECRET=...
#   bash scripts/spotify-login.sh
# Opens Spotify in your browser; log in with the account whose music the tablet shows and accept.
# The keys go straight to the phone (~/.config/drawer-server/spotify), never on screen. Run it again
# to switch accounts. Runs on your computer, with Python 3.
source "$(dirname "$0")/lib.sh"

load_phone_env
HOST="${PHONE_LAN_IP:?run scripts/04-network.sh first}"
[ -n "${SPOTIFY_CLIENT_ID:-}" ] && [ -n "${SPOTIFY_CLIENT_SECRET:-}" ] \
  || die "Put SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in .env (from your app at developer.spotify.com)"
PY="$(command -v python3 || command -v python || true)"
[ -n "$PY" ] || die "Python 3 is needed on this computer"

say "Connecting Spotify"
# .env is exported by lib.sh, so the keys reach Python through the environment, not the command line.
# The phone keeps the new file only if all three lines arrived.
"$PY" "$(localpath "$REPO_ROOT/scripts/spotify-login.py")" | phone_ssh "$HOST" \
  'umask 077; f=~/.config/drawer-server/spotify; mkdir -p ~/.config/drawer-server; cat > "$f.new"
   if [ "$(wc -l < "$f.new")" -eq 3 ]; then mv "$f.new" "$f"; else rm -f "$f.new"; exit 1; fi' \
  || die "Spotify wasn't connected (nothing was changed on the phone)"
echo "  Spotify connected. Play something and look at the tablet."
