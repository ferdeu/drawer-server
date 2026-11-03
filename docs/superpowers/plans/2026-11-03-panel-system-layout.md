# Panel: CPU, Power and Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Server section shows how hard the phone works (CPU, load, each of our services, watts) and its Wi-Fi, every section folds from its heading, and the page uses the width of big screens.

**Architecture:** A new module `termux/panel/system.py` reads what Android 15 still lets Termux read (cpufreq, the `sysinfo()` syscall, our own `/proc/<pid>`), and a background thread samples it so `/api/status` stays fast. `panel.py` adds a `system` block to the status and fixes `uptime_h`. The page gets a CPU card, the old Connection card becomes a small Wi-Fi card inside the Server grid, every section gets a foldable heading, and the CSS gets a wide layout.

**Tech Stack:** Python 3 standard library (Termux) with `ctypes` for `sysinfo()`, vanilla JS/CSS in `PAGE`, unittest run on the phone.

**Spec:** none written separately. The requirements below come from Fer's request on 2026-11-03, and the readability probes were run on the Edge 40 that day.

## What Android 15 lets Termux read (measured on the Edge 40)

| Wanted | Source | Readable |
|---|---|---|
| Whole-phone CPU % | `/proc/stat` | **no** (permission denied) |
| Load average, uptime | `/proc/loadavg`, `/proc/uptime`; Python's `os.getloadavg` doesn't exist in Termux | **no**, but the `sysinfo()` syscall works through ctypes (it gave uptime 124909 s and load 14.7) |
| CPU speed per cluster | `/sys/devices/system/cpu/cpufreq/policy*/scaling_cur_freq`, `cpuinfo_max_freq`, `related_cpus` | yes (policies 0, 4, 7 = cores 0-3, 4-6, 7) |
| Our processes' CPU and RAM | `/proc/<pid>/stat`, `/proc/<pid>/status`, `/proc/<pid>/cmdline` for our uid | yes |
| CPU temperature, network totals | `/sys/class/thermal`, `/proc/net/dev` | **no** (would need root) |
| Battery voltage and current | `termux-battery-status` (`voltage` mV, `current` µA, negative while discharging) | yes, already read |

The current panel reads `/proc/uptime`, which this phone refuses, so "on for" is blank in the screenshot from 2026-11-03.

## Global Constraints

- Standard library only, as in the rest of `termux/panel/`. No new packages on the phone.
- All repo text in English. Every new page string goes into both `TEXT["en"]` and `TEXT["es"]`.
- The CPU figure is a *speed* figure (current clock ÷ max clock, weighted by cores per cluster). It is labelled "how hard it's working" / "qué tan exigido", never "usage", and the CPU card's details say so in one sentence.
- Per-service CPU % is a share of the **whole phone** (all cores = 100%), so it adds up with the bar and doesn't read like `top`'s 800%.
- Sampling runs in one background thread every `CPU_SAMPLE_S = 2` s, averaged over the last `CPU_WINDOW = 5` samples. `/api/status` only reads the cached result.
- Load words go by load ÷ cores: below 1 = calm (`tranquilo`), below 2 = busy (`ocupado`), 2 or more = very busy (`muy ocupado`). Constants `LOAD_BUSY = 1.0` and `LOAD_VERY = 2.0` live in `system.py`.
- Folded/unfolded sections are remembered per browser in `localStorage` key `shut` (a list of section keys). Everything starts unfolded. Wrap every storage access in try/catch, like the existing `open` set.
- A folded section still feeds the top "Everything works" / problems line. Folding never hides a problem.
- A folded Cameras section makes no still requests.
- Layout: `main` keeps `max-width:760px` below 900 px and widens to `max-width:1180px` from 900 px. No horizontal scroll at 360 px.
- Path A rules hold: nothing here roots, unlocks or erases anything.
- Another session is changing `panel.py` and `tests/` for step 12 (recorder). **Don't start until that work is committed.** Never run `tests/run-on-phone.sh` while the other session runs it, because both wipe `~/drawer-tests`.

## Review Focus

