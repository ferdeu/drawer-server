# Camera recorder and disk budget — design

Date: 2026-10-31. Status: **approved by the owner** (2026-10-31), with three additions: heat check
and docs, panel stills from the recorder, and advice to pick `pause` for a camera facing a plant.
Built from `2026-10-31-recorder-brief.md` (decisions agreed with the owner) plus measurements taken on
the server the same day. Marks: **(owner)** the owner said it; **(agreed)** proposed in the brief and
accepted by the owner; **(my call)** decided while writing this, for the owner to check.

## Intent

Step 11 lets the family *watch* the cameras at home. This adds *recording*: short clips when something
moves, a few seconds before and after, kept on the server and watchable from the panel at home.

It is for **people who clone the repo** (owner). The owner's own cameras already record motion to
their microSD cards, so it ships **off by default** and the owner's server keeps it off unless the
owner turns it on (owner).

The second half is a **disk budget** (owner): the server's disk is shared by things that grow
(photo backups now, recordings, later movies for Jellyfin), and one of them must not quietly eat the
space the others need. Each one gets a share; the panel shows the split.

Owner's standing rule: anything someone may want to tune is a setting in `.env`, written by the step
script to a small file under `~/.config/drawer-server/` that the programs re-read when they use it,
so a future panel screen can edit settings without changing how the programs work.

## Goals

- **Motion clips** for the cameras from step 11: from about 5 s before the motion to 10 s after the
  last motion (owner; defaults agreed, both in `.env`). Full HD quality, video copied as the camera
  sends it, never re-encoded (agreed).
- **Light on the server** next to Luanti, the panel and the stills: see the CPU budget below.
- **"Looks obstructed"** (owner): a camera that sees motion most of the time (a plant in the wind, a
  cobweb, rain), or whose image is black or flat (something on the lens) (agreed), gets a warning in
  the panel's top line, e.g. "⚠️ Lateral looks obstructed, check it (still recording)". `.env` decides
  whether it keeps recording or pauses that camera (owner). The warning clears by itself (agreed).
- **Recordings in the panel** (owner): per camera and per day, a thumbnail and the time of each
  clip; tap to play. Home only, like live view (agreed). Shown or hidden by its own setting,
  separate from recording on/off (agreed).
- **Disk budget** (owner): a share per growing thing, set in `.env`; the panel's 💾 card shows the
  split. Recordings: a hard cap, oldest clips deleted at the cap. Photo backups: never deleted; the
  share is a warning, optionally pausing Syncthing (owner).
- A new optional **step 12**, `scripts/12-recorder.sh`, not in `setup.sh` (like 9–11).

## Non-goals

- Alerts or notifications on motion; telling people from cats or cars; zones to ignore part of the
  image (masks). The plant case is handled by "looks obstructed" for now.
- Recording around the clock, or on a schedule.
- Audio (my call: `-an`, as live view has none; camera audio codecs often don't play in browsers).
- Re-encoding: no H.265 → H.264 for devices that can't play H.265 (same as step 11).
- Watching clips away from home.
- Deleting clips, or changing any setting, from the panel. It would need protection (anyone on the
  home Wi-Fi can open the panel); the settings files are shaped so that screen can come later
  (owner agreed). Deleting clips by hand: SFTP/SSH (docs say where they are).
- Copying clips elsewhere (cloud, computer).
- The doorbell (no RTSP, as in step 11).

## Anti-goals (a failure even if it works)

- **Silently not recording.** A camera that is set to record but isn't being watched (ffmpeg keeps
  dying, go2rtc down, disk full, recorder down) must show in the top line.
- **Filling the phone's disk.** Android and Termux misbehave when storage runs out. The recorder
  keeps a free-space floor no matter what the shares say.
- **Deleting anything that isn't a clip the recorder made.** Above all, never a photo.
- **Writing to flash around the clock by design** (all the video, motion or not). A phone's storage
  is not made for that; writes must follow motion (see "pre-roll in memory"). The worst case, a camera
  that sees motion nearly all the time, is under "Looks obstructed".
