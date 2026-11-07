"""Calendars for the fridge view: Google's secret iCal addresses, fetched, parsed and merged.
Used by panel.py (deployed side by side). Needs `recurring-ical-events` from pip, imported only when parsing.
"""
import re
import sys
import threading
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

MAX_CALENDARS = 12
MAX_BYTES = 20_000_000  # Google sends every past event too: an old calendar can be a few MB
RETRY_S = 60  # a calendar never read yet (just booted, Wi-Fi not up) is asked again this soon
STALE = timedelta(minutes=30)  # no fresh copy for this long: the page says so
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_UNSURE = re.compile(r"^(?:(?:❓|⚠️?)\s*)+")


def clean_title(summary):
    """Titles written by tools that tag events: drop a leading emoji, a "[Name]" tag and ❓/⚠️ marks.
    Gives (title, unsure); unsure when ❓ or ⚠ came before the title."""
    s = summary or ""
    t = re.sub(r"^[^\w\s\[\(]+\s*", "", s)
    t = re.sub(r"^\[.*?\]\s*", "", t)
    t = _UNSURE.sub("", t)
    prefix = s[:len(s) - len(t)]
    return t.strip(), "❓" in prefix or "⚠" in prefix


def parse_calendar_list(text):
    """`Name|#rrggbb|https://…` lines → [{"name", "color", "url"}]; anything else is skipped, at most 12."""
    out = []
    for line in (text or "").splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 3:
            continue
        name, color, url = parts
        if name and _COLOR.match(color) and url.startswith("https://") and not re.search(r"\s", url):
            out.append({"name": name, "color": color, "url": url})
    return out[:MAX_CALENDARS]


def _local(value, tz):
    """A DTSTART/DTEND value as local aware datetime, or a date for all-day ones."""
    if isinstance(value, datetime):
        return value.replace(tzinfo=tz) if value.tzinfo is None else value.astimezone(tz)
    return value


def _end(comp, start):
    if comp.get("DTEND") is not None:
        return comp.get("DTEND").dt
    if comp.get("DURATION") is not None:
        return start + comp.get("DURATION").dt
    return start + timedelta(days=1) if not isinstance(start, datetime) else start


def _fmt(value):
    return value.strftime("%Y-%m-%dT%H:%M") if isinstance(value, datetime) else value.isoformat()


def _event(comp, i, tz, start, stop, first_day, stop_day):
    """One occurrence as the page's event dict, or None when cancelled or outside the window."""
    if str(comp.get("STATUS", "")).upper() == "CANCELLED":
        return None
    raw = comp.get("DTSTART").dt
    begin, end = _local(raw, tz), _local(_end(comp, raw), tz)
    all_day = not isinstance(begin, datetime)
    if all_day:
        end = end.date() if isinstance(end, datetime) else end
        if not (begin < stop_day and end > first_day):
            return None
    elif not (begin < stop and end > start):
        return None
    title, unsure = clean_title(str(comp.get("SUMMARY", "")))
    where = str(comp.get("LOCATION", "")).strip().splitlines()
    return {"title": title, "where": where[0][:80] if where else "", "start": _fmt(begin), "end": _fmt(end),
            "all_day": all_day, "cals": [i], "unsure": unsure}


