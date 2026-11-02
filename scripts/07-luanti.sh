#!/usr/bin/env bash
# Step 7 (optional) - A block-building game server for the kids: Luanti + Mineclonia.
#
# Luanti (formerly Minetest) is a free, open-source voxel game engine; Mineclonia is a game for
# it that plays like Minecraft. Clients are free on Android (Play Store / F-Droid) and Windows,
# no accounts or purchases. On the test phone the server used ~270 MB of RAM
# (a Minecraft Java server used 1.3 GB).
#
# Luanti isn't packaged for Termux, so it runs inside a small Debian (proot-distro):
# Android > Termux > Debian > luantiserver.
#
#   Put LUANTI_ADMIN=<player name> in .env, then:  bash scripts/07-luanti.sh   (safe to re-run)
#   That player gets all privileges. Without it the step skips itself.
#   LUANTI_CREATIVE=true: unlimited blocks, flying, no dying, no monsters (animals stay). Players
#     who already joined need "/grant <name> fly, fast" from the admin to fly.
#   LUANTI_GAME=minetest: Minetest Game (simpler, no monsters or animals) instead of Mineclonia.
#   LUANTI_WORLD=<folder> picks the world in ~/luanti/worlds (default casa; a new name starts a new one).
#   Re-run the step after changing any of these; other worlds stay on the phone.
source "$(dirname "$0")/lib.sh"

load_phone_env
HOST="${PHONE_LAN_IP:?run scripts/04-network.sh first}"
if [ -z "${LUANTI_ADMIN:-}" ]; then
  warn "Skipped: no LUANTI_ADMIN in .env (the player name that will be the game's admin). Optional step."
  exit 0
fi
ADMIN="$LUANTI_ADMIN"
case "$ADMIN" in *[!A-Za-z0-9_-]*) die "LUANTI_ADMIN: use letters, numbers, - or _ (that's what Luanti allows): $ADMIN" ;; esac
[ "${#ADMIN}" -le 20 ] || die "LUANTI_ADMIN: Luanti names are 20 characters at most: $ADMIN"
PORT="${LUANTI_PORT:-30000}"
case "${LUANTI_CREATIVE:-false}" in
  true)  CREATIVE=true;  DAMAGE=false; PEACEFUL=true;  PRIVS="interact, shout, home, fly, fast" ;;
  false) CREATIVE=false; DAMAGE=true;  PEACEFUL=false; PRIVS="interact, shout, home" ;;
  *) die "LUANTI_CREATIVE: use true or false: $LUANTI_CREATIVE" ;;
esac
GAME="${LUANTI_GAME:-mineclonia}"
case "$GAME" in mineclonia|minetest) ;; *) die "LUANTI_GAME: use mineclonia or minetest: $GAME" ;; esac
WORLD="${LUANTI_WORLD:-casa}"
case "$WORLD" in ''|*[!A-Za-z0-9_-]*) die "LUANTI_WORLD: use letters, numbers, - or _: $WORLD" ;; esac

MC_URL="" MC_VER=""
if [ "$GAME" = mineclonia ]; then
  say "Finding the latest Mineclonia release"
  # newest release is first; plain grep so it works without Python
  JSON="$(curl -sSf https://content.luanti.org/api/packages/ryvnf/mineclonia/releases/ || echo '{}')"
  MC_URL="$(grep -o '"url": *"[^"]*"' <<<"$JSON" | head -1 | sed 's/.*"\(http[^"]*\)"/\1/' || true)"
  MC_VER="$(grep -o '"title": *"[^"]*"' <<<"$JSON" | head -1 | sed 's/.*: *"\([^"]*\)"/\1/' || true)"
  if [ -n "$MC_URL" ] && [ -n "$MC_VER" ]; then
    echo "  Mineclonia $MC_VER"
  else
    # content.luanti.org down: fine if the phone already has a copy
    warn "Couldn't read the Mineclonia release list from content.luanti.org; keeping the installed one"
    MC_VER=""
  fi
fi