- Camera codes in logs, `ps`, the repo or the browser (same rule as step 11). Real camera images in
  the repo (tests use made-up frames; screenshots use fake data).
- The panel getting slower or heavier: nothing about recordings loads until someone opens that
  section (a wall tablet shows the panel all day).
- A **permanent warning**. A recordings share sitting at its cap is normal operation, not a problem.
- Anything that breaks Path A (no unlock, wipe, root). Nothing here needs it.

## What we know (measured 2026-10-31 on the real server)

### OpenCV on this phone

The owner asked about "a Python library that detects motion": that's OpenCV. Findings:

- Not in Termux's main repository, not in TUR. pip has no build for this phone (Python 3.14 on
  Android, `android-24-arm64_v8a`).
- It **is** in Termux's **x11** repository: `opencv` 5.0.0 + `opencv-python`. Installing it means
  adding that repository and **40 packages** (Qt6, Mesa, X11 libraries, Perl): 89 MB download,
  **~514 MB on disk**.
- Its numpy needs a newer system C++ library than the server has (55 Termux packages are behind), so
  it only works after a full `pkg upgrade` first. Unpacked into a throwaway folder with that library,
  OpenCV 5.0 ran fine. Nothing was installed on the server; the test folder is deleted.

### CPU per camera

One camera (Lateral, sub stream 768×432 @ 10 fps, H.265 through go2rtc), 60 s per option, % of one
core (the phone has 8). "Diff" = count pixels that changed since the previous look.

| Option | CPU (of one core) | RAM |
|---|---|---|
| Look only at full frames (keyframes), pure Python diff | **3.7%** | 51 MB |
| Decode every frame, look twice a second, pure Python diff (160×90) | 17.3% | 61 MB |
| Same, numpy diff | 14.7% | 76 MB |
| Same, OpenCV background subtraction (MOG2, 320×180) | 20.1% | 136 MB |
| OpenCV MOG2, five looks a second | 30.6% | 136 MB |
| OpenCV opens the camera itself (all 10 fps) | 25.2% | 105 MB |
| Hardware decoder (`hevc_mediacodec`) | 17.7% (no gain) | 78 MB |
| Every frame, 1 thread, no loop filter, `+fast` (cheapest full decode found) | **14.4%** | — |
| Recording: HD stream copied, no decode | **2.1–2.5%** | 29 MB |

What this says: **decoding the video is the cost, not the detection method.** Anything that looks
at every frame costs ~15% of a core per camera, OpenCV or not. Looking only at full frames costs
~4%, but on these cameras a full frame comes **every ~4 s** (both streams, measured: 44 in 180 s;
the 2.5 s noted on 2026-10-28 is no longer true, so code must not assume an interval).

Pure Python at 320×180 took 37–45 ms per look with a naive loop: fine once every 4 s (~1%), but ~8%
of a core at two looks a second, so the fast mode needs the cheaper comparison described below.

### Other measurements

- HD stream: **1.0–1.4 Mbit/s** (0.12–0.17 MB/s) per camera, 2304×1296 @ 15 fps.
- Writing the HD stream to disk all the time (rolling segments, as the brief first proposed) would
  write 10–15 GB a day per camera, 30–44 GB a day for three: ~11–16 TB a year to the phone's flash.
- **Pre-roll in memory works** (spike): ffmpeg copies the HD stream as fragmented MP4 to a pipe
  (`-c copy -an -tag:v hvc1 -f mp4 -movflags frag_keyframe+empty_moov+default_base_moof pipe:1`).
  Each `moof`+`mdat` pair is one fragment starting at a full frame (~4 s, ~0.5 MB). Header boxes
  (`ftyp`+`moov`) + the last fragments, written to a file, remuxed with `-c copy -movflags +faststart`,
  gave a valid 16 s, 2304×1296 `hvc1` clip. Thumbnail from the clip: 0.7 s.
- **Pipe gotcha** (hit in the spike): stopping an ffmpeg that writes to a pipe nobody reads hangs,
  because ffmpeg tries to write its trailer. Close the pipe first, then kill.
