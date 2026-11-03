"""Clip storage for the camera recorder: <root>/<camera folder>/<YYYY-MM-DD>/<HHMMSS>-<len>.mp4 (+ .jpg).
This is the only module that deletes files, and only the recorder's own: regular files whose name matches
a pattern below, at exactly <root>/<folder>/<day>/<name>, with no symlink on the way. Never a photo.
"""
import hashlib
import os
import re
import stat
import time
import urllib.parse
from pathlib import Path

FOLDER = re.compile(r"[A-Za-z0-9_~%-]{1,200}")
DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
CLIP = re.compile(r"(\d{6})-(\d{1,5})\.mp4")
THUMB = re.compile(r"(\d{6})-(\d{1,5})\.jpg")
PART = re.compile(r"(\d{6})\.part\.mp4")
REMUX = re.compile(r"(\d{6})\.remux\.mp4")
OURS = (CLIP, THUMB, PART, REMUX)


def folder_for(camera):
    """Camera name -> a folder name that is safe on disk and always matches FOLDER.
    '.' is escaped too, so '..' can't happen. Empty or very long names are cut at a %XX boundary
    and get ~ plus 8 hex of a hash, so different names stay apart.
    """
    quoted = urllib.parse.quote(camera, safe="").replace(".", "%2E")
    if quoted and len(quoted) <= 200:
        return quoted
    kept = ""
    for tok in re.findall(r"%[0-9A-Fa-f]{2}|.", quoted):
        if len(kept) + len(tok) > 190:
            break
        kept += tok
    return kept + "~" + hashlib.sha1(camera.encode()).hexdigest()[:8]


def camera_for(folder):
    return urllib.parse.unquote(folder)


def _is_dir(path):
    try:
        return stat.S_ISDIR(os.lstat(path).st_mode)
    except OSError:
        return False


def _is_file(path):
    try:
        return stat.S_ISREG(os.lstat(path).st_mode)
    except OSError:
        return False


def _entries(path):
    """DirEntry list of a real directory (not a symlink to one); [] if it can't be read."""
    if not _is_dir(path):
        return []
    try:
        with os.scandir(path) as it:
            return list(it)
    except OSError:
        return []


