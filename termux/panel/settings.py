"""Settings files for the recorder and the disk budget: key=value lines, re-read often, clamped on read.
Used by panel.py and recorder.py (deployed side by side).
"""
import re
from dataclasses import dataclass
from pathlib import Path

GB = 1_000_000_000  # the panel already counts GB as 10^9 bytes


def read_kv(path):
    """key=value lines, both sides stripped. Blank, # and malformed lines are skipped; no file gives {}."""
    out = {}
    try:
        text = Path(path).read_text(errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key:
            out[key] = value.strip()
    return out


def _whole(kv, key, default, low, high):
    """A whole number (digits only) clamped to low..high; anything else is the default, clamped too."""
    raw = kv.get(key, "").strip()
    n = int(raw) if re.fullmatch(r"[0-9]+", raw) else default
    return max(low, min(high, n))


def _choice(kv, key, allowed, default):
    value = kv.get(key, "").strip().lower()
    return value if value in allowed else default


def _gb(kv, key):
    """GB with optional decimals as bytes, or None when missing or not a plain number."""
    raw = kv.get(key, "").strip()
    if not re.fullmatch(r"[0-9]+(\.[0-9]+)?", raw):
        return None
    return int(round(float(raw) * GB))


@dataclass(frozen=True)
class RecorderSettings:
    cameras: tuple
    before_s: int
    after_s: int
    sensitivity: int
    check: str
    obstructed: str


def recorder_settings(kv, all_cameras):
    raw = kv.get("cameras", "").strip()
    if raw:
        wanted = {name.strip() for name in raw.split(",")}
        cameras = tuple(c for c in all_cameras if c in wanted)  # step 11 order, unknown names dropped
    else:
        cameras = tuple(all_cameras)
    return RecorderSettings(
        cameras=cameras,
        before_s=_whole(kv, "before", 5, 0, 30),
        after_s=_whole(kv, "after", 10, 2, 60),
        sensitivity=_whole(kv, "sensitivity", 5, 1, 10),
        check=_choice(kv, "check", ("fast", "light"), "fast"),
        obstructed=_choice(kv, "obstructed", ("keep", "pause"), "keep"),
    )


@dataclass(frozen=True)
class DiskSettings:
    recordings_bytes: int
    backup_bytes: "int | None"
    backup_pause: bool
    keep_free_bytes: int


def disk_settings(kv, total_bytes):
    rec = _gb(kv, "recordings_gb")
    if rec is None:
        rec = total_bytes // 10
    keep = _gb(kv, "keep_free_gb")
    if keep is None:
        keep = 5 * GB
    return DiskSettings(
        recordings_bytes=max(GB, min(total_bytes, rec)),
        backup_bytes=_gb(kv, "backup_gb"),
        backup_pause=kv.get("backup_pause", "").strip().lower() == "yes",
        keep_free_bytes=max(GB, keep),
    )


def shows_recordings(kv):
    return kv.get("show", "").strip().lower() != "no"
