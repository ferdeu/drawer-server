#!/data/data/com.termux/files/usr/bin/bash
# Runs INSIDE Termux on the phone (scripts/03-setup-ssh.sh types the command for you).
# Installs the SSH server, trusts your computer's key, and makes it start on boot.
set -euo pipefail

SHARE=/sdcard/Download/drawer-server
STATUS="$SHARE/status"
echo "started $(date)" > "$STATUS"
trap 'echo "failed at line $LINENO" >> "$STATUS"' ERR

export DEBIAN_FRONTEND=noninteractive
pkg update -y
pkg upgrade -y -o Dpkg::Options::=--force-confnew
pkg install -y openssh termux-api

# Only your computer's key gets in. No passwords over the network.
mkdir -p ~/.ssh
chmod 700 ~/.ssh
touch ~/.ssh/authorized_keys
while IFS= read -r key; do
  [ -n "$key" ] && ! grep -qxF "$key" ~/.ssh/authorized_keys && echo "$key" >> ~/.ssh/authorized_keys
done < "$SHARE/authorized_keys"
chmod 600 ~/.ssh/authorized_keys
CONF="$PREFIX/etc/ssh/sshd_config"
grep -q '^PasswordAuthentication no' "$CONF" || echo 'PasswordAuthentication no' >> "$CONF"

# Termux:Boot runs everything in ~/.termux/boot/ when the phone turns on
mkdir -p ~/.termux/boot
cat > ~/.termux/boot/10-sshd.sh <<'EOF'
#!/data/data/com.termux/files/usr/bin/sh
termux-wake-lock
sshd
EOF
chmod +x ~/.termux/boot/10-sshd.sh

# If Android force-stops Termux (e.g. "Clear all" in recents), just opening Termux
# again brings the server back.
touch ~/.bashrc
grep -q 'drawer-server' ~/.bashrc || cat >> ~/.bashrc <<'EOF'
# drawer-server: restart the server whenever Termux opens
pgrep -x sshd >/dev/null || { termux-wake-lock; sshd; }
for s in ~/.termux/boot/*.sh; do [ "$s" = ~/.termux/boot/10-sshd.sh ] || sh "$s"; done 2>/dev/null
EOF

termux-wake-lock
pkill sshd || true
sshd

echo "ready user=$(whoami) port=8022" >> "$STATUS"
echo
echo "=============================================="
echo " drawer-server: SSH is ready on port 8022"
echo " You can go back to your computer now."
echo "=============================================="