class ClipStore:
    def __init__(self, root):
        self.root = Path(root)

    # --- walking the fenced layout ---

    def _folders(self):
        return sorted(e.name for e in _entries(self.root)
                      if FOLDER.fullmatch(e.name) and e.is_dir(follow_symlinks=False))

    def _days(self, folder):
        """Day names under a camera folder: real directories matching DAY."""
        if not FOLDER.fullmatch(folder):
            return []
        return sorted(e.name for e in _entries(self.root / folder)
                      if DAY.fullmatch(e.name) and e.is_dir(follow_symlinks=False))

    def _files(self, folder, day, patterns):
        """[(name, match, size)] of regular files in <root>/<folder>/<day> matching one of the patterns."""
        if not (FOLDER.fullmatch(folder) and DAY.fullmatch(day)):
            return []
        if not _is_dir(self.root / folder):
            return []
        out = []
        for e in _entries(self.root / folder / day):
            for pat in patterns:
                m = pat.fullmatch(e.name)
                if m:
                    try:
                        st = e.stat(follow_symlinks=False)
                    except OSError:
                        break
                    if stat.S_ISREG(st.st_mode):
                        out.append((e.name, m, st.st_size))
                    break
        return out

    def _walk(self, patterns):
        """[(folder, day, name, match, size)] over everything the recorder owns."""
        out = []
        for folder in self._folders():
            for day in self._days(folder):
                out += [(folder, day, n, m, s) for n, m, s in self._files(folder, day, patterns)]
        return out

    # --- writing side ---

    def new_part(self, camera, start):
        """Path for a new part file, named after the start second (the next free second if taken)."""
        folder = folder_for(camera)
        t = int(start)
        while True:
            lt = time.localtime(t)
            hms = time.strftime("%H%M%S", lt)
            d = self.root / folder / time.strftime("%Y-%m-%d", lt)
            taken = (d / f"{hms}.part.mp4").exists() or (d / f"{hms}.remux.mp4").exists()
            if not taken and d.is_dir():
                taken = any(n.startswith(hms + "-") and CLIP.fullmatch(n) for n in os.listdir(d))
            if not taken:
                d.mkdir(parents=True, exist_ok=True)
                return d / f"{hms}.part.mp4"
            t += 1

    def remux_path(self, part):
        return part.with_name(part.name[:6] + ".remux.mp4")

    def final_paths(self, part, length_s):
        stem = f"{part.name[:6]}-{int(length_s)}"
        return part.with_name(stem + ".mp4"), part.with_name(stem + ".jpg")

    def parts(self):
        return [self.root / f / d / n for f, d, n, _, _ in self._walk((PART,))]

    def discard(self, path):
        """Delete a part or remux file of ours; anything else is ignored."""
        try:
            rel = Path(path).relative_to(self.root).parts
        except ValueError:
            return
        if len(rel) == 3:
            self._remove(*rel, patterns=(PART, REMUX))

    def _remove(self, folder, day, name, patterns):
        """The one place that deletes. True if the file is gone."""
        if not (FOLDER.fullmatch(folder) and DAY.fullmatch(day)
                and any(p.fullmatch(name) for p in patterns)):
            return False
        base = self.root / folder
        if not (_is_dir(base) and _is_dir(base / day)):
            return False
        path = base / day / name
        if not _is_file(path):
            return False
        try:
            os.unlink(path)
        except FileNotFoundError:
            return True  # someone else got there first
        except OSError:
            return False
        return True

    # --- reading side ---

    def cameras(self):
        out = []
        for folder in self._folders():
            days = [d for d in self._days(folder) if self._files(folder, d, (CLIP,))]
            if days:
                out.append({"folder": folder, "name": camera_for(folder), "days": days[::-1]})
        return sorted(out, key=lambda c: (c["name"], c["folder"]))

    def has_clips(self):
        """Is there at least one clip? Stops at the first one (cheap enough to ask often)."""
        return any(self._files(folder, day, (CLIP,)) for folder in self._folders() for day in self._days(folder))

    def clips(self, folder, day):
        thumbs = {n[:-4] for n, _, _ in self._files(folder, day, (THUMB,))}
        rows = []
        for n, m, _ in self._files(folder, day, (CLIP,)):
            t = m.group(1)
            rows.append({"file": n, "time": f"{t[:2]}:{t[2:4]}:{t[4:]}", "len": int(m.group(2)),
                         "thumb": n[:-4] in thumbs})
        return sorted(rows, key=lambda r: r["file"], reverse=True)

    def count(self, camera, day):
        return len(self._files(folder_for(camera), day, (CLIP,)))

    def file(self, folder, day, name):
        if not (FOLDER.fullmatch(folder) and DAY.fullmatch(day)
                and (CLIP.fullmatch(name) or THUMB.fullmatch(name))):
            return None
        path = self.root / folder / day / name
        if _is_dir(self.root / folder) and _is_dir(self.root / folder / day) and _is_file(path):
            return path
        return None

    def total_bytes(self):
        return sum(s for *_, s in self._walk(OURS))

    def enforce(self, cap_bytes, keep_free_bytes, free_bytes):
        """Delete the oldest clips (with thumbnails) until under the cap and the free floor is met.
        Returns (bytes left, floor_ok). Never touches a part file.
        """
        found = self._walk((CLIP, THUMB))
        sizes = {(f, d, n): s for f, d, n, _, s in found}
        total = self.total_bytes()
        queue = sorted((d, m.group(1), f, n) for f, d, n, m, _ in found if CLIP.fullmatch(n))
        touched = set()
        for day, _, folder, name in queue:
            if total <= cap_bytes and free_bytes() >= keep_free_bytes:
                break
            for victim in (name, name[:-4] + ".jpg"):
                if (folder, day, victim) in sizes and self._remove(folder, day, victim, (CLIP, THUMB)):
                    total -= sizes[(folder, day, victim)]
            touched.add((folder, day))
        for folder, day in sorted(touched):
            self._rmdir(self.root / folder / day)
            self._rmdir(self.root / folder)
        return self.total_bytes(), free_bytes() >= keep_free_bytes

    def _rmdir(self, path):
        """Remove a directory only if it is real and empty (rmdir refuses otherwise)."""
        if _is_dir(path):
            try:
                os.rmdir(path)
            except OSError:
                pass
