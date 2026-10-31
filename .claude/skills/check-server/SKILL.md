---
name: check-server
description: Check whether the phone server is alive and healthy (battery, temperature, memory, storage, SSH, NextDNS, Luanti, Syncthing, smart plug, cameras) over Wi-Fi or Tailscale, no cable. Use when the human asks if the server/phone/panel works, says something seems down or slow, or before and after deploying a change to the phone.
---

# Check the server

1. Run `bash .claude/skills/check-server/check.sh`. It reads the panel's `/api/status` over the
   home Wi-Fi, falls back to Tailscale, and prints a short summary (not the raw JSON).
2. Tell the human the result in plain words, in their language: what's fine, what's down.
3. If something is wrong, give the likely cause and the next step, but don't run fixes without asking:
   - Panel doesn't answer on either IP: phone off, off Wi-Fi, or Termux stopped. Try
     `source scripts/lib.sh; load_phone_env; phone_ssh "$PHONE_LAN_IP" true`. "Connection refused"
     means Android stopped Termux: needs the USB cable and `bash scripts/restart-server.sh`.
   - Battery reading stale: Termux:API was stopped; `scripts/restart-server.sh` wakes it.
   - A service DOWN: re-running its step is safe (07 Luanti, 06 NextDNS, 09 Syncthing, 08 panel, 11 cameras).
   - Battery over 45 C, or stuck at 100% plugged: warn the human (heat and full charge wear it out;
     step 10 keeps it between 30 and 80%).
