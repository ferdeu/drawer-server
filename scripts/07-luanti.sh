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
#   bash scripts/07-luanti.sh                install + start (safe to re-run)
#   LUANTI_ADMIN=Fer bash scripts/07-luanti.sh   that player name gets all privileges
source "$(dirname "$0")/lib.sh"

load_phone_env
HOST="${PHONE_LAN_IP:?run scripts/04-network.sh first}"
ADMIN="${LUANTI_ADMIN:-admin}"
PORT="${LUANTI_PORT:-30000}"

say "Finding the latest Mineclonia release"
# newest release is first; plain grep so it works without Python
JSON="$(curl -sSf https://content.luanti.org/api/packages/ryvnf/mineclonia/releases/)"
MC_URL="$(grep -o '"url": *"[^"]*"' <<<"$JSON" | head -1 | sed 's/.*"\(http[^"]*\)"/\1/')"
MC_VER="$(grep -o '"title": *"[^"]*"' <<<"$JSON" | head -1 | sed 's/.*: *"\([^"]*\)"/\1/')"
[ -n "$MC_URL" ] && [ -n "$MC_VER" ] || die "Couldn't read the Mineclonia release list from content.luanti.org"
echo "  Mineclonia $MC_VER"

say "Installing Debian + Luanti server on the phone (first time: a few minutes)"
phone_ssh "$HOST" "set -e; [ -n \"${DEBUG:-}\" ] && set -x
pkg install -y proot-distro >/dev/null 2>&1
proot-distro login debian -- true 2>/dev/null || proot-distro install debian >/dev/null 2>&1
proot-distro login debian -- sh -c 'command -v /usr/games/luantiserver >/dev/null || { apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq luanti-server >/dev/null; }'
proot-distro login debian -- /usr/games/luantiserver --version 2>&1 | head -1

mkdir -p ~/luanti/games ~/luanti/worlds
cd ~/luanti/games
if [ \"\$(cat mineclonia.version 2>/dev/null)\" != '$MC_VER' ]; then
  rm -rf mineclonia && curl -sSfL -o mc.zip '$MC_URL' && unzip -q mc.zip && rm mc.zip
  echo '$MC_VER' > mineclonia.version
fi

cat > ~/luanti/luanti.conf <<'EOF'
server_name = drawer-server
server_description = Home server running on an old phone
server_announce = false
name = $ADMIN
max_users = 10
creative_mode = false
enable_damage = true
default_privs = interact, shout, home
EOF

cat > ~/.termux/boot/30-luanti.sh <<'EOF'
#!/data/data/com.termux/files/usr/bin/sh
# start the game server unless it's already running
PID=\$HOME/luanti/server.pid
if [ -f \$PID ] && kill -0 \"\$(cat \$PID)\" 2>/dev/null; then exit 0; fi
cd \$HOME/luanti
nohup proot-distro login debian --bind \$HOME/luanti:/srv/luanti -- \\
  env MINETEST_GAME_PATH=/srv/luanti/games /usr/games/luantiserver \\
  --gameid mineclonia --world /srv/luanti/worlds/casa --config /srv/luanti/luanti.conf --port $PORT \\
  > server.log 2>&1 &
echo \$! > \$PID
EOF
chmod +x ~/.termux/boot/30-luanti.sh
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
