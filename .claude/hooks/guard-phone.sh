#!/usr/bin/env bash
# PreToolUse hook for Bash: makes the human confirm anything that could erase or unlock the phone.
# AGENTS.md: Path A never runs fastboot, unlock, wipe or format commands without explicit consent.
# It only asks, never blocks, so a false alarm (e.g. grepping the docs) costs one click.
input="$(cat)"
pattern='fastboot|oem[ _-]?unlock|flashing[ _-]?(un)?lock|reboot +(bootloader|recovery|fastboot|edl|download)|wipe|mkfs|sm +(format|partition)|pm +clear|factory[ _-]?reset|master_clear'

match="$(printf '%s' "$input" | grep -oiE "$pattern" | head -1 | tr -cd '[:alnum:] _-')"
[ -n "$match" ] || exit 0

printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":"%s"}}\n' \
  "This command may erase or unlock the phone ($match). Path A never does that: approve only if you chose Path B on purpose."
