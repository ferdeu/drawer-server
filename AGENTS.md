# Instructions for AI agents

You are helping someone turn an old Android phone into a home server with this repo.

## How to run it

1. Detect the OS. On Windows use Git Bash (`bash`), not PowerShell or cmd.
2. Make sure `adb` is installed (`winget install Google.PlatformTools`, `brew install android-platform-tools`
   or `sudo apt install adb`). `scripts/lib.sh` also finds winget's install folder if PATH isn't refreshed yet.
3. Run steps one at a time, so you can show the human each result:
   `bash scripts/00-recon.sh`, then `01`, `02`… or `bash setup.sh <n>` to resume from step n.
4. Steps that need the human print a purple `[phone] ...` line and **poll** until it's done (no Enter
   key needed). Relay that message to the human right away, in their language.

## Rules

- Path A never erases or unlocks anything. Keep it that way. **Never** run `fastboot`, `flashing unlock`,
  `oem unlock`, wipe or format commands as part of Path A. If the human wants Path B (unlock / custom ROM),
  stop, explain that it erases the phone, and get explicit confirmation for every destructive command.
- Step 00 is read-only. If the phone isn't the tested one (`fogorow`), say so and proceed carefully.
- Step 2: warn the human **before** running it that Google Play Protect will show "Blocked unsafe app"
  three times and they must tap the small **"Install anyway"** text, not "Got it".
- Step 3: tell the human to unlock the phone and leave it on Termux; the script types into it.
- Steps 6–11 are optional and run over Wi-Fi (no cable needed). Step 6 skips itself without
  `NEXTDNS_LINK_URL` in `.env`, step 7 without `LUANTI_ADMIN`: ask the human before step 6 whether they
  want them. Steps 9, 10 and 11 are not in `setup.sh`. Run `bash scripts/09-syncthing.sh <name>`
  once per family phone, with that phone at hand, and relay the on-screen instructions. Step 10 (smart
  plug) needs the human to pair the plug and create a Tuya cloud project first; its header lists how.
  Step 11 (cameras) needs `PANEL_CAMERAS` in `.env` (cameras with RTSP and fixed IPs) and skips itself without it.
- If a step fails, stop. Show the error, explain it simply, propose options. Don't skip ahead.
- Explain things in plain words; people doing this may be beginners or kids.
- `local/` holds per-phone data (IPs, Termux user). It's gitignored. Never commit it.

## Where things are

The human may name things loosely ("the panel", "the plug", "photos", "the game"). Map them here:

| Topic | Files |
|---|---|
| Status panel web page and its cards | `termux/panel/panel.py`, deployed by `scripts/08-panel.sh`, cards set by `PANEL_*` in `.env` |
| What the router knows about each device, naming devices | `scripts/router-devices.sh` (read-only; detail in `local/router-devices.json`), names go in `PANEL_DEVICE_NAMES` |
| Charging between 30 and 80% (smart plug) | `scripts/10-smart-plug.sh`, `termux/plug-setup.py`; the cycling itself runs inside the panel |
| Photo backup from family phones | `scripts/09-syncthing.sh` |
| Security cameras in the panel (stills, live view) | `scripts/11-cameras.sh` (go2rtc), `termux/panel/cameras.py`; tests: `bash tests/run-on-phone.sh` |
| Game server for the kids | `scripts/07-luanti.sh` |
| Ad blocking | `scripts/06-nextdns.sh` |
| Access from outside home | `scripts/05-tailscale.sh` |
| Wi-Fi, phone IPs | `scripts/04-network.sh`, saved in `local/phone.env` |
| What runs when the phone boots | `termux/bootstrap.sh` |
| Server down, SSH "Connection refused" | `scripts/restart-server.sh` (needs the cable) |
| Shared helpers (`say`, `wait_for`, `phone_ssh`) | `scripts/lib.sh` |
| Docs for humans | `README.md`, `docs/path-a.md`, `docs/panel.md`, `docs/services.md`, `docs/concepts.md` |

## Checking your work (Claude Code)

- `.claude/settings.json` runs shellcheck on every `.sh` you edit and a syntax check on `.py`; it
  also asks the human before any command that could erase or unlock the phone.
- After changing something that runs on the phone, deploy it and use the `check-server` skill.
- Before committing, run the `path-a-reviewer` agent. To add a step, the human can use `/new-step`.

## Known gotchas

- Git Bash rewrites `/sdcard/...` arguments into Windows paths; `lib.sh` sets `MSYS_NO_PATHCONV=1`
  and uses `localpath` for local files passed to `adb.exe`.
- `dumpsys` piped into `grep -m1` makes adb fail with "Broken pipe" under `pipefail`; filter on the phone side.
