# Camera recorder + disk budget: brief for the design

Status: decisions agreed with the owner on 2026-10-31, in a brainstorming conversation. Not a design yet.
A new session turns this into `docs/superpowers/specs/2026-10-31-recorder-design.md`. Whatever is
marked **(owner)** was said by the owner; **(proposed)** was proposed by Claude and accepted ("100% de acuerdo");
**(open)** is for the builder to settle and mark as its call.

## Why

The owner's own cameras already record motion to their microSD, so he won't use this now. It's for
**people who clone the repo**: an optional, off-by-default recorder that builds on step 11 (owner).
Owner's standing rule: anything someone may want to tune is a setting (in `.env`, written to a file
under `~/.config/drawer-server/` that the panel re-reads on each use), built so the panel could edit it
later even if that UI isn't offered yet.

## Part 1: motion recorder

- **What it records:** short clips when there's motion, with a few seconds before and after (owner).
  Default 5 s before, 10 s after, both in `.env` (proposed).
- **How (proposed):** keep the HD stream (`camN_hd` from go2rtc) as-is, no re-encoding, in short rolling
  segments; detect motion on the small stream (`camN`) at a few frames per second; keep the segments
  around motion and join them into one clip; drop the rest.
- **Motion detection:** the owner asked about "a Python library that detects motion": that's OpenCV
  (background subtraction). **(open)** OpenCV is not in Termux's main package list as far as checked
  (`apt-cache policy opencv-python python-opencv` found nothing); verify (TUR repo, pip). A lighter
  fallback: ffmpeg decodes the small stream at ~2 fps, scaled to e.g. 160x90 gray, piped to Python, and
  frame differencing (pure Python or `python-numpy`, which Termux has). Pick by CPU cost measured on the
  phone; it must stay light next to Luanti, the panel and stills.
- **Sensitivity** in `.env` (proposed). **Which cameras:** all from step 11 by default, optional list in
  `.env` (proposed).
- **On/off:** off by default; turned on from `.env` (owner).

## Part 2: "looks obstructed" (owner's idea)

- If a camera sees motion almost all the time (e.g. more than half of the last few minutes: a plant in
  the wind, a cobweb, rain), mark it "looks obstructed" (owner). Also an all-black or flat image, which
  usually means something covers the lens (proposed).
- `.env` chooses what happens then: keep recording, or pause that camera until it's back to normal (owner).
- Either way the panel's top line (where it says "Everything works") shows a warning like
  "⚠️ Lateral looks obstructed, check it", saying whether it's still recording or paused (owner). The
  warning clears by itself when the camera is back to normal (proposed).
- Real case: the owner's "Lateral" camera has a plant in frame that moves with the wind.

## Part 3: watching clips in the panel

- A "Recordings" section in the panel: per camera and per day, a small thumbnail and the time of each
  clip; tap to play (owner, as proposed).
- The section can be shown or hidden (owner): its own `.env` setting, separate from recording on/off,
  so someone can record without showing clips, e.g. on a tablet everyone in the house sees (proposed).
- Home only, like live view and stills (proposed; reuse `is_home` and `same_site` in `termux/panel`).

## Part 4: disk budget (owner)

- The owner wants a share of the disk for each thing that can grow and fill it: photo backups,
  recordings, and later ones (e.g. Jellyfin movies). Set in `.env` for now; the panel only shows it.
  Editing from the panel later is possible but needs protection (anyone on the home Wi-Fi could change
  it); build it so adding that is just the screen (owner agreed).
- **Not the same for each kind (agreed):**
  - Recordings: a hard cap; at the cap the oldest clips are deleted automatically.
  - Photo backups (and anything else people care about, like movies): never deleted. The budget is a
    warning ("⚠️ Photo backup near its limit"), optionally pausing Syncthing; never deleting.
- **Panel:** the 💾 disk card gets an expander with the split, roughly:
  `Photo backup 5 / 50 GB (10%) ▓░░░`, `Recordings 10 / 50 GB (20%) ▓▓░░`, and what's left free.
  Anything over 90% of its share shows in the top warning line like the other problems (proposed).

## Facts about the setup (2026-10-31)

- Phone: Moto G24 Power, Android 14, Termux, no root (Path A: never fastboot/unlock/wipe). 8 cores,
  8 GB RAM. Disk: 108 GB, 49 GB free; photo backups take 20 GB in `/sdcard/Backups`.
  (Since 2026-11-02 the server is a Motorola Edge 40: Android 15, 8 GB, 245 GB with 216 free. The design
  has the numbers measured again on it.)
- go2rtc 1.9.15 (`scripts/11-cameras.sh`), listens only on 127.0.0.1: API 1984, RTSP 8554. Streams
  `camN` (sub) and `camN_hd` (main), N from 1 in `PANEL_CAMERAS` order. Its config holds the camera
  codes (600 permissions); codes must never reach logs, `ps` or the repo.
- Cameras: 3 Ezviz H8c, H.265. Main 2304x1296 @15 fps, sub 768x432 @10 fps, a keyframe about every
  2.5 s (so stream-copy segments can only cut there). ISAPI doesn't exist (404).
- Stills: `termux/panel/cameras.py`, one keyframe-only ffmpeg per camera (`-skip_frame nokey`), ~14% of
  one core for all 3, started on demand and reaped when idle. ffmpeg is installed by step 11.
- Browsers: H.265 live view (MSE) plays on the owner's phone and PC Chrome; an old Lenovo tablet
  (TB-7306X) couldn't decode HD. Clips will be H.265 too: think about what plays them.
- Panel: `termux/panel/panel.py` (stdlib only, ThreadingHTTPServer), status JSON at `/api/status`,
  10 s refresh, texts in `TEXT` (en/es), recent example of the settings pattern: `PANEL_SPEEDTEST`
  (0-6 a day) in `scripts/08-panel.sh` → `~/.config/drawer-server/speedtest`, re-read on each use,
  with tests in `tests/test_panel_routes.py`. Tests run on the phone: `bash tests/run-on-phone.sh`.
- Repo rules: `AGENTS.md`. Everything committed is in English. Steps are numbered scripts in `scripts/`;
  this would likely be step 12, not in `setup.sh` (like 9-11). Update README, `docs/path-a.md`,
  `docs/panel.md`, `docs/services.md` (the "Camera recorder" row), `.env.example`, `AGENTS.md` table.
  Run the `path-a-reviewer` agent before committing.
