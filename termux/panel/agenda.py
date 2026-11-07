"""Calendars for the fridge view: Google's secret iCal addresses, fetched, parsed and merged.
Used by panel.py (deployed side by side). Needs `recurring-ical-events` from pip, imported only when parsing.
"""
import re
import sys
from datetime import datetime, timedelta

MAX_CALENDARS = 12
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_UNSURE = re.compile(r"^(?:(?:❓|⚠️?)\s*)+")


def clean_title(summary):
    """The school agent's title rule: drop a leading emoji, a "[Name]" and ❓/⚠️ marks.
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
            found = recurring_ical_events.of(icalendar.Calendar.from_ical(text)).between(start, stop)
        except Exception as e:  # a broken calendar must not hide the others
            print(f"agenda: calendar {i + 1} could not be read ({type(e).__name__})", file=sys.stderr)
            continue
        for comp in found:
            if str(comp.get("STATUS", "")).upper() == "CANCELLED":
                continue
            raw = comp.get("DTSTART").dt
            begin, end = _local(raw, tz), _local(_end(comp, raw), tz)
            all_day = not isinstance(begin, datetime)
            if all_day:
                end = end.date() if isinstance(end, datetime) else end
                if not (begin < stop_day and end > first_day):
                    continue
            elif not (begin < stop and end > start):
                continue
            title, unsure = clean_title(str(comp.get("SUMMARY", "")))
            where = str(comp.get("LOCATION", "")).strip().splitlines()
            ev = {"title": title, "where": where[0][:80] if where else "", "start": _fmt(begin), "end": _fmt(end),
                  "all_day": all_day, "cals": [i], "unsure": unsure}
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
