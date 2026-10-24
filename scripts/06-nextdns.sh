#!/usr/bin/env bash
# Step 6 - Whole-home ad blocking with NextDNS (free tier: 300k queries/month).
#
# Why not AdGuard Home / Pi-hole on the phone? Without root, Android won't let programs use
# port 53 (DNS), and home routers can't send DNS to any other port. So the blocking runs in
# NextDNS's cloud, and the phone does the job a router can't: on Starlink and other CGNAT
# connections the home's public IP keeps changing, so every 5 minutes the phone tells
# NextDNS "this is still us" (the "linked IP" update URL).
#
#   Put NEXTDNS_LINK_URL in .env, then:  bash scripts/06-nextdns.sh
#
# Get that URL in my.nextdns.io > Setup > Linked IP > "Show advanced options".
# It is a secret: it lives in .env (gitignored) and on the phone only.
source "$(dirname "$0")/lib.sh"

load_phone_env
NEXTDNS_LINK_URL="${1:-${NEXTDNS_LINK_URL:-}}"
if [ -z "$NEXTDNS_LINK_URL" ]; then
  warn "Skipped: no NEXTDNS_LINK_URL in .env (see .env.example). Optional step."
  exit 0
fi
[[ "$NEXTDNS_LINK_URL" =~ ^https://link-ip\.nextdns\.io/[0-9a-f]+/[0-9a-f]+$ ]] || die "That doesn't look like a NextDNS link-ip URL."
HOST="${PHONE_LAN_IP:?run scripts/04-network.sh first}"

say "Installing the linked-IP updater on the phone (runs every 5 minutes, starts on boot)"
phone_ssh "$HOST" "mkdir -p ~/.config/drawer-server ~/bin ~/.termux/boot
umask 077; printf '%s\n' '$NEXTDNS_LINK_URL' > ~/.config/drawer-server/nextdns-link-url
cat > ~/bin/nextdns-link-loop.sh <<'EOF'
#!/data/data/com.termux/files/usr/bin/sh
# Tell NextDNS our current public IP every 5 minutes (CGNAT IPs change).
LOG=\$HOME/.cache/nextdns-link.log
mkdir -p \$HOME/.cache
while true; do
  r=\$(curl -fsS -m 20 \"\$(cat \$HOME/.config/drawer-server/nextdns-link-url)\" 2>&1)
  echo \"\$(date '+%F %T') \$r\" >> \$LOG
  tail -n 200 \$LOG > \$LOG.tmp && mv \$LOG.tmp \$LOG
  sleep 300
done
EOF
chmod +x ~/bin/nextdns-link-loop.sh
cat > ~/.termux/boot/20-nextdns-link.sh <<'EOF'
#!/data/data/com.termux/files/usr/bin/sh
# start the updater unless it's already running (pid file, so we never start two)
PID=\$HOME/.cache/nextdns-link.pid
mkdir -p \$HOME/.cache
if [ -f \$PID ] && kill -0 \"\$(cat \$PID)\" 2>/dev/null; then exit 0; fi
nohup sh \$HOME/bin/nextdns-link-loop.sh >/dev/null 2>&1 &
echo \$! > \$PID
EOF
chmod +x ~/.termux/boot/20-nextdns-link.sh
sh ~/.termux/boot/20-nextdns-link.sh
sleep 8
echo \"  updater running: \$(kill -0 \"\$(cat ~/.cache/nextdns-link.pid)\" 2>/dev/null && echo yes || echo NO)\"
echo \"  NextDNS says: \$(tail -n 1 ~/.cache/nextdns-link.log)\""

say "Last step: point your router's DHCP DNS at NextDNS"
cat <<'EOF'
  In the router's DHCP settings set:
     Primary DNS   = 45.90.28.40
     Secondary DNS = 45.90.30.40
  (TP-Link Archer AX23: Advanced > Network > DHCP Server, then SAVE.)

  Devices pick up the new DNS when they reconnect to Wi-Fi (or when their lease renews).
  Check it at https://test.nextdns.io from any device at home: "status": "ok".
  To undo: clear those two fields in the router and save.
EOF
