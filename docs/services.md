# Services

What you can run on the phone, with **numbers measured on the test phone** (Moto G24 Power,
8 GB RAM, 8 cores, Android 14, Path A / no root) on 2026-10-24.

**Your phone will differ.** CPU, RAM and heat depend on the phone's chip: on the second test phone
(Motorola Edge 40, a faster chip) decoding camera video cost roughly a quarter less than on the G24. Disk
and Wi-Fi depend on the phone too, and camera numbers also depend on the cameras (how often they
send a full frame, their bitrate). Use these as a guide, and check your own server in the panel's
🖥️ section (temperature, RAM, disk).

Starting point: with Android + SSH + the NextDNS updater running, about **4.9 GB of RAM is
available**, and **5.7 GB** after removing preinstalled bloat with `scripts/extra-debloat.sh`.
Leave ~1 GB for Android itself, so plan with **~4–4.5 GB** for services.

## The menu

| Service | What it's for | RAM | CPU | Difficulty | Status |
|---|---|---|---|---|---|
| **Ad blocker** (NextDNS) | blocks ads for the whole home | 3 MB (IP updater) | ~0 | ⭐ easy | ✅ `scripts/06-nextdns.sh` |
| **SSH / SFTP** | control the phone; copy files with WinSCP, FileZilla, etc. | 2 MB | ~0 | ⭐ easy | ✅ comes with step 3 |
| **Luanti + Mineclonia** (free Minecraft-like game) | a world for the kids; free clients on Android and Windows | **270–320 MB** | low; lag spike only while a new player downloads the textures | ⭐⭐ medium | ✅ `scripts/07-luanti.sh` |
| **Minecraft Java server** (Paper 26.2, Java 25) | a world for the kids | **1.3 GB** idle, plan 2 GB with players | **~33% of one core** idle (of 8 cores) | ⭐⭐ medium | 🧪 measured, script pending |
| **Syncthing** | automatic photo/file backup between phones and computers | **29 MB** idle | ~0 idle, bursts while syncing | ⭐⭐ medium | ✅ `scripts/09-syncthing.sh <name>` |
| **Status panel** (small Python web page) | battery, temperature, RAM, disk, services, 24 h battery chart, charge reminder; photo backup progress; optional Starlink dish stats, speed tests (~100 MB each, 0–6 a day), Epson ink levels and who's home | **~25 MB** | ~0 | ⭐ easy | ✅ `scripts/08-panel.sh` → `http://<phone-ip>:8080`, see [panel.md](panel.md) |
| **Cameras in the panel** (go2rtc + ffmpeg) | at home: a still of each camera every few seconds (each full frame the camera sends; ~4 s on the tested cameras), tap for live video | go2rtc ~20 MB | stills: ~14% of one core for 3 cameras on the G24, ~9% on the Edge 40, only while someone looks; live video is passed through, not re-encoded | ⭐⭐ medium | ✅ `scripts/11-cameras.sh` |
| **Camera recorder** (ffmpeg, RTSP) | motion clips from the step 11 cameras, with a few seconds from before the movement, watchable in the panel at home. Off by default | ~400 MB for 3 cameras, plus its Python program (measured on the Edge 40 without the Python part; the G24 estimate is ~260 MB) | 3 cameras, of one core: **~66%** in the default `fast` mode (~68% measured with its Python part, a real day with motion), **~38%** in `light` mode, including go2rtc's ~21% (Edge 40). Per camera: 12.3% `fast`, 3.1% `light`. G24 (estimate, not measured with 3 cameras): ~60–65% / ~25–30%. Plus ~7 Mbit/s of Wi-Fi (Edge 40, 5 GHz). Runs around the clock, so the phone runs warmer: on the Edge 40 it peaked at 35 °C after an hour while charging (33 °C without the recorder), see [path-a.md](path-a.md#heat-and-load-read-this-before-leaving-it-on) | ⭐⭐ medium | ✅ `scripts/12-recorder.sh` |
| **Jellyfin** ("home Netflix") | movies and shows on the TV/Chromecast | est. 300–500 MB (runs inside a Debian container, `proot-distro`) | fine if the TV plays the file as-is; re-encoding video is too heavy for a phone CPU | ⭐⭐⭐ hard | ⏳ not measured |
| **Uptime monitor** (e.g. Uptime Kuma) | logs when the internet goes down | est. 80–120 MB | low | ⭐⭐ medium | 💡 idea |
| **Bots / scripts 24/7** (Python, Node) | Telegram bot, alerts, automations | 20–80 MB each | depends | ⭐–⭐⭐ | 💡 idea |

