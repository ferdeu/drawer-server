# Delete Recordings from the Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In the clip player, a Delete button that asks "Are you sure?". Next to the chosen day, a "Delete the whole day" link per camera that says how many clips and GB will go and asks twice.

**Architecture:** `ClipStore` (termux/panel/clips.py) gets two deleting methods. Both go through its one fenced `_remove`, so only the recorder's own clip and thumbnail names inside `~/recordings` can be touched. `panel.py` answers `DELETE` on the existing clip and day URLs, with the same home-only and same-site checks as the other recording routes. The page adds the buttons and uses the browser's own `confirm()`.

**Tech Stack:** Python 3 standard library, vanilla JS, unittest on the phone.

**Spec:** this changes an anti-goal of `docs/superpowers/specs/2026-10-31-recorder-design.md` ("Deleting clips … from the panel"). Owner's decision on 2026-11-03: anyone at home may delete, after a confirmation, with no setting and no PIN.

## Global Constraints

- Deleting only ever goes through `ClipStore._remove`, so: names matching `CLIP`/`THUMB`, real (not symlinked) folders, regular files. A `.part.mp4` or `.remux.mp4` is never deleted from the panel, because it may be the recording in progress.
- `DELETE` requests: 404 when recordings are hidden (`recordings_shown()` false). 403 when not home or not same-site (the same checks as `GET`). 404 when the clip or day doesn't exist or doesn't match the patterns.
- An answer is `{"clips": int, "bytes": int}` with what was actually removed.
- Empty day and camera folders are removed afterwards (`_rmdir`).
- The texts go in both `en` and `es`. Repo text is in English.

## Review Focus

1. **Deleting the clip being recorded today.** Its `.part` file is never touched, and the whole-day delete leaves it alone. Pinned by `test_delete_day_keeps_part`.
2. **Path tricks in a DELETE URL** (`..`, encoded `/`, symlinked folders). They must give 404 and delete nothing. Pinned by `test_delete_path_tricks`.
3. **Another website sending DELETE.** The browser would need a preflight, which we never answer, and `same_site` rejects a foreign `Origin` anyway. Pinned by `test_delete_other_site`.
4. **The recorder trims the same clip at the same moment.** `_remove` treats "already gone" as done, so there's no error.
5. **The last clip of the day deleted from the player.** The player closes and the list reloads, and today's day pick disappears if it is now empty. Checked in the browser.

---

### Task 1: ClipStore deletes a clip or a day

**Files:** Modify `termux/panel/clips.py`. Test: `tests/test_clips.py`.

**Produces:**
- `ClipStore.clips(folder, day)` rows gain `"bytes"` (the clip plus its thumbnail).
- `ClipStore.delete_clip(folder, day, name) -> dict`: removes the clip and its `.jpg`, and returns `{"clips": 0|1, "bytes": n}`. `name` must match `CLIP`.
- `ClipStore.delete_day(folder, day) -> dict`: removes every `CLIP` and `THUMB` file of that day, leaves `PART`/`REMUX` files, and returns the totals.

- [ ] Write failing tests: `test_delete_clip` (clip and thumb gone, the other clip stays, the result counts the bytes), `test_delete_clip_not_a_clip` (a `.part.mp4`, `x.txt` or `../` name → nothing deleted, `{"clips": 0, "bytes": 0}`), `test_delete_day_keeps_part` (the clips go, the `.part.mp4` stays, and the day folder stays because it isn't empty), `test_delete_day_removes_empty_folders`, and `test_delete_through_symlinked_day_refused`. Update `test_clips_listing` for `"bytes"`.
- [ ] Run `bash tests/run-on-phone.sh -k ClipStoreTest` (or the test class name in that file) → FAIL.
- [ ] Implement.
- [ ] Run again → OK. Commit.

### Task 2: DELETE routes

**Files:** Modify `termux/panel/panel.py` (the `Handler`). Test: `tests/test_panel_routes.py` (`RecordingsTest`).

**Produces:** `DELETE /rec/<folder>/<day>/<clip>.mp4` and `DELETE /api/recordings/<folder>/<day>`.

- [ ] Write failing tests:
  - `test_delete_clip_route`: 200 with `{"clips": 1, "bytes": 1005}`, then GET of the clip → 404.
  - `test_delete_day_route`.
  - `test_delete_away`: `is_home` false → 403 and the file stays.
  - `test_delete_other_site`: `Origin: http://evil.example` → 403.
  - `test_delete_hidden`: recordings hidden → 404.
  - `test_delete_path_tricks`: `%2e%2e`, `%2F` and a thumbnail name on the clip route → 404, nothing deleted.
  - Update `test_list_and_day` for `"bytes"`.
- [ ] Run → FAIL. Implement `do_DELETE` by sharing the checks with `recordings()`. Run → OK. Commit.

### Task 3: Buttons, texts, docs

**Files:** `termux/panel/panel.py` (`TEXT`, `PAGE`, JS), `docs/panel.md` (Recordings row), the spec's anti-goal line.

- Player top bar: a `🗑️` button (`id="clip_del"`, `aria-label` = `T.rec_delete`). `confirm(T.rec_del_one)`, then `DELETE`. On success the clip leaves `recClips`: if it was the last one, the player closes; otherwise the player opens the clip now at the same position. Then the camera and day list reloads.
- Under the day picks: `button.link` `🗑️ T.rec_del_day`. First `confirm(T.rec_del_day_q)` with `{n}` clips, `{gb}` GB (the sum of `bytes`), `{cam}` and `{day}`, then `confirm(T.rec_del_sure)`. After that, the list reloads.
- If something fails, it alerts `T.rec_del_fail`.
- Texts:
  - `rec_delete`: "Delete" / "Borrar"
  - `rec_del_one`: "Delete this clip? It can't be undone." / "¿Borrar este clip? No se puede deshacer."
  - `rec_del_day`: "Delete the whole day" / "Borrar todo el día"
  - `rec_del_day_q`: "Delete the {n} clips ({gb} GB) from {cam}, {day}?" / "¿Borrar los {n} clips ({gb} GB) de {cam} del {day}?"
  - `rec_del_sure`: "It can't be undone. Delete them anyway?" / "No se puede deshacer. ¿Borrar igual?"
  - `rec_del_fail`: "Couldn't delete it." / "No se pudo borrar."
- [ ] Implement. Check it with `node --check`, deploy, and try it in the browser on a test clip. Docs. Run the full suite on the phone, `path-a-reviewer`, commit.
