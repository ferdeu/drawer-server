"""Tests for the fridge view's calendars (agenda.py). Run on the phone: bash tests/run-on-phone.sh"""
import sys
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "termux" / "panel"))
import agenda  # noqa: E402

TZ = ZoneInfo("America/Argentina/Buenos_Aires")
START = datetime(2026, 11, 7, tzinfo=TZ)


def ics(*events):
    """A calendar with the given VEVENT bodies (lines without BEGIN/END)."""
    out = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//test//EN"]
    for n, body in enumerate(events):
        out += ["BEGIN:VEVENT", f"UID:e{n}@test", "DTSTAMP:20261101T000000Z", *body.strip().splitlines(), "END:VEVENT"]
    out.append("END:VCALENDAR")
    return "\r\n".join(out) + "\r\n"


def event(summary, dtstart, dtend, *extra):
    return "\n".join([f"SUMMARY:{summary}", dtstart, dtend, *extra])


GOOD = ics(event("Dentista", "DTSTART:20261107T163000Z", "DTEND:20261107T173000Z", "LOCATION:Av. Siempre Viva 742\\nPiso 2"))


class AgendaParseTest(unittest.TestCase):
    def test_clean_title(self):
        self.assertEqual(agenda.clean_title("🎂 [Nicolas] ❓ Cumple Enzo"), ("Cumple Enzo", True))
        self.assertEqual(agenda.clean_title("Dentista"), ("Dentista", False))
        self.assertEqual(agenda.clean_title("⚠️ Acto"), ("Acto", True))

    def test_timed_event_in_utc_lands_local(self):
        [e] = agenda.parse_calendars([GOOD], START)
        self.assertEqual(e["start"], "2026-11-07T13:30")
        self.assertEqual(e["end"], "2026-11-07T14:30")
        self.assertEqual(e["title"], "Dentista")
        self.assertEqual(e["where"], "Av. Siempre Viva 742")
        self.assertFalse(e["all_day"])
        self.assertEqual(e["cals"], [0])
        self.assertFalse(e["unsure"])

    def test_tzid_and_floating(self):
        text = ics(
            event("Almuerzo", "DTSTART;TZID=America/Argentina/Buenos_Aires:20261108T120000",
                  "DTEND;TZID=America/Argentina/Buenos_Aires:20261108T130000"),
            event("Gimnasia", "DTSTART:20261109T080000", "DTEND:20261109T090000"),
        )
        starts = {e["title"]: e["start"] for e in agenda.parse_calendars([text], START)}
        self.assertEqual(starts, {"Almuerzo": "2026-11-08T12:00", "Gimnasia": "2026-11-09T08:00"})

    def test_weekly_recurrence_expands(self):
        body = event("Inglés", "DTSTART;TZID=America/Argentina/Buenos_Aires:20261005T170000",
                     "DTEND;TZID=America/Argentina/Buenos_Aires:20261005T180000", "RRULE:FREQ=WEEKLY;BYDAY=MO,WE")
        starts = [e["start"] for e in agenda.parse_calendars([ics(body)], START)]
        self.assertEqual(starts, ["2026-11-09T17:00", "2026-11-11T17:00"])
        body += "\nEXDATE;TZID=America/Argentina/Buenos_Aires:20261111T170000"
        starts = [e["start"] for e in agenda.parse_calendars([ics(body)], START)]
        self.assertEqual(starts, ["2026-11-09T17:00"])

    def test_all_day_multi_day(self):
        text = ics(event("Viaje", "DTSTART;VALUE=DATE:20261110", "DTEND;VALUE=DATE:20261112"))
        [e] = agenda.parse_calendars([text], START)
        self.assertTrue(e["all_day"])
        self.assertEqual((e["start"], e["end"]), ("2026-11-10", "2026-11-12"))

    def test_window(self):
        text = ics(
            event("Antes", "DTSTART:20261106T150000Z", "DTEND:20261106T160000Z"),
            event("Después", "DTSTART:20261114T150000Z", "DTEND:20261114T160000Z"),
            event("Cruza", "DTSTART;TZID=America/Argentina/Buenos_Aires:20261106T230000",
                  "DTEND;TZID=America/Argentina/Buenos_Aires:20261107T010000"),
        )
        self.assertEqual([e["title"] for e in agenda.parse_calendars([text], START)], ["Cruza"])

    def test_duplicates_merge(self):
        same = ics(event("🎂 [Sofia] Acto", "DTSTART:20261110T120000Z", "DTEND:20261110T130000Z"))
        other = ics(event("[Lucia] Acto", "DTSTART:20261110T120000Z", "DTEND:20261110T130000Z"))
        later = ics(event("Acto", "DTSTART:20261110T140000Z", "DTEND:20261110T150000Z"))
        events = agenda.parse_calendars([GOOD, same, other], START)
        self.assertEqual([e["cals"] for e in events if e["title"] == "Acto"], [[1, 2]])
        events = agenda.parse_calendars([same, later], START)
        self.assertEqual(len(events), 2)

    def test_bad_calendar_skipped(self):
        events = agenda.parse_calendars([GOOD, None, "garbage"], START)
        self.assertEqual([e["title"] for e in events], ["Dentista"])

    def test_calendar_list(self):
        text = "\n".join([
            "Casa|#5ee1ff|https://calendar.google.com/calendar/ical/a/private-x/basic.ics",
            "",
            "Plain|#123456|http://example.com/b.ics",
            "No color|https://example.com/c.ics",
            "Escuela | #AABBCC | https://example.com/d.ics",
        ])
        cals = agenda.parse_calendar_list(text)
        self.assertEqual([(c["name"], c["color"]) for c in cals], [("Casa", "#5ee1ff"), ("Escuela", "#AABBCC")])
        self.assertEqual(cals[1]["url"], "https://example.com/d.ics")
        many = "\n".join(f"C{n}|#000000|https://example.com/{n}.ics" for n in range(20))
        self.assertEqual(len(agenda.parse_calendar_list(many)), 12)


if __name__ == "__main__":
    unittest.main()
