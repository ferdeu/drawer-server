# Moving the server to a new phone

Got a better phone for the server? This moves **everything** to it: the photo backups, the game
worlds, the settings, the smart plug, the panel's history, and the server's addresses at home and on
Tailscale. When you're done, nobody else has to change anything: the family's phones, the kids' game
and the panel bookmarks just reconnect on their own.

Nothing gets erased. The old phone keeps all its files until you decide what to do with it.

**Time:** about an hour of your time, plus a few hours to a night of copying photos (the computer
does that alone). **Downtime:** a few minutes, in part 4.

## What you need

- The **old phone**, still working as the server.
- The **new phone**, charged, on the home Wi-Fi. If it was someone else's, remove their Google
  account **before** you factory-reset it, or it will ask for their password afterwards.
- The **computer** you set up the old phone with (it has the `local/` folder and the SSH key).
- The **router's admin password**, and the **Tailscale account** the old phone uses.

Every command below runs on the computer, in the repo folder (Git Bash on Windows).

---

## Part 1: remember the old phone

```bash
bash scripts/move-server.sh save-old
```

This saves the old phone's addresses in `local/old-phone.env`. **Do it before part 2**, because
setting up the new phone overwrites them.

## Part 2: set up the new phone

Follow the normal setup with the new phone: [docs/path-a.md](path-a.md), **steps 0 to 8, and 11**
if you have cameras. Skip steps 9 and 10: the photos and the smart plug come over in part 4.

- Its USB port doesn't work? Use [wireless debugging](path-a.md#no-usb-cable-wireless-debugging).
- Step 2 asks three times about Play Protect: if you don't see "Install anyway", tap **More details**
  first ([photos](path-a.md#about-the-play-protect-warning)).
- Step 4 says to reserve the address in the router: **skip that this time**. The new phone gets a
  temporary address now, and takes the old phone's address in part 5.
- Step 5 (Tailscale): log in with the **same account** the old phone uses.

The old phone keeps working the whole time.

## Part 3: copy the photos

```bash
bash scripts/move-server.sh copy
```

It first saves a full backup of the old server on the computer (`local/old-server-home.tar`), then
copies the photo backups from the old phone to the new one. **This is the slow part**: about 20 GB
took a whole night over 2.4 GHz Wi-Fi. To make it faster, put both phones close to the router, or
on the 5 GHz Wi-Fi.

If it stops halfway (Wi-Fi drop, computer asleep), run the same command again: it continues where it
was. It finishes with "Done".

## Part 4: switch (a few minutes of downtime)

Pick a moment when **nobody is playing** the game.

```bash
bash scripts/move-server.sh switch
```

It stops everything on the old phone, copies the photos that arrived since part 3, the game worlds,
Syncthing (so the family's phones see it as the same server), the settings and the smart plug, then
starts everything on the new phone. At the end it lists the services, all "running".

From now on, the **new phone is the server**. It still has the temporary address, so parts 5 and 6
move it to the old phone's addresses.

## Part 5: give the new phone the old address

1. **Old phone:** turn its Wi-Fi **off** (or switch the phone off). Otherwise both phones fight
   over the same address.
2. **New phone:** *Settings → Wi-Fi →* tap your network (or its ⚙️) → **Privacy** (on some phones
   *MAC address type*) → **Use device MAC**. It reconnects by itself.

   Why: Android invents a "private" MAC address for each Wi-Fi network, and some phones change it now
   and then. The router recognizes the phone by that MAC, so it has to stay fixed.
3. **Write down the new phone's MAC:** it's on the same Wi-Fi network screen, under *MAC address*
   (six pairs like `a4:83:e7:12:34:56`). Or, if adb is still connected, run `bash scripts/04-network.sh`:
   it shows `MAC address: ...` (ignore its router instructions this time).
4. **Router:** open the router's page and find **Address Reservation** (on a TP-Link Archer AX23:
   *Advanced → Network → DHCP Server → Address Reservation*). You'll see the old phone's line with
   the server's address. **Edit** it: replace the MAC with the new phone's and keep the same IP.
   Save. (TP-Link: press Tab after typing, or the SAVE button stays grey.)
5. **New phone, by hand:** turn Wi-Fi **off**, wait 5 seconds, turn it **on**. That makes it ask
   the router again, and the router now gives it the old address.

   ⚠️ Do this with your finger, not from the computer: Android lets a script turn Wi-Fi off but
   not back on, and then the server is unreachable until someone touches it.
6. Still not on the old address after a minute? **Restart the router** (unplug it for 10 seconds),
   wait until the Wi-Fi is back, and do step 5 again.

## Part 6: give the new phone the old Tailscale address

So that bookmarks and apps that reach the server from outside home keep working.

1. Open [login.tailscale.com/admin/machines](https://login.tailscale.com/admin/machines) and log in
   with the server's Tailscale account.
2. On the **old phone's** row, open the **…** menu → **Remove** → confirm. Its address is free now.
3. On the **new phone's** row: **…** → **Edit machine IPv4** → type the old phone's address
   (`move-server.sh switch` printed it; it's also `PHONE_TS_IP` in `local/old-phone.env`) → Update.
4. On the new phone's row again: **…** → **Disable key expiry**. Otherwise Tailscale logs the server
   out after 180 days, and someone has to log it back in by hand.
5. Optional: **…** → **Edit machine name**, if you want the old name back.

## Part 7: the smart plug

Only if you use one (step 10). The new phone already controls it. Take the **old phone's** charger
out of the smart plug and plug in the **new phone's** charger. The panel turns the plug off at 80%
and on at 30%.

## Part 8: check everything

```bash
bash scripts/move-server.sh finish
```

It checks that the new phone answers at the old address and at the old Tailscale address, and points
this computer at it. If it says "Not yet", repeat part 5 (or part 6) and run it again.

Then open the panel at its usual address (`http://<server-ip>:8080`) and check:

- the battery is the **new** phone's,
- every service is OK,
- each family phone's **Syncthing** shows the server as connected. If one doesn't, open the
  Syncthing app on that phone once; it reconnects by itself, no new pairing.

## The old phone

Its services are stopped and won't start again after a reboot. Its files are still there, and in
`local/old-server-home.tar` on the computer. Keep it as a spare for a while; once you're sure nothing
is missing, you can reset it.

**To go back** to the old phone: turn its Wi-Fi on, put its MAC back in the router's reservation, and
in Termux on it run `mv ~/.termux/boot.moved/* ~/.termux/boot/` and restart the phone. Then turn the
new phone's Wi-Fi off.
