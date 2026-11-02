# Motorola Edge 40 (`lyriq`)

| | |
|---|---|
| Models | XT2303-x (tested: XT2303-2, software channel RETAR) |
| SoC | MediaTek Dimensity 8020 (platform `mt6893`), 8 cores, arm64 |
| RAM / storage | 8 GB / 256 GB |
| Battery | 4400 mAh, 68 W wired, 15 W wireless (Qi) |
| Android tested | 15 (`V1TLS35.73-60-3-14`) |
| Treble | yes, A/B slots |

## Path A

✅ Works (November 2026). Steps 0–8 and 11 ran on it; it then took over from a Moto G24 Power with
[`scripts/move-server.sh`](../../scripts/move-server.sh) ([guide](../new-phone.md)), which brought steps 9 and 10 along: same
photos, game worlds, Syncthing identity, smart plug and home IP.

The tested phone had a cracked screen and a **USB-C port that no longer carries data** (and charges
only at some angles), so it was set up entirely over **Wireless debugging**
([how](../path-a.md#no-usb-cable-wireless-debugging)). Things that came up on this phone:

- **The Wi-Fi MAC changes.** Android 15 changed the made-up ("private") MAC on the same network
  several times in one night, so the router reservation stopped matching. Fix: Wi-Fi > the network >
  Privacy > **Use device MAC**. Step 4 now warns about it.
- **Tailscale's "Log in" did nothing** after removing Chrome: the login opens a browser and there was
  none. `extra-debloat.sh` keeps Chrome now.
- The VPN shows up as `tun1` instead of `tun0` (step 5 handles both).
- Play Protect hides "Install anyway" under **More details**
  ([photos](../path-a.md#about-the-play-protect-warning)).
- More preinstalled apps than the G24 (Amazon, Deutsche Telekom, Motorola Spaces, FM radio,
  recorder, Ready For desktop); `extra-debloat.sh` lists them.

### Charging through a smart plug

Step 10 works: the charger draws about 18 W from the plug and goes from 62 to 80% in about 20
minutes, then the panel cuts it. After a cut, switching the plug back on starts charging again
within seconds, even with the loose port. If the port gets worse, the phone also charges on a Qi
wireless pad, and the plug can switch that just the same.

## Path B (unlock + custom ROM): not done

- **No official LineageOS** as of November 2026.
- On the tested phone `sys.oem_unlock_allowed = 1` (the "OEM unlocking" switch is on), but unlocking
  needs `fastboot`, which needs a USB data connection, and this phone's port had none.

## Before you start: a hand-me-down phone

Remove the previous owner's **Google account** (Settings > Passwords & accounts) *before* a factory
reset. Otherwise, after the reset the phone asks for that account's password (Factory Reset
Protection) and you can't get past setup without it. Remove their eSIM too, if it had one.