Measured idle = server started, nobody connected. "est." = not measured yet.

### Not a good fit for this phone (Path A)

| Service | Why not |
|---|---|
| AdGuard Home / Pi-hole on the phone | needs port 53; Android blocks it without root (tested: 53 and 853 denied, 5353 allowed) |
| Windows shared folder (Samba) | Windows only talks to port 445, also blocked without root. Use SFTP instead. |
| Immich (Google Photos clone) | needs Docker and a machine-learning stack; too heavy for Termux. Syncthing covers the backup part. |
| Nextcloud | possible (PHP + database in a container) but heavy and fiddly for what it gives; Syncthing is lighter |
| Minecraft **Bedrock** server (official) | x86-only binary. Luanti + Mineclonia is the free alternative that runs here. A Java server + the Geyser plugin lets Bedrock players (tablets, phones, consoles) join. |

## How many at once?

With ~3.5–4 GB to spend, all of these fit **together**:

```
Minecraft (2 GB with players) + Syncthing + camera recorder (3 cameras) + status panel + NextDNS updater
≈ 2.0 + 0.05 + 0.4 + 0.02 + 0.003  ≈ 2.5 GB
```

That is RAM. The camera recorder also keeps part of the CPU busy all day (see its row), so with Minecraft
and the recorder together, watch the panel's temperature and use the recorder's `light` mode if the phone
runs hot.

Jellyfin (~0.5 GB) also fits on RAM, but avoid using it while kids are playing Minecraft:
both want the CPU. Storage is the other limit: video recording fills disks fast
(recording a 2K camera all day is ~10–15 GB a day; measured 1.0–1.4 Mbit/s), so the recorder only
keeps motion clips and has a size cap (`DISK_RECORDINGS_GB`, default 10% of the storage): at the cap
the oldest clips are deleted. The panel's storage card shows how the space is split between photo
backup and recordings.

## Status panel

What it shows, which cards you can add and how to set them up: [panel.md](panel.md).

## Photo backup notes (from the test)

- Run `bash scripts/09-syncthing.sh <name>` once per person, with their phone at hand. It shows a QR
  code; they install **Syncthing-Fork** on *their* phone (not on the server), scan it, and share
  `DCIM/Camera` as **Send Only**. The server accepts it by itself.
- Photos land in `Backups/<name>/Camera` on the server's storage. The server **ignores deletions**,
  so freeing space on a phone never deletes the backup.
- It only talks over the home network and Tailscale: no router port opening, no public relays.
- The first copy is the slow one. On the test it ran at ~1 MB/s with both phones on 2.4 GHz Wi-Fi
  and the server far from the router (20 GB ≈ 5 h). Later only new photos travel.
  Keep the sending phone plugged in with Syncthing open for that first copy.

## Luanti notes (from the test)

- Runs inside Debian 13 (`proot-distro`), Luanti 5.10 server; a 5.17 Windows client connected fine.
- A player's **first** join downloads all the game's textures, which takes a minute or two on Wi-Fi.
  Later joins are quick.
- The world lives in `~/luanti/worlds/casa` in Termux (or the folder set in `LUANTI_WORLD`). Copy that folder to back it up.

## Minecraft notes (from the test)

- First start (creating the world) took **55 s**; the world uses **235 MB** of disk.
- Harmless errors at start: `JNA ... libc.so.6 not found`. It's a hardware-info library that
  doesn't know Android. The server runs fine.
- Latest Minecraft (26.x) needs **Java 25** (`pkg install openjdk-25`). Termux also has 17 and 21 for older versions.
