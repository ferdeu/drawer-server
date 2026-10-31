# drawer-server 📱➡️🖥️

**Turn the old phone sitting in your drawer into a small home server, without erasing anything.**

<img src="docs/img/panel.jpg" alt="The status panel on a phone: 'Everything works', internet, who's home, the server's battery, temperature, memory and storage, services, and the devices on the Wi-Fi." width="260" align="right">

This started as a weekend project to play and learn (with kids watching). An old Android phone is
a surprisingly good server: 8 CPU cores, several GB of RAM, lots of storage, its own battery as a
built-in UPS, and it uses about as much power as a night light.

Everything here is **scripted**. Clone the repo, plug the phone in, run one command, and tap a few
buttons on the phone when told to. You get the same result without the whole learning process.

## What you get

- 🐧 **A small Linux inside the phone** ([Termux](https://termux.dev)), controlled from your
  computer over SSH, by cable, by Wi-Fi or from anywhere.
- 🔋 **On 24/7:** Android won't kill it, and it starts by itself when the phone reboots.
- 🌍 **Access from outside home** with [Tailscale](https://tailscale.com), even on Starlink or other
  connections where opening router ports doesn't work.
- 🧩 **Optional services, one script each:** ad blocking for the whole home, a Minecraft-like game
  server for the kids, photo backup from the family's phones, and a battery saver that charges
  between 30 and 80% with a smart plug.
- 📊 **A status panel** (right): a web page that shows whether everything at home works.

**Nothing gets unlocked, rooted or erased.** Your apps and photos stay where they are, and every
setting can be undone ([how](docs/path-a.md#undoing-everything)).

## What you need

**To start (steps 0–5):**

- An Android phone with **Android 11 or newer**; 4 GB of RAM or more is comfortable.
- Its **charger**: it stays plugged in.
- A **USB cable that carries data** (some cheap ones only charge).
- A **computer**: Windows with [Git Bash](https://git-scm.com/download/win), macOS or Linux. Only for setup.
- **Home Wi-Fi** and the password of your **router's admin page**, to give the phone a fixed address.
- A **Google account** on the phone (to install Tailscale from the Play Store) and a free
  **Tailscale** account (signing in with Google works).

**Only for the optional steps:**

| For | You need |
|---|---|
| Ad blocking (6) | a free [NextDNS](https://nextdns.io) account |
| Photo backup (9) | the family's phones, one at a time |
| Battery saver (10) | a Wi-Fi smart plug that works with the **Smart Life** app (Tuya), and a free iot.tuya.com account |
| Cameras (11) | cameras with RTSP (tested: Ezviz H8c), each with a fixed IP in the router |
| Panel cards | whatever you have: Starlink, a TP-Link router, an Epson printer ([details](docs/panel.md)) |

## Quick start

1. **On the phone:** enable developer options and USB debugging ([how](docs/path-a.md#step-0-look-at-the-phone)).
2. **On the computer:** install Android Platform Tools (`adb`):
   - Windows: `winget install Google.PlatformTools`
   - macOS: `brew install android-platform-tools`
   - Debian/Ubuntu: `sudo apt install adb`
3. Plug the phone in, then:
   ```bash
   git clone https://github.com/ferdeu/drawer-server.git
   cd drawer-server
   cp .env.example .env      # your settings; steps 0-5 work with it empty
   bash setup.sh
   ```
4. Do what the purple `[phone]` messages say. If a step fails, fix it and resume with `bash setup.sh <step>`.

Using an AI coding agent? Point it at [AGENTS.md](AGENTS.md) and it can drive the whole thing.

## The steps

`bash setup.sh` runs steps 0 to 8 in order. Steps 9 to 11 are separate commands you run when you're ready.

| Step | What it does | | What you do on the phone |
|---|---|---|---|
| 0 | Looks at the phone (read-only) | required | "Allow USB debugging?" → **Always allow from this computer** → Allow |
| 1 | Stops Android from killing background programs | required | nothing |
| 2 | Installs Termux and two add-ons from F-Droid | required | Play Protect warning ×3: tap the small **"Install anyway"**, **not** "Got it" ([why](docs/path-a.md#about-the-play-protect-warning)) |
| 3 | SSH, so the computer controls the phone; starts on boot | required | keep it unlocked on Termux while text types itself, then lock Termux in recent apps ([how](docs/path-a.md#if-the-server-stops-connection-refused)) |
| 4 | Tests Wi-Fi and shows what to reserve in the router | required | nothing; you add the address in your router |
| 5 | Tailscale, to reach it from anywhere | recommended | install from the Play Store, log in, accept the VPN |
| 6 | Ad blocking for the whole home | optional, skipped without `NEXTDNS_LINK_URL` in `.env` | nothing; you set two DNS addresses in the router |
| 7 | Game server for the kids ([Luanti](https://www.luanti.org)) | optional, skipped without `LUANTI_ADMIN` in `.env` | nothing |
| 8 | Status panel at `http://<phone-ip>:8080` | recommended | nothing |
| 9 | Photo backup: `bash scripts/09-syncthing.sh <name>`, once per person | optional | on *their* phone: install Syncthing-Fork, scan a QR |
| 10 | Charge between 30 and 80%: `bash scripts/10-smart-plug.sh` | optional | nothing; pair the plug in Smart Life first |
| 11 | Security cameras in the panel, at home: `bash scripts/11-cameras.sh` | optional, skipped without `PANEL_CAMERAS` in `.env` | nothing |

From step 6 on, everything goes over Wi-Fi: the cable is only needed for steps 0–5.
[docs/path-a.md](docs/path-a.md) explains each step and why.

<img src="docs/img/play-protect-warning.jpg" alt="Google Play Protect warning for Termux:Boot, in Spanish. Tap 'Instalar de todas formas' (Install anyway), not 'Entendido' (Got it)." width="280">

## Make it yours

Your settings live in `.env` (never uploaded, it's in `.gitignore`). [.env.example](.env.example)
lists every setting grouped by step. Change one, then re-run that step's script.

To get from the basic panel to one that knows your house (its name, who's home, the cameras and
devices on your Wi-Fi, printer ink), follow [docs/panel.md](docs/panel.md).

## If something goes wrong

- **A step failed:** fix what it says and resume with `bash setup.sh <step>`. Every step is safe to re-run.
- **SSH says "Connection refused":** Termux was closed. Open it on the phone, or plug the cable in
  and run `bash scripts/restart-server.sh` ([why it happens](docs/path-a.md#if-the-server-stops-connection-refused)).
- **Something else:** open an issue with the step and the error.

## Tested on

| Phone | Android | Result |
|---|---|---|
| Motorola **Moto G24 Power** (XT2425-1, `fogorow`, MediaTek Helio G85, 8 GB RAM) | 14 | ✅ steps 0–11 working |

It uses only standard Android features, so it should work on most phones with **Android 11 or newer**.
If you try another phone, please open an issue or PR with your results.

## Docs

- [docs/path-a.md](docs/path-a.md): every step, what it does and why, and how to undo it all.
- [docs/panel.md](docs/panel.md): the status panel, from zero to your own.
- [docs/services.md](docs/services.md): what else fits on the phone, with measured RAM and CPU.
- [docs/concepts.md](docs/concepts.md): the ideas in plain words (adb, Termux, SSH, CGNAT, root…).
- [docs/devices/moto-g24-power.md](docs/devices/moto-g24-power.md): notes for the tested phone,
  including "Path B" (unlocking and a custom ROM, which erases the phone; not scripted here).

## What's next

Ideas not built yet: recording the home's Wi-Fi cameras, a Minecraft Java server, Jellyfin (movies
on the TV). See [docs/services.md](docs/services.md) for what fits.

## Repo layout

```
setup.sh              runs steps 0-8 in order
scripts/              one script per step, run from your computer
termux/               what runs on the phone (boot setup, the panel)
docs/                 guides
.env.example          every setting; copy it to .env
apks/  local/         created on your machine, not committed
```