- At rest (calm morning, 06:30) full frame to full frame at 320×180, pixels changed by more than 25
  levels: median 0.02%, max 0.28% across the three cameras. No wind then, so the plant was still;
  the windy case is still to be seen.
- Free disk: 49 GB of 108 GB; photo backups 20 GB in `/sdcard/Backups`.

## How it works

### The pieces

```
camera ──RTSP──▶ go2rtc (127.0.0.1, step 11)
                   ├─ camN (small) ──▶ ffmpeg: decode, gray 320×180 ──▶ recorder.py: motion?
                   └─ camN_hd ───────▶ ffmpeg: copy, fragmented MP4 ──▶ recorder.py: last few s in RAM,
                                                                          clip to disk on motion
recorder.py ──▶ ~/recordings/…  (clips + thumbnails)
            ├─▶ ~/.cache/drawer-server/recorder.json  (state per camera, read by the panel)
            └─▶ ~/.cache/drawer-server/recorder-stills/camN.jpg  (panel stills, see below)
panel.py    ──▶ Recordings section, 💾 split, warnings; reads the clips folder, the state file
                and the recorder's stills
```

- **Its own process** (my call): `recorder.py`, started on boot by `~/.termux/boot/70-recorder.sh`
  (pid file, "already running? exit", like the other boot scripts). Restarting the panel (step 8)
  must not cut a recording, and a recorder problem must not take the panel down.
- One Python process for all cameras; per camera, two ffmpeg children (motion, recording), each in
  its own process group, stopped with the group when the recorder stops (the panel once left 1921
  `termux-api` processes behind). An ffmpeg that dies (camera offline, go2rtc restarted by step 11)
  is restarted with a growing wait (10 s up to ~60 s); the camera shows as not recording meanwhile.
- ffmpeg reads from go2rtc's RTSP on `127.0.0.1`, like the stills, so no camera code is ever in a
  command line. Each camera keeps a single connection to go2rtc, shared with live view and stills.

### Recording: pre-roll in memory (my call)

The brief proposed rolling segments on disk (agreed). Measured, that writes 30–44 GB a day to flash
for three cameras, so the "last few seconds" live in memory instead and only clips reach the disk.
Same result for the owner (clips with seconds before), no constant writes.

- ffmpeg copies `camN_hd` as fragmented MP4 to its stdout (command above). The recorder reads
  top-level boxes (4-byte size + 4-byte type; handle 64-bit sizes), keeps `ftyp`+`moov` as the clip
  header, and keeps a ring of the latest fragments: enough that the oldest starts at least
  `RECORD_BEFORE` seconds before now, plus a byte limit as a safety net. A fragment is only complete
  when the next full frame arrives, so clips can only start and end at full frames: with ~4 s
  fragments, "5 s before" means 5 to 9 s in practice (docs say so).
- **Motion starts** → open `<clip>.part.mp4`, write header + ring, then append fragments as they come.
- **Motion keeps going** → keep appending. Clips are split at 5 minutes (my call, a named constant);
  the next clip continues from the next fragment, no gap.
- **Motion stops** → close at the first fragment boundary at least `RECORD_AFTER` seconds after the
  last motion. Then remux to a normal MP4 (`-c copy -tag:v hvc1 -movflags +faststart`, so browsers
  get the duration and can seek), make the thumbnail, delete the `.part`.
