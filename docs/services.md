# Services

What you can run on the phone, with **numbers measured on the test phone** (Moto G24 Power,
8 GB RAM, 8 cores, Android 14, Path A / no root) on 2026-10-24.

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
| **Status panel** (small Python web page) | battery, temperature, RAM, disk, services, 24 h battery chart, charge reminder; photo backup progress; optional Starlink dish stats, Epson ink levels and who's home | **~25 MB** | ~0 | ⭐ easy | ✅ `scripts/08-panel.sh` → `http://<phone-ip>:8080` |
| **Camera recorder** (ffmpeg, RTSP) | record Wi-Fi cameras 24/7 or by schedule | est. 30–60 MB per camera | low (copies the video, doesn't re-encode) | ⭐⭐ medium | ⏳ needs the cameras' RTSP password |
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
≈ 2.0 + 0.05 + 0.15 + 0.02 + 0.003  ≈ 2.3 GB
```

Jellyfin (~0.5 GB) also fits on RAM, but avoid using it while kids are playing Minecraft:
both want the CPU. Storage is the other limit: video recording fills disks fast
(a 1080p camera stream is roughly 15–40 GB per day), so recorder setups need a retention limit
or the cameras' lower-resolution sub-stream.

## Panel home cards

Set in `.env`, then re-run `scripts/08-panel.sh`:

| Card | Setting | How it works |
|---|---|---|
| 🛰️ Starlink | `PANEL_STARLINK=yes` | the dish's local gRPC API at `192.168.100.1:9200` (`grpcurl`), no account needed |
| 🖨️ Epson ink | `PANEL_PRINTER_IP=…` | Epson's own SNMP status query (`@BDC ST2`), works on old models like the XP-211 that don't fill the standard printer-supplies table |
| 🏠 Who's home | `PANEL_PEOPLE="Ana=192.168.1.20,Bo=192.168.1.21"` | pings each phone every 2 min; "home" if it answered in the last 20 min (sleeping phones skip pings). Give those phones fixed IPs in the router. |

The panel also shows a 📷 **Photo backup** card by itself once step 9 is set up: each phone's
folder, whether that phone is connected, how much is left and the download speed.

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
- The world lives in `~/luanti/worlds/casa` in Termux. Copy that folder to back it up.

## Minecraft notes (from the test)

- First start (creating the world) took **55 s**; the world uses **235 MB** of disk.
- Harmless errors at start: `JNA ... libc.so.6 not found`. It's a hardware-info library that
  doesn't know Android. The server runs fine.
- Latest Minecraft (26.x) needs **Java 25** (`pkg install openjdk-25`). Termux also has 17 and 21 for older versions.