1. **A phone that reports battery current in mA, not µA.** Watts would come out 1000× too small. `battery_watts` treats `|current| < 10000` as mA. Pinned by `test_watts_milliamps` (Task 1). **Dropped during the build:** that guess read a phone holding its charge (~3000 µA) as 12 W. The current is always µA (Android's unit), and under 0.05 W shows nothing; see `test_watts_small_current_is_microamps`.
2. **A cpufreq policy that disappears or can't be read** (a cluster hot-unplugged, or a different phone). The figure averages the readable policies and returns `None` only if none can be read. Pinned by `test_cpu_pct_missing_policy` (Task 1).
3. **A process that exits between listing `/proc` and reading its `stat`.** It's skipped, never crashes the sampler. A pid reused between samples doesn't produce a negative %. Pinned by `test_proc_vanishes` and `test_pid_reused` (Task 2).
4. **Helper processes** (ffmpeg under the recorder, the shell under a boot script, proot under Luanti) get counted under their parent's service instead of piling up in "Other". Pinned by `test_child_inherits_service` (Task 2). On the phone, check that "Other" stays small (Task 7).
5. **Folding Cameras, then reloading the page.** It must stay folded and fetch no stills. Checked in the browser's network list (Task 5).

---

### Task 1: System readers (`system.py`)

**Files:**
- Create: `termux/panel/system.py`
- Test: `tests/test_system.py`

**Interfaces:**
- Produces:
  - `sysinfo() -> dict | None`: `{"uptime_s": int, "load": [float, float, float]}`, from libc `sysinfo()` via ctypes (struct starts with `long uptime; unsigned long loads[3]`, loads scaled by 65536). Returns `None` if the call fails.
  - `cpu_pct(root: Path = Path("/sys/devices/system/cpu/cpufreq")) -> int | None`: the average over `policy*` of `scaling_cur_freq / cpuinfo_max_freq`, each weighted by how many cores `related_cpus` lists, rounded to 0..100.
  - `load_word(load1: float, ncpu: int) -> str`: `"calm" | "busy" | "very_busy"`.
  - `battery_watts(b: dict) -> float | None`: `abs(voltage_mV/1000 × current_A)` rounded to 1 decimal. Current is in µA unless `abs(current) < 10000` (then mA) (superseded: always µA, None under 0.05 W). Uses `current_average`, falling back to `current`. `None` if either value is missing or zero.

- [ ] **Step 1: Write the failing tests** in `tests/test_system.py` (same header and `sys.path` line as `tests/test_settings.py`):

```python
class SystemTest(unittest.TestCase):
    def policy(self, root, name, cur, top, cpus):  # helper: writes the three files
        ...
    def test_cpu_pct_weighted(self):  # policy0 4 cores 1.0/2.0 GHz, policy4 3 cores 2.6/2.6, policy7 1 core 0.65/2.6
        self.assertEqual(system.cpu_pct(root), 66)  # (4*50 + 3*100 + 1*25) / 8 = 65.6
    def test_cpu_pct_missing_policy(self):  # policy7 has no scaling_cur_freq -> (4*50 + 3*100) / 7 = 71.4 -> 71
    def test_cpu_pct_none(self):  # empty dir -> None
    def test_load_word(self):
        self.assertEqual(system.load_word(7.9, 8), "calm")
        self.assertEqual(system.load_word(8.0, 8), "busy")
        self.assertEqual(system.load_word(16.0, 8), "very_busy")
    def test_watts_microamps(self):
        self.assertEqual(system.battery_watts({"voltage": 3847, "current_average": -78000}), 0.3)
    def test_watts_milliamps(self):
        self.assertEqual(system.battery_watts({"voltage": 4200, "current": 2500}), 10.5)
    def test_watts_missing(self):
        self.assertIsNone(system.battery_watts({}))
    def test_sysinfo_shape(self):  # runs for real on the phone
        s = system.sysinfo()
        self.assertGreater(s["uptime_s"], 0); self.assertEqual(len(s["load"]), 3)
```

- [ ] **Step 2: Run and see them fail.** `bash tests/run-on-phone.sh -k SystemTest`. Expected: `ModuleNotFoundError: No module named 'system'`.
- [ ] **Step 3: Implement the four functions** in `termux/panel/system.py`, with a module docstring saying what Android blocks and why these sources (the table above, in two lines).
- [ ] **Step 4: Run again.** `bash tests/run-on-phone.sh -k SystemTest`. Expected: `OK`.
- [ ] **Step 5: Commit.** `git add termux/panel/system.py tests/test_system.py && git commit -m "Panel: read CPU speed, load, uptime and battery watts where Android 15 allows"`

### Task 2: Our services' CPU and RAM, and the sampler

**Files:**
- Modify: `termux/panel/system.py`
- Test: `tests/test_system.py`

**Interfaces:**
- Consumes: `cpu_pct()` from Task 1.
- Produces:
  - `SERVICE_RULES`: ordered `(needle, service)` pairs matched against `comm` and then `cmdline`: `("panel.py", "Panel")`, `("recorder.py", "Recorder")`, `("go2rtc", "Cameras")`, `("syncthing", "Syncthing")`, `("luanti", "Luanti")`, `("sshd", "SSH")`, `("nextdns", "NextDNS")`. Service names match the panel's `svc` keys, plus a new `"Panel"`.
  - `proc_table(proc: Path = Path("/proc")) -> dict[int, tuple[int, str, int, int]]`: pid → `(ppid, service_or_"", cpu_ticks, rss_kb)`. Ticks are utime+stime (fields 14 and 15 of `stat`, counted after the `)` of the name). RSS is `VmRSS` from `status`. Unreadable pids are skipped.
  - `by_service(table) -> dict[str, tuple[int, int]]`: service → `(ticks, rss_kb)`. A pid without a rule takes its nearest ancestor's service, else `"Other"`.
  - `usage(before, after, seconds: float, ncpu: int, hz: int = 100) -> list[dict]`: `[{"name": str, "cpu_pct": float, "mem_mb": int}]`, sorted by cpu_pct and then mem. `cpu_pct = max(0, Δticks) / (hz × seconds × ncpu) × 100`, rounded to 1 decimal. `before`/`after` are `proc_table` results. A pid's Δ only counts when the pid is in both and its ticks didn't go down (otherwise the pid was reused, so count it as 0).
  - `class Sampler(threading.Thread)`: daemon. Every `CPU_SAMPLE_S` it records `cpu_pct()` (keeps the last `CPU_WINDOW`) and a `proc_table()`. `snapshot() -> dict` returns `{"cpu_pct": int|None, "services": list, "ncpu": int}`, with services from the oldest and newest table in the window.

- [ ] **Step 1: Write the failing tests.** A fake `/proc` in a temp dir with `stat`, `status` and `cmdline` per pid:
  - `test_child_inherits_service`: pid 10 `recorder.py` (parent 1), pid 11 `ffmpeg` (parent 10), pid 12 `sleep` (parent 1). `by_service` gives `Recorder` = ticks of 10+11 and `Other` = ticks of 12.
  - `test_usage_share_of_phone`: 8 cores, 2 s, Δticks 160 at hz 100. Expected `cpu_pct == 10.0`.
  - `test_proc_vanishes`: a pid dir with `cmdline` but no `stat` gets skipped, with no exception.
  - `test_pid_reused`: the same pid with fewer ticks in `after` counts as 0, never negative.
  - `test_name_with_spaces`: a `stat` whose name is `(my proc) x` still parses ticks correctly.
- [ ] **Step 2: Run and see them fail.** `bash tests/run-on-phone.sh -k SystemTest`.
- [ ] **Step 3: Implement** `SERVICE_RULES`, `proc_table`, `by_service`, `usage` and `Sampler`. `ncpu` is `os.cpu_count()`.
- [ ] **Step 4: Run again.** Expected: `OK`.
- [ ] **Step 5: Commit.** `git commit -m "Panel: CPU and RAM per service from our own processes"`

### Task 3: Status API wiring and the uptime fix

**Files:**
- Modify: `termux/panel/panel.py` (`uptime_hours` ~L257, `status` ~L694, the startup code that starts the readers' threads)
- Test: `tests/test_panel_routes.py`

**Interfaces:**
- Consumes: `system.sysinfo`, `system.Sampler`, `system.battery_watts`, `system.load_word`.
- Produces: `/api/status` gains
  `"system": {"cpu_pct": int|None, "load": float|None, "load_word": str|None, "ncpu": int, "services": [...], "watts": float|None}`.
  `uptime_h` comes from `sysinfo()["uptime_s"]`, and from `/proc/uptime` only if `sysinfo()` is `None`.

- [ ] **Step 1: Write the failing test.** In `RoutesTest`, add `test_status_system`: GET `/api/status` and assert that `"system"` exists, its `ncpu >= 1`, `uptime_h` is not `None` (this fails today on the Edge 40), and that `services` is a list.
- [ ] **Step 2: Run it.** `bash tests/run-on-phone.sh -k test_status_system`. Expected: FAIL (`KeyError: 'system'`).
- [ ] **Step 3: Implement.** Make the `Sampler` a module-level `SAMPLER`, started where the other background threads start. Add a `system_status()` helper next to `status()` that builds the dict from `SAMPLER.snapshot()`, `sysinfo()` and `battery_watts(_battery)`.
- [ ] **Step 4: Run all panel tests.** `bash tests/run-on-phone.sh -k RoutesTest`. Expected: `OK`.
- [ ] **Step 5: Commit.** `git commit -m "Panel: system block in the status; uptime works on Android 15"`

### Task 4: Server section (CPU card, watts, Wi-Fi card)

**Files:**
- Modify: `termux/panel/panel.py` (`TEXT` en/es, `PAGE` Server grid ~L938-954, `refresh()`, `drawConnection` ~L1398)

**Interfaces:**
- Consumes: `s.system` from Task 3.
- Produces: element ids `cpu`, `cpusub`, `cpu_det`, `cpu_more`, `wf` (the Wi-Fi card), `wf_list`. The id `cn` disappears.

Layout of the Server grid, in this order: Battery · Temperature · CPU · Free memory · Free storage · Wi-Fi, then the 24 h chart (wide, as now), then Services (wide, as now).

- [ ] **Step 1: Texts.** Add these keys to `en` and `es`:
  - `cpu`: "Processor" / "Procesador"
  - `cpu_sub`: "working at {p}%" / "exigido al {p}%"
  - `calm` / `busy` / `very_busy`: "calm" / "busy" / "very busy", and "tranquilo" / "ocupado" / "muy ocupado"
  - `load`: "load {l} on {n} cores" / "carga {l} en {n} núcleos"
  - `cpu_note`: "Android doesn't let apps see the processor's real use; this is how fast it's running compared with its top speed." / "Android no deja ver el uso real del procesador; esto es qué tan rápido va comparado con su máximo."
  - `svc_other`: "Other" / "Otros"
  - `uses_w`: "using {w} W" / "usa {w} W"
  - `charges_w`: "charging at {w} W" / "carga a {w} W"
  - `svc.Panel`: "Panel" / "Panel"

  Rename `connection` to "Wi-Fi" / "WiFi" (reuse the existing `wifi` key and drop `connection`).
- [ ] **Step 2: CPU card.** `.big` = `cpu_pct + '%'`, colored WARN from 80 and BAD from 95. `.sub` = the load word. A `.bar` under the number. `details data-k="cpu" id="cpu_det"` holds one row per service: name (from `T.svc`, else `T.svc_other`), `cpu_pct %`, `mem_mb MB`, plus a bar. Then the load row, then `cpu_note`. Add a CSS rule like the existing `disk_det` one so the open card spans the full row.
- [ ] **Step 3: Watts.** Add to the battery card's `#plug` line: `T.charges_w` while charging, otherwise `T.uses_w`, when `s.system.watts` isn't null. Keep the smart-plug text after it.
- [ ] **Step 4: Wi-Fi card.** Change `drawConnection` to fill `wf_list` in a normal (not wide) grid card `wf`, with the same two rows (server, plug) and `show('wf', rows.length)`.
- [ ] **Step 5: Check in the browser.** Deploy with `bash scripts/08-panel.sh`. Open `http://<server-ip>:8080` with chrome-devtools at 390 px and 1280 px: the six cards are present, the CPU details open, the numbers move between refreshes, and "on for X h" shows next to the Server heading.
- [ ] **Step 6: Commit.** `git commit -m "Panel: CPU card, watts and Wi-Fi inside the Server section"`

### Task 5: Every section folds from its heading

**Files:**
- Modify: `termux/panel/panel.py` (`PAGE` markup and CSS, JS fold helpers, `drawCameras`)

**Interfaces:**
- Produces: a section is `<section class="… sec" data-s="KEY">` whose first child is `<div class="sec-h">` holding the icon and title, a `<span class="sub right" id="KEY_sum">` and the chevron. Keys: `net`, `cams`, `pp`, `bk`, `srv`, `dv`. JS: `shut` (a Set), `fold(key, on)`, `isShut(key)`.

Decisions:
- Internet, Cameras, Who's home, Photo backup and Devices: their current `.label` line becomes the `.sec-h`.
- Server: wrap the `h2` and the `.grid` in `<section class="sec" data-s="srv">`. The `h2` becomes its `.sec-h`, and "on for X h" moves into `srv_sum`.
- Printer and Recordings already fold as one `details`. Leave them as they are, but give their summary the same font and size as `.sec-h` so all headings look alike.
- CSS: `.sec.shut > :not(.sec-h) { display:none }`. The chevron is `›`, rotated 90° when open, same as `summary::after`. The whole `.sec-h` row is the tap target (`cursor:pointer`, `role="button"`, `aria-expanded`, toggles with Enter/Space).
- The summary shows only while folded:
  - net: `19 ms · ⬇ 193 Mbps`
  - cams: number of cameras
  - pp: the `n_of`-style "{a} of {b} home" (new key `n_home`: "{a} of {b} home" / "{a} de {b} en casa")
  - bk: "up to date ✓" or the lowest %
  - srv: `47% · 23,0°C · CPU 35%`
  - dv: the existing `n_of`
- `drawCameras` doesn't touch the still `img` sources while `cams` is folded. When you unfold it, the stills reload at once.

- [ ] **Step 1: Implement** the markup, CSS and JS above.
- [ ] **Step 2: Check in the browser.** Deploy, then fold each section and reload: each stays folded and shows its summary. Fold Cameras, then run chrome-devtools `list_network_requests` for 10 s: there must be no `/api/camera/` requests. Unfold it: stills appear within one refresh. Keyboard: Tab to a heading and press Enter to toggle it.
- [ ] **Step 3: Commit.** `git commit -m "Panel: every section folds from its heading and remembers it"`

### Task 6: Responsive layout

**Files:**
- Modify: `termux/panel/panel.py` (`PAGE` CSS and the Internet markup ~L904-916)

Decisions:
- `main`: `max-width:760px` by default, and `@media (min-width:900px) { main { max-width:1180px } }`.
- Internet card, from about 7 rows down to 2-3: one `.stats` row holds latency, ⬇ now, ⬆ now, a thin vertical divider (hidden when it wraps), ⬇ top and ⬆ top. Under it, one line holds "speed test 2 h ago · Test now · Details ›". Drop the `margin-top:12px` block. At 390 px it wraps to two rows of numbers.
- From 900 px, Who's home and Photo backup sit side by side. Wrap them in `<div class="pair">` with `display:grid; grid-template-columns:1fr 1fr; gap:12px`, and one column below 900 px. If only one of them is visible it takes the full width (`.pair > .hidden + section, .pair > section:only-of-type` → `grid-column:1/-1`, or set it from JS when one is hidden).
- The Server grid keeps `auto-fit, minmax(150px,1fr)`. At 1180 px that puts all six cards in one row.
- Cameras keep `auto-fit` (three in a row on wide screens, as now).

- [ ] **Step 1: Implement.**
- [ ] **Step 2: Check in the browser** at 360, 390, 768, 1024 and 1440 px with chrome-devtools `resize_page` plus `take_screenshot`: no horizontal scroll, Internet is at most 3 rows tall from 768 px, Who's home and Photo backup are side by side from 900 px, and the six Server cards sit in one row at 1440 px. Run the check in dark and light mode.
- [ ] **Step 3: Commit.** `git commit -m "Panel: compact Internet card and a wide layout for big screens"`

### Task 7: Docs, deploy, final check

**Files:**
- Modify: `docs/panel.md` (new CPU card, watts, Wi-Fi card, folding, wide layout, and the "Android doesn't allow the real CPU %" note), `docs/img/panel.jpg`, `AGENTS.md` (`system.py` in the panel row of the table), `README.md` if it lists the cards.

- [ ] **Step 1: Write the docs.** Plain words, for beginners.
- [ ] **Step 2: Redo the screenshot** with made-up data, as in PROGRESO: serve `panel.py` on the PC with `LANG en` and the title "Our house", and capture it with chrome-devtools at 390 px.
- [ ] **Step 3: Deploy and check.** Run `bash scripts/08-panel.sh` and the `check-server` skill. On the real panel, open the CPU details: the "Other" row must be under a few %. If it isn't, list `ps -e -o pid,ppid,args` and add the missing rule to `SERVICE_RULES` (with a test in Task 2's style).
- [ ] **Step 4: Run all tests** with `bash tests/run-on-phone.sh`. Expected: `OK`.
- [ ] **Step 5: Run the `path-a-reviewer` agent**, then commit with Fer's OK. Never commit `.env`, `PROGRESO.md` or `local/`. Push only if Fer asks.
