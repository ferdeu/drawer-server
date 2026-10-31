# Cameras in the status panel — design

Date: 2026-10-28. Status: approved and built.

**Changed while building:** live video doesn't go from the browser to go2rtc directly. go2rtc refuses
websockets from another page's origin, and opening it to any origin would let any website a home
user visits watch. So the panel passes live video through (`/live/ws`, `/live/video-rtc.js`), checks
that requests come from its own page at a plain IP address, and go2rtc listens on `127.0.0.1` only.
"Home only" therefore covers live video too.

## Intent

At home, looking at the security cameras should be instant: open the panel, see all cameras, tap one
to watch it live. Today that means opening the camera vendor's app (Ezviz), which is slow, needs a
login, shows ads and goes through the vendor's cloud even when you're on the same Wi-Fi.

Away from home the family keeps using the vendor app. This feature is **home-only**.

A wall tablet showing the panel all day is the next project; this one has to work well on it
(it will be looking at the camera card all day), but the tablet itself (kiosk mode, charging) is out
of scope here.

## Goals

- A **Cameras** card in the panel (`termux/panel/panel.py`) with one still image per camera that
  refreshes by itself about every 2.5 s, only while someone has the page open and visible.
- Tap a still → full-screen **live** view of that camera in high quality, with ◀ ▶ to go to the
  previous/next camera, pinch to zoom (digital) and a close button.
- Starts in 1–2 s, low delay, no cloud, no vendor login.
- Away from home (the panel reached over Tailscale), the card shows "home only" and loads nothing.
- Near-zero cost when nobody is looking.
- A new optional step, `scripts/11-cameras.sh`, sets it up and makes it start on boot. Skips itself
  when no cameras are configured, like steps 6 and 7.

## Non-goals

- Recording, playback, motion alerts, audio, talk-back, moving the camera (pan/tilt). The vendor app
  does those.
- Access from outside home.
- The Ezviz EP7 doorbell: it has no RTSP.
- Converting video formats on the server (transcoding).
- Computers with browsers that can't play H.265: they simply won't show live video. Accepted.
- The wall tablet setup (separate project).

## Anti-goals (would be a failure even if it works)

- Camera codes/passwords reaching the browser, the page source, logs, the repo or a command line
  visible in `ps`. The browser only ever knows a camera's name or index.
- The panel page getting slower to load, or failing, because a camera is offline.
- Constant CPU use on the server when nobody has the panel open.
- Anything that breaks Path A rules (no unlock, wipe, root).
- Opening a way to run commands on the server from the home network (see go2rtc below).

## What we know (measured 2026-10-28 on the real setup)

- 3 Ezviz H8c cameras on cable: Entrada `192.168.1.50`, Lateral `192.168.1.51`, Fondo
  `192.168.1.52`. RTSP on port 554, user `admin`, password = the camera's verification code.
  Paths: `/ch1/main/av_stream` (H.265, 2304×1296, 15 fps) and `/ch1/sub/av_stream` (H.265, 768×432,
  10 fps). A full frame (keyframe) every ~2.5 s. No ISAPI web API (404), so formats can't be read or
  changed over HTTP.
- **go2rtc v1.9.15** (`go2rtc_linux_arm64`, SHA-256
  `af416f22b21a24ab83b8d78642190b4932ae695b4e386853f11d1b0319781763`, the digest GitHub publishes for
  that asset) runs in Termux as a plain binary. Live view over **MSE** (`/api/ws`) works:
  - PC Chrome: all three at once, perfect.
  - Owner's phone (Chrome): one camera perfect (main or sub stream); **three
    videos at once stutter** (phone limit on simultaneous H.265 decoders). Hence stills in the grid.
  - Lenovo Tab M7 (MT6761): the main stream fails with `PIPELINE_ERROR_DECODE` (too big for its
    decoder). Weak devices exist; see the fallback below.
- go2rtc's own snapshot endpoint (`/api/frame.jpeg`) **crashes go2rtc on Android** (`SIGSYS` on the
  `faccessat2` syscall when it looks up ffmpeg). Anything in go2rtc that starts ffmpeg or an `exec:`
  source has the same problem. Don't use them.
- Stills with Termux's ffmpeg straight from the camera's sub stream, decoding keyframes only:
  `ffmpeg -nostdin -loglevel error -skip_frame nokey -rtsp_transport tcp -i <sub url> -fps_mode passthrough -q:v 5 -update 1 -y <file>.jpg`
  gives one new JPEG (~100 KB) every ~2.5 s per camera, ~14% of one core for all three
  (decoding every frame instead costs ~44%). The server has 8 cores.

## How it works

### go2rtc (live video)

- Step 11 downloads the pinned go2rtc version and **refuses to install it if the SHA-256 doesn't
  match** the value pinned in the script. Updating go2rtc = changing version + hash in the script.