say "Installing Debian + Luanti server on the phone (first time: a few minutes)"
phone_ssh "$HOST" "set -e; [ -n \"${DEBUG:-}\" ] && set -x
pkg install -y proot-distro >/dev/null 2>&1
proot-distro login debian -- true 2>/dev/null || proot-distro install debian >/dev/null 2>&1
proot-distro login debian -- sh -c 'command -v /usr/games/luantiserver >/dev/null || { apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq luanti-server >/dev/null; }'
if [ '$GAME' = minetest ]; then
  proot-distro login debian -- sh -c '[ -d /usr/share/luanti/games/minetest_game ] || { apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq luanti-game-minetest >/dev/null; }'
fi
proot-distro login debian -- /usr/games/luantiserver --version 2>&1 | head -1

mkdir -p ~/luanti/games ~/luanti/worlds
cd ~/luanti/games
if [ '$GAME' != mineclonia ]; then
  :
elif [ -z '$MC_VER' ]; then
  [ -d mineclonia ] || { echo 'Mineclonia not installed and content.luanti.org is down; try again later' >&2; exit 1; }
elif [ \"\$(cat mineclonia.version 2>/dev/null)\" != '$MC_VER' ]; then
  rm -rf mineclonia && curl -sSfL -o mc.zip '$MC_URL' && unzip -q mc.zip && rm mc.zip
  echo '$MC_VER' > mineclonia.version
fi
# opening a world with another game turns its blocks into 'unknown' ones: refuse
WG=\$(sed -n 's/^gameid *= *//p' ~/luanti/worlds/'$WORLD'/world.mt 2>/dev/null)
if [ -n \"\$WG\" ] && [ \"\$WG\" != '$GAME' ]; then
  echo \"The world '$WORLD' is a \$WG world. To play $GAME, also set a new LUANTI_WORLD in .env\" >&2; exit 1
fi

cat > ~/luanti/luanti.conf <<'EOF'
server_name = drawer-server
server_description = Home server running on an old phone
server_announce = false
name = $ADMIN
max_users = 10
creative_mode = $CREATIVE
enable_damage = $DAMAGE
only_peaceful_mobs = $PEACEFUL
default_privs = $PRIVS
EOF

cat > ~/.termux/boot/30-luanti.sh <<'EOF'
#!/data/data/com.termux/files/usr/bin/sh
# start the game server unless it's already running
PID=\$HOME/luanti/server.pid
if [ -f \$PID ] && kill -0 \"\$(cat \$PID)\" 2>/dev/null; then exit 0; fi
cd \$HOME/luanti
nohup proot-distro login debian --bind \$HOME/luanti:/srv/luanti -- \\
  env MINETEST_GAME_PATH=/srv/luanti/games /usr/games/luantiserver \\
  --gameid $GAME --world /srv/luanti/worlds/$WORLD --config /srv/luanti/luanti.conf --port $PORT \\
  > server.log 2>&1 &
echo \$! > \$PID
EOF
chmod +x ~/.termux/boot/30-luanti.sh
# restart so a changed luanti.conf takes effect (players get dropped for a few seconds)
# (SIGTERM goes to the server inside proot, so it saves the world; proot then exits)
if [ -f ~/luanti/server.pid ] && pkill -TERM -P \$(cat ~/luanti/server.pid); then
  for i in \$(seq 1 20); do kill -0 \$(cat ~/luanti/server.pid) 2>/dev/null || break; sleep 1; done
fi
: > ~/luanti/server.log
sh ~/.termux/boot/30-luanti.sh
for i in \$(seq 1 40); do grep -q 'listening on' ~/luanti/server.log 2>/dev/null && break; sleep 3; done
grep 'listening on' ~/luanti/server.log || { tail -20 ~/luanti/server.log; exit 1; }"

say "Game server ready"
cat <<EOF
  On each Android phone/tablet: install "Luanti" from the Play Store (or F-Droid).
  On Windows: download it from https://www.luanti.org/downloads/
  Then: Join Game > Address: $HOST   Port: $PORT
  Pick any name and password the first time; that creates the player.
  The player named "$ADMIN" is the server admin.
EOF