def parse_calendars(texts, start, days=7):
    """Events of all calendars overlapping [start, start + days), local times, duplicates merged.
    texts[i] is calendar i's ICS text, or None; one that can't be read is skipped."""
    import icalendar
    import recurring_ical_events

    tz, stop = start.tzinfo, start + timedelta(days=days)
    first_day, stop_day = start.date(), stop.date()
    merged = {}
    for i, text in enumerate(texts):
        if not text:
            continue
        try:
            cal = icalendar.Calendar.from_ical(text)
            # an event with no start, or a broken repeating one, is skipped, not the whole calendar
            cal.subcomponents = [c for c in cal.subcomponents if c.name != "VEVENT" or "DTSTART" in c]
            found = recurring_ical_events.of(cal, skip_bad_series=True).between(start, stop)
        except Exception as e:  # a broken calendar must not hide the others
            print(f"agenda: calendar {i + 1} could not be read ({type(e).__name__})", file=sys.stderr)
            continue
        for comp in found:
            try:
                ev = _event(comp, i, tz, start, stop, first_day, stop_day)
            except Exception as e:  # an odd event is left out, not its calendar
                print(f"agenda: an event in calendar {i + 1} was skipped ({type(e).__name__})", file=sys.stderr)
                continue
            if not ev:
                continue
            title, unsure = ev["title"], ev["unsure"]
            key = (title.casefold(), ev["start"], ev["end"])
            if key in merged:
                old = merged[key]
                if i not in old["cals"]:
                    old["cals"].append(i)
                old["unsure"] = old["unsure"] or unsure
                old["where"] = old["where"] or ev["where"]
            else:
                merged[key] = ev
    return sorted(merged.values(), key=lambda e: (e["start"], e["title"]))


class TooBig(ValueError):
    pass


def _fetch(url):
    with urllib.request.urlopen(url, timeout=20) as r:
        data = r.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise TooBig()
    return data.decode("utf-8", errors="replace")


def _readable(text):
    import icalendar
    return icalendar.Calendar.from_ical(text) is not None


class Agenda:
    """Keeps the last good copy of each calendar listed in config_path and gives the merged week.
    URLs are secrets: they never leave this object, not even in error lines."""

    def __init__(self, config_path, fetch=_fetch, now=lambda: datetime.now().astimezone()):
        self.config_path, self.fetch, self.now = Path(config_path), fetch, now
        self.lock = threading.Lock()
        self.cals, self.texts, self.ok = [], {}, {}  # texts and ok (last success) are keyed by URL
        self.cache = None  # (day, events)

    def refresh(self):
        try:
            cals = parse_calendar_list(self.config_path.read_text(errors="replace"))
        except OSError:
            cals = []
        got = {}
        for n, cal in enumerate(cals, 1):
            try:
                text = self.fetch(cal["url"])
                _readable(text)
                got[cal["url"]] = text
            except Exception as e:  # keep the last good copy; never print the URL
                why = f"bigger than {MAX_BYTES // 1_000_000} MB" if isinstance(e, TooBig) else type(e).__name__
                print(f"agenda: calendar {n} not fetched ({why})", file=sys.stderr)
        urls = {c["url"] for c in cals}
        with self.lock:
            self.cals = cals
            self.texts = {u: t for u, t in self.texts.items() if u in urls} | got
            self.ok = {u: t for u, t in self.ok.items() if u in urls} | {u: self.now() for u in got}
            self.cache = None

    def start(self, every_s=600):
        def loop():
            while True:
                try:
                    self.refresh()
                except Exception as e:
                    print(f"agenda: {type(e).__name__}", file=sys.stderr)
                time.sleep(self.wait(every_s))
        threading.Thread(target=loop, daemon=True).start()

    def wait(self, every_s):
        """Seconds until the next refresh: sooner while a calendar has never been read."""
        with self.lock:
            return RETRY_S if any(c["url"] not in self.ok for c in self.cals) else every_s

    def snapshot(self):
        now = self.now()
        day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        with self.lock:
            cals, texts, ok = self.cals, self.texts, self.ok
            broken = False
            if self.cache is None or self.cache[0] != day:  # parse again only after a refresh or at midnight
                try:
                    self.cache = (day, parse_calendars([texts.get(c["url"]) for c in cals], day) if cals else [])
                except Exception as e:  # e.g. the iCal package gone after a Python upgrade: say so, don't crash
                    print(f"agenda: could not read the calendars ({type(e).__name__})", file=sys.stderr)
                    broken = True
            events = [] if broken else self.cache[1]
        stale = broken or any(c["url"] not in ok or now - ok[c["url"]] > STALE for c in cals)
        return {"calendars": [{"name": c["name"], "color": c["color"]} for c in cals], "events": events,
                "stale": stale}