- Config in `~/.config/drawer-server/go2rtc.yaml`, written with `umask 077`, codes sent over stdin
  (never in a command line), like the router password in step 8.
- Streams named by index: `cam1`, `cam1_hd`, `cam2`, … (`camN` = sub, `camN_hd` = main). Names
  shown to people come from `.env`.
- Only what's needed is turned on: the HTTP API on port 1984 for MSE, and its RTSP server on
  `127.0.0.1` only (for the stills, see below). WebRTC off.
- **Locked down**: go2rtc's API can add streams and change its config, and `exec:` sources run
  commands. Use go2rtc's `api: allow_paths` so only the paths the live view needs are reachable
  (the websocket `/api/ws` plus the player script if the page uses go2rtc's; the builder confirms
  the exact list). Config editing, `/api/streams` writes and the web UI must be unreachable.
- Starts on boot via `~/.termux/boot/60-cameras.sh`, same pattern as the panel (pid file, "already
  running? exit").

### Stills (the grid)

- The panel serves `/api/camera/<n>.jpg`. The first request for a camera starts the ffmpeg command
  above for that camera; the image keeps being overwritten. If nobody asks for that camera for ~30 s,
  the panel stops its ffmpeg. Result: CPU only while someone looks.
- My call: ffmpeg reads the sub stream **through go2rtc** at `rtsp://127.0.0.1:8554/camN`, so no
  code ever appears in ffmpeg's command line, and each camera keeps a single connection (go2rtc
  shares it between the live view and the stills). go2rtc's RTSP server listens on `127.0.0.1` only.
- No image yet / camera offline → the card shows a placeholder with "no image", never breaks the page.
- The page refreshes each still every 2.5 s with a cache-busting query, only while
  `document.visibilityState === "visible"`.

### Live view

- Tap a still → full-screen overlay with the live main stream from go2rtc over MSE (the browser
  connects to `http://<server>:1984` directly; the panel's standard-library server can't proxy
  websockets).
- **Fallback (my call):** if the main stream fails to decode or doesn't start in ~5 s, switch to the
  sub stream automatically. That covers weak tablets like the Lenovo.
- ◀ ▶ buttons and swipe go to the previous/next camera; pinch-to-zoom and pan on the video (CSS
  transform), double-tap resets. Close with ✕ or the back button.
- Only one live video at a time.

### Home only

- The panel decides by the address the request comes from: private ranges (192.168.x, 10.x,
  172.16–31.x) = home; anything else (Tailscale 100.64.0.0/10) = away. Away: the card says "home
  only", `/api/camera/*` returns 403, nothing starts.
- No login, like the rest of the panel (owner's decision): anyone on the home Wi-Fi can watch.
  Guests who shouldn't can get the router's guest network.
- My call: at home, people open the panel by its home Wi-Fi address (`http://<server-ip>:8080`),
  not the Tailscale one; a device with Tailscale on still reaches that address over the Wi-Fi, so it
  counts as home. The docs say so, and the "home only" text shows the home address to use.

### Configuration (`.env`)

- My call: one line, name, address and code per camera:
  `PANEL_CAMERAS="Entrada=192.168.1.50:CODE,Lateral=192.168.1.51:CODE,Fondo=192.168.1.52:CODE"`
  Defaults fit Ezviz/Hikvision (`admin`, port 554, `/ch1/main/av_stream`, `/ch1/sub/av_stream`);
  `CAMERA_USER`, `CAMERA_MAIN_PATH`, `CAMERA_SUB_PATH` override them for other brands.
- Without `PANEL_CAMERAS`, step 11 skips itself and the panel shows no card.
- Step 11 writes the names (no codes) to `~/.config/drawer-server/cameras` for the panel, and the
  stream URLs to the go2rtc config. Re-running it is safe (re-writes config, restarts go2rtc, then
  re-runs step 8 like step 10 does).

### Panel integration

- The card goes near the top, after the "everything works" line and Internet. Builder's call on the
  exact spot, keeping the current look (`docs/panel.md`).
- "Cameras" appears in Services (go2rtc alive), with a friendly name in both languages.
- Texts in `TEXT` for `en` and `es`.
- The existing "camera offline" problem line (from the router card) stays as is.

## Docs and tooling to update

`.env.example`, `README.md` (steps table), `docs/path-a.md` (step 11), `docs/services.md`,
`docs/panel.md`, `AGENTS.md` (topic table, step list), `.claude/skills/check-server` (go2rtc alive),
`docs/img/panel.jpg` if the card changes the screenshot (fake data, no real camera images).

## Cleanup

Remove the test install on the server (`~/spike-go2rtc`, its go2rtc process on port 1984) before
step 11 runs the first time.

## Left to the builder

- Exact go2rtc `allow_paths` list and whether to use go2rtc's `video-stream.js` player or a minimal
  MSE client in the panel page.
- Card layout details, swipe/zoom implementation, timeouts.
- How the panel finds go2rtc's port (default 1984, overridable).
