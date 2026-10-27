---
name: new-step
description: Add a new numbered setup step (scripts/NN-name.sh) to drawer-server, following the repo's conventions end to end.
disable-model-invocation: true
argument-hint: "<what the step should set up, in any words>"
---

# Add a new step

The human described the step as: $ARGUMENTS

Their description may be short or rough. Before writing code, restate in one or two lines what the
step will do, on the phone and on the computer, and what the human has to do by hand. Ask only if a
choice is really theirs (a paid service, something that erases data, which phone it runs on).

## Conventions (copy them from the latest step, e.g. scripts/10-smart-plug.sh)

1. **File**: `scripts/NN-short-name.sh`, NN = next free number. Starts with `#!/usr/bin/env bash`
   and a header comment: `# Step NN (optional) - <what and why, in plain words>`, then
   "Before running it:" steps for the human, and the exact command to run it.
2. **Helpers**: `source "$(dirname "$0")/lib.sh"`. Use `say`, `warn`, `die`, `load_phone_env`,
   `phone_ssh "$HOST" ...`, `wait_for "<what the human must do>" <seconds> <check>` (prints the purple
   `[phone]` line and polls; never wait for Enter). Over Wi-Fi: `HOST="${PHONE_LAN_IP:?...}"`.
3. **Safe to re-run**: check before installing or creating (`command -v x || pkg install ...`).
4. **Secrets and settings** go in `.env` and get a commented, empty line in `.env.example`.
   Never print secrets; pass them over stdin like step 10 does. Per-phone data goes in `local/`.
5. **Path A**: nothing that erases, unlocks or flashes the phone. No `fastboot`, `oem unlock`, wipe.
6. **Gotchas** (AGENTS.md): `/sdcard/...` args need `MSYS_NO_PATHCONV` (lib.sh sets it); local paths
   for `adb.exe` go through `localpath`; filter `dumpsys` on the phone side, not with `grep -m1`.
7. **Phone-side code** goes in `termux/` and is copied with `scp -q -i "$KEY" -P 8022 ...`.

## Wire it in

- Optional steps that need something special (one per family phone, a device to pair) stay out of
  `setup.sh` and get an `echo` hint at its end; core steps go into its `STEPS` list.
- Update `AGENTS.md` (how to run it, what to tell the human), `README.md` and `docs/services.md`.
- If it adds a panel card, follow the existing cards in `termux/panel/panel.py` (English and Spanish text).

## Finish

- The edit hook runs shellcheck on every `.sh` you touch; fix what it reports.
- Offer to run the step with the human, one step at a time, relaying `[phone]` lines in their language.
- Then run the `check-server` skill to confirm nothing else broke.