- **Power cut or crash mid-clip**: a fragmented `.part` is valid up to its last full fragment. On
  start, the recorder remuxes leftover `.part` files (or deletes ones that can't be read).
- RAM: ~2 MB of ring per camera (measured 2.15 MB for 4 fragments).

### Motion detection (my call, after measuring)

**No OpenCV.** It adds ~514 MB, an extra repository and a forced full upgrade, and costs more CPU
and RAM than the simple way while the decoding cost (the real cost) stays the same. Detection is
**frame differencing in plain Python**, standard library only, like the panel.

- The motion ffmpeg decodes `camN` (the small stream), scales to **320×180 gray**, writes raw frames
  to its stdout. Two speeds, a setting (`RECORD_CHECK`):
  - **fast**: decodes every frame and looks twice a second (`fps=2`), ~15% of a core per camera.
    Catches someone who crosses the view in a second or two.
  - **light**: looks only at full frames (`-skip_frame nokey`), ~4% per camera, once every ~4 s on
    these cameras. Can miss motion that starts and ends between two looks.
  - Default: **fast** (owner).
- Each look compares with the previous one: the share of pixels whose brightness changed by more
  than a threshold. Motion = that share above a minimum area. `RECORD_SENSITIVITY` (1–10, default 5)
  moves both: higher = smaller changes count. Default 5 starts at about 25 levels and 0.5% of the
  image, above the 0.28% measured at rest; the builder tunes with footage from the real cameras.
- **The comparison must cost ≤ 2% of a core per camera.** The naive Python loop measured 40 ms per
  320×180 look: fine for light, not for fast. Builder's choice how (e.g. ffmpeg computes the
  difference with `tblend=all_mode=difference` and Python thresholds with `bytes.translate` +
  `count`, both C-speed; or a smaller frame).
- **Light changes are not motion**: when most of the image changes at once (lights on, night
  vision switching, a cloud), treat it as a lighting change: no motion, start comparing from the new
  image. The builder sets "most" with real footage, keeping in mind someone walking right up to the
  lens also changes a lot of the image.
