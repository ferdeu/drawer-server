#!/usr/bin/env bash
# Shared helpers. Source this from the other scripts.
# Works in Git Bash (Windows), Linux and macOS.

set -euo pipefail

# Git Bash on Windows rewrites args like /sdcard/x into C:/Program Files/Git/sdcard/x
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Secrets live in .env (gitignored); see .env.example
if [ -f "$REPO_ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source <(tr -d '\r' < "$REPO_ROOT/.env")
  set +a
fi
PHONE_DIR="/sdcard/Download/drawer-server"

say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[!] %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[1;31m[x] %s\033[0m\n' "$*" >&2; exit 1; }

find_adb() {
  if command -v adb >/dev/null 2>&1; then command -v adb; return; fi
  # winget installs Platform Tools here but the PATH only refreshes in new shells
  local w
  for w in "${LOCALAPPDATA:-}"/Microsoft/WinGet/Packages/Google.PlatformTools_*/platform-tools/adb.exe \
           "$HOME"/AppData/Local/Microsoft/WinGet/Packages/Google.PlatformTools_*/platform-tools/adb.exe \
           "$HOME"/Library/Android/sdk/platform-tools/adb \
           "$HOME"/Android/Sdk/platform-tools/adb; do
    [ -x "$w" ] && { echo "$w"; return; }
  done
  die "adb not found. Install Android SDK Platform Tools (see docs/path-a.md, step 0)."
}

ADB="$(find_adb)"
adb() { "$ADB" "$@"; }

require_device() {
  local n
  n="$(adb devices | awk 'NR>1 && $2=="device"' | wc -l | tr -d ' ')"
  if [ "$n" = "0" ]; then
    adb devices -l >&2
    die "No authorized phone. Enable USB debugging and accept the prompt on the phone (docs/path-a.md, step 0)."
  fi
  [ "$n" = "1" ] || die "More than one phone connected. Leave only one plugged in."
}

# ...so local file paths handed to the Windows adb.exe must be converted by hand
localpath() { if command -v cygpath >/dev/null 2>&1; then cygpath -w "$1"; else echo "$1"; fi; }

# wait_for "<what the human must do>" <timeout-seconds> <command...>
# Polls until the command succeeds, so it works for humans and for agents alike.
wait_for() {
  local msg="$1" timeout="$2"; shift 2
  local waited=0
  printf '\033[1;35m[phone] %s\033[0m\n' "$msg"
  until "$@" >/dev/null 2>&1; do
    sleep 3; waited=$((waited + 3))
    [ "$waited" -lt "$timeout" ] || die "Gave up waiting after ${timeout}s: $msg"
  done
}

KEY="$HOME/.ssh/drawer_server_ed25519"
load_phone_env() {
  [ -f "$REPO_ROOT/local/phone.env" ] || die "Run scripts/03-setup-ssh.sh first."
  # shellcheck disable=SC1091
  source "$REPO_ROOT/local/phone.env"
}

# phone_ssh <host> <command> - run a command inside Termux
phone_ssh() {
  local host="$1"; shift
  ssh -i "$KEY" -p 8022 -o StrictHostKeyChecking=accept-new -o ConnectTimeout=8 "$TERMUX_USER@$host" "$@"
}

prop() { adb shell getprop "$1" | tr -d '\r'; }
