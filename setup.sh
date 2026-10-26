#!/usr/bin/env bash
# drawer-server - Path A orchestrator.
# Runs every step in order. Each step is safe to re-run.
# Nothing gets erased, nothing gets unlocked.
#
#   bash setup.sh            run all steps
#   bash setup.sh 3          start from step 3
set -euo pipefail
cd "$(dirname "$0")"

STEPS=(
  "scripts/00-recon.sh|Look at the phone (read-only)"
  "scripts/01-server-settings.sh|Stop Android from killing background programs"
  "scripts/02-install-termux.sh|Install Termux, Termux:Boot and Termux:API from F-Droid"
  "scripts/03-setup-ssh.sh|Set up SSH so this computer can control the phone"
  "scripts/04-network.sh|Test Wi-Fi access and show what to reserve in the router"
  "scripts/05-tailscale.sh|Tailscale, to reach the phone from outside home"
  "scripts/06-nextdns.sh|Ad blocking for the whole home with NextDNS (optional)"
  "scripts/07-luanti.sh|Game server for the kids: Luanti + Mineclonia"
  "scripts/08-panel.sh|Status panel web page"
)

cat <<'EOF'

  drawer-server - turn an old phone into a home server (Path A: nothing gets erased)

  What you'll be asked to do on the phone along the way:
    * Accept "Allow USB debugging?"                      (step 0)
    * Tap "Install anyway" on 3 Google Play Protect warnings
      - it's the small text above the big "Got it" button  (step 2)
    * Leave the phone unlocked on Termux for a few minutes (step 3)
    * Lock Termux in recent apps (padlock), so "Clear all" can't kill it
    * Install Tailscale from the Play Store and log in     (step 5)

EOF

from="${1:-0}"
for i in "${!STEPS[@]}"; do
  [ "$i" -ge "$from" ] || continue
  script="${STEPS[$i]%%|*}"; desc="${STEPS[$i]#*|}"
  printf '\n\033[1;32m################ Step %s: %s\033[0m\n' "$i" "$desc"
  if ! bash "$script"; then
    printf '\n\033[1;31mStep %s failed. Fix the problem above and resume with:  bash setup.sh %s\033[0m\n' "$i" "$i"
    exit 1
  fi
done

printf '\n\033[1;32mAll done! Your phone is now a server. Next: pick services in docs/services.md\033[0m\n'
echo "  Photo backup from each family phone:  bash scripts/09-syncthing.sh <name>"