- Fast mode may ask for motion in two looks in a row before starting a clip, to skip one-frame noise
  (builder's call).

### Panel stills from the recorder (owner asked, my call to do it)

Without the recorder, the panel runs its own ffmpeg per camera for the stills while someone looks
(full frames only, ~4% of a core per camera). A wall tablet looks all day, so with the recorder on
that would decode each camera twice. Instead, **the motion ffmpeg also writes the still**:

- One ffmpeg per camera, two outputs from one decode (`-filter_complex` with `split`): the gray
  320×180 frames for detection, and a JPEG of each full frame (`select` on keyframes, same size and
  quality as today's stills, `-update 1 -atomic_writing 1`) into
  `~/.cache/drawer-server/recorder-stills/camN.jpg`. In light mode both outputs get the same frames.
- **Its own folder, not the panel's `cams/`**: on start the panel kills any ffmpeg writing into
  `cams/` (`kill_leftovers`), which would kill the recorder's.
- The panel's `Stills` serves the recorder's JPEG when it is fresh (same 15 s rule) and doesn't start
  its own ffmpeg for that camera. When it isn't (recorder off or down, camera not in `RECORD_CAMERAS`,
  ffmpeg restarting), the panel falls back to its own ffmpeg as today. The stills never stop because
  of the recorder.
- Saves ~4% of a core per recorded camera while the panel is open (~11% for three). The JPEG costs
  little (one 768×432 image every ~4 s); the builder checks it adds under 1% of a core.

### "Looks obstructed"

- **Moving all the time** (owner): motion in more than half of the looks of the last 10 minutes.
  Clears when it falls under a quarter for the same window (my call: a gap so it doesn't flicker).
- **Black or flat image** (agreed): almost no brightness spread (or almost black) for a minute.
  Clears after a minute of normal image. (A camera with no night vision in a dark room would
  trigger this every night; accepted, docs mention it.) Spread and mean come from a sample of the
  pixels, cheap.
- `RECORD_OBSTRUCTED` (owner): **keep** or **pause**: no new clips for that camera while obstructed;
  detection keeps running so it notices when the camera is back to normal. A clip in progress ends
  normally. The person installing chooses; the warning shows either way (owner). When the setting
  is empty: **keep** (my call: never miss footage; the cap protects the space).
- **Docs, next to `RECORD_OBSTRUCTED`** (owner, in `.env.example` and the docs): if a camera sees a
  plant, a flag or anything else that moves all the time, `pause` is the better choice; otherwise
  that camera fills the recordings share with useless clips and writes to the disk all day.
- **Worst case for the disk:** a camera that sees motion most of the time (with `keep`, or one that
  moves a lot without crossing the "half" line) joins its clips back to back: ~10–15 GB written a day
  for that camera. The cap bounds the space, not the writes. The remux writes each clip a second
  time; avoid that if practical (builder's call).
- Panel top line (owner): one text for both causes: "⚠️ Lateral looks obstructed, check it (still
  recording)" or "… (recording paused)". In Spanish too.
- A camera going offline resets its obstructed state.

### Clips on disk

- In **Termux's private storage**, `~/recordings/` (my call): other apps on the phone can't read it,
  unlike `/sdcard`. Reachable with SFTP; docs say how.
- One folder per camera and per day, local time, e.g. `~/recordings/<camera>/2026-10-31/`, with the
  clip (`.mp4`) and its thumbnail (`.jpg`, 320 px wide, taken where the motion started). The file
  name must let the panel list a day with hundreds of clips without opening each file (start time
  and length in the name or in one small index per day: builder's call). Camera folder names must be
  safe for any camera name (spaces, accents) and keep working if a camera is renamed: old clips stay
  listed under the old name and still count against the cap.
- **Cap** (agreed): total size of `~/recordings` ≤ the recordings share. Checked after each clip and
  every few minutes; at the cap it deletes the **oldest clips first, across all cameras**, clip and
  thumbnail together, and empty day folders.
- **Free-space floor** (my call): the recorder never lets the disk's free space drop under
  `DISK_KEEP_FREE_GB` (default 5). Below it: delete oldest clips; if none are left, start no new
  clips and say so in the top line ("Disk almost full: recording stopped").
- **Deleting is fenced** (anti-goal): only regular files inside `~/recordings` whose names match the
  recorder's own pattern; never follow symlinks; never anything else. Tests prove it.

### Recorder state for the panel

`~/.cache/drawer-server/recorder.json`, written atomically every ~10 s: time; per camera: name,
state (watching, recording, paused-obstructed, can't see the camera, off), obstructed cause, last
motion, clips today; total bytes of recordings; and "recording stopped: disk full" when it applies.
The panel treats the file as stale after ~1 minute (recorder down).

### Panel: Recordings section

- **🎞️ Recordings**, near the Cameras card, collapsed by default (my call; like Devices), with a
  one-line summary (clips today, space used). Nothing else loads until it's opened.
- Opened: pick a camera, then a day (newest first: today, yesterday, dates), then a grid of
  thumbnails with the start time and length. Tap → full-screen player like live view: the clip with
  normal video controls, ◀ ▶ to the previous/next clip, ✕ to close.
- If the browser can't play H.265 (the video errors), say so and offer a download link (my call).
- Shown when `PANEL_RECORDINGS` isn't `no` and the recorder is on or clips exist (my call: someone
  who turns recording on wants to see clips). `PANEL_RECORDINGS=no` applies to the whole server, for
  everyone: the section is hidden **and its routes answer 404** (my call: hiding the section while the
  clips stay reachable by address would be pointless). A per-device switch (e.g. only for a shared
  tablet) is not part of this.
- **Home only** (agreed): same checks as the camera routes (`is_home`, `same_site`). Away, the
  section says "home only" and the routes answer 403.
- Routes (builder's call on names): a list of cameras and days, a day's clips, and the files
  themselves. Video served in chunks with **HTTP Range** support (206): browsers need it to seek, and
  a 5-minute clip is ~45 MB. Paths validated strictly and resolved inside `~/recordings` only.
- Texts in `TEXT` for `en` and `es`. Look and layout follow the current panel (`docs/panel.md`),
  usable at 390 px wide.

### Panel: disk budget

- The 💾 card gets an expander with one row per kind that exists on this server, then what's free:
  `Photo backup 20 / 50 GB (40%) ▓▓░░`, `Recordings 3.1 / 10 GB (31%) ▓░░░`, `Free 49 GB` (agreed).
  A kind with no share shows only its size.
- Sizes: photo backup from Syncthing's API, which the panel already reads every 30 s (`localBytes` of
  each folder in `/rest/db/status`), so no slow disk scan; recordings from the recorder's state file.
- **Photo backup over 90% of its share** → top line, "photo backup near its limit" (agreed).
  At 100% and `DISK_BACKUP_PAUSE=yes`, the panel pauses the backup folders through Syncthing's API and
  resumes them under 95% or when the setting is turned off. It only resumes folders it paused itself
  (it remembers which), never ones a person paused. Never deletes anything.
- **Recordings at their cap: no warning** (my call; deleting the oldest is the plan, see anti-goals).
  The brief's "over 90% shows a warning" applies to kinds that are never deleted.
- Built as a list of kinds, each with how to measure it, its share and its rule (cap or warning), so
  adding movies later is one more entry (owner).

### Settings

`.env` → validated by the step script (clear error messages) → small `key=value` files under
`~/.config/drawer-server/` → re-read by the program when it uses them, and clamped to valid values
on read (the `PANEL_SPEEDTEST` pattern), so a future panel screen can write those files and nothing
else changes (owner). My call on names and defaults:

| `.env` | Default | What | Written by |
|---|---|---|---|
| `RECORDER` | empty = off | `yes` records motion clips | step 12 |
| `RECORD_CAMERAS` | all from step 11 | camera names, comma-separated (agreed) | step 12 |
| `RECORD_BEFORE` | 5 | seconds kept before the motion (agreed) | step 12 |
| `RECORD_AFTER` | 10 | seconds after the last motion (agreed) | step 12 |
| `RECORD_SENSITIVITY` | 5 | 1 (only big changes) to 10 (small ones) (agreed) | step 12 |
| `RECORD_CHECK` | `fast` (owner) | `fast` or `light`, see motion detection | step 12 |
| `RECORD_OBSTRUCTED` | `keep` | `keep` or `pause` (owner) | step 12 |
| `PANEL_RECORDINGS` | shown | `no` turns recordings off in the panel (agreed) | step 8 |
| `DISK_RECORDINGS_GB` | 10% of the disk | recordings cap (agreed) | step 8 |
| `DISK_BACKUP_GB` | none | photo backup share, a warning (agreed) | step 8 |
| `DISK_BACKUP_PAUSE` | no | `yes` pauses photo backup at its share (agreed) | step 8 |
| `DISK_KEEP_FREE_GB` | 5 | the recorder never goes below this much free | step 8 |

The recorder re-reads its file and the disk file every ~30 s: changes apply without a restart,
including which cameras record.

### Step 12: `scripts/12-recorder.sh`

- Needs step 11 (the camera names file and go2rtc running); otherwise stops with "run step 11 first".
- Without `RECORDER=yes`: if a recorder is installed, stops it and removes its boot script, keeping
  the clips (and says where they are and how to delete them); otherwise "Skipped". This also answers
  the reviewer's pending point that steps have no clean way to be turned off.
- With it: validate the settings (names in `RECORD_CAMERAS` must exist in `PANEL_CAMERAS`), write the
  settings file, copy `recorder.py`, install `70-recorder.sh`, restart the recorder, wait until its
  state file shows each camera watching, print a short summary, then re-run step 8 (as step 11 does)
  so the panel shows the new section and disk split.
- Safe to re-run. Panel and recorder code should not drift apart between deploys (builder's call how).

### CPU and RAM budget (three cameras, estimate from the measurements)

| | light | fast (default) |
|---|---|---|
| Motion | ~14% | ~48% |
| Recording (HD copy) | ~7% | ~7% |
| go2rtc relaying 6 streams around the clock | ~5–10% | ~5–10% |
| **Total, of one core** | **~25–30%** (3–4% of the phone) | **~60–65%** (~8% of the phone) |
| RAM | ~260 MB | ~260 MB |

Plus ~4–6 Mbit/s constantly over the server's Wi-Fi (its 2.4 GHz link is 78 Mbit/s). Tip for the
docs: lowering the sub stream's frame rate in the camera's own settings cuts the fast mode's cost.
With the panel open, the panel's own stills ffmpeg no longer runs for recorded cameras (see "Panel
stills from the recorder"), so the real total is a bit lower than this table plus today's stills.

**Heat** (owner): this load runs around the clock, so the phone stays warmer than with the other
services, more so in a closed drawer or while charging. It is measured on the real server (see
Tests), and the docs must mention it: watch the panel's 🌡️ card (it already warns in the top line at
40 °C), give the phone some air, and use `light` mode or fewer cameras if it runs hot.

### Where the code goes (my call)

`termux/panel/recorder.py` (deployed next to the panel; can reuse helpers from `cameras.py`),
`scripts/12-recorder.sh`, panel changes in `termux/panel/panel.py`, tests in
`tests/test_recorder.py` and `tests/test_panel_routes.py`, run with `bash tests/run-on-phone.sh`.

### Tests

Made-up frames and a short made-up video only (ffmpeg's test pattern); never real camera images.

- Box reader and ring: fragments kept, pre-roll covers `RECORD_BEFORE`, clip ends `RECORD_AFTER`
  after the last motion at a fragment boundary, 5-minute split, leftover `.part` recovery, pipe
  shutdown doesn't hang.
- Detection: still image → no motion; a moving square → motion; whole image brighter → lighting,
  not motion; sensitivity changes the outcome; flat/black → covered.
- Obstructed: turns on above half, off under a quarter, pause stops new clips but not detection.
- Cap and floor: oldest deleted first across cameras; files that aren't the recorder's (other names,
  symlinks, files outside the folder) are never touched.
- Settings: bad or missing values fall back to defaults.
- Stills: the panel serves the recorder's still when it is fresh and starts no ffmpeg for that
  camera; with a stale or missing one it falls back to its own ffmpeg; the panel's `kill_leftovers`
  doesn't match the recorder's ffmpeg.
- Panel: Recordings routes home-only and `same_site`, path tricks refused, Range answers 206 with the
  right bytes; disk rows and warnings from fake data; recordings at cap give no warning; Syncthing
  pause/resume only on folders the panel paused.
- On the real server: a clip appears after walking in front of a camera; CPU and RAM match the
  budget (`check-server`); the panel's stills keep coming with the recorder on, off and restarting.
- **Heat on the real server** (owner): with `fast` and the three cameras, read the phone's temperature
  (`termux-battery-status`, the same one the panel shows) every minute for about an hour, after a
  baseline reading with the recorder off, and report the curve. **Over 45 °C: tell the owner** (owner)
  and turn the recorder off then (my call; it goes off afterwards anyway).
- Then the recorder goes back off on the owner's server unless the owner says to keep it (owner: not
  using it now).

## Docs and tooling to update

`.env.example` (step 12 section, with the `pause` advice next to `RECORD_OBSTRUCTED`; disk budget
under step 8), `README.md` (steps table, what you need, "What's next"), `docs/path-a.md` (step 12,
including heat and the `pause` advice), `docs/panel.md` (Recordings section, disk budget, how they
work, stills from the recorder), `docs/services.md` (the Camera recorder row with the measured
CPU/RAM and temperature; "How many at once"),
`AGENTS.md` (topic table row; steps 9–12 not in `setup.sh`; step 12 needs step 11),
`.claude/skills/check-server` (recorder alive, obstructed cameras, disk split), `docs/img/panel.jpg`
if the page changes visibly (fake data). Run the `path-a-reviewer` agent before committing.

## Left to the builder

- How the comparison stays under 2% of a core in fast mode; detection resolution if 320×180 proves
  wrong; exact thresholds behind each sensitivity step and the lighting-change rule, tuned on real
  footage kept out of the repo.
- File naming inside a day folder, camera folder naming, the index (if any).
- Route names, JSON shapes, the state file's exact fields, panel layout details.
- Restart waits, timeouts, ring byte limit, how often the cap is checked.
- Whether the recorder or step 11 notices a changed camera list.
- The exact two-output ffmpeg command (filter graph, keyframe `select`), and how the panel learns
  which stills the recorder covers (file age alone, or also the state file).
- Log file and its size limit (`~/.cache/drawer-server/recorder.log`, nothing secret in it).
