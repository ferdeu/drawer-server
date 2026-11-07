"""Tests for the fridge view's calendars (agenda.py). Run on the phone: bash tests/run-on-phone.sh"""
import importlib.util
import io
import json
import sys
import tempfile
import unittest
import unittest.mock
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "termux" / "panel"))
import agenda  # noqa: E402

TZ = ZoneInfo("America/Argentina/Buenos_Aires")
START = datetime(2026, 11, 7, tzinfo=TZ)
# step 8 installs it only when calendars are set up
needs_ical = unittest.skipUnless(importlib.util.find_spec("recurring_ical_events"), "recurring-ical-events not installed")


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


@needs_ical
class AgendaParseTest(unittest.TestCase):
    def test_clean_title(self):
        self.assertEqual(agenda.clean_title("🎂 [Juan] ❓ Cumple Pedro"), ("Cumple Pedro", True))
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
        same = ics(event("🎂 [Ana] Acto", "DTSTART:20261110T120000Z", "DTEND:20261110T130000Z"))
        other = ics(event("[Bea] Acto", "DTSTART:20261110T120000Z", "DTEND:20261110T130000Z"))
        later = ics(event("Acto", "DTSTART:20261110T140000Z", "DTEND:20261110T150000Z"))
        events = agenda.parse_calendars([GOOD, same, other], START)
        self.assertEqual([e["cals"] for e in events if e["title"] == "Acto"], [[1, 2]])
        events = agenda.parse_calendars([same, later], START)
        self.assertEqual(len(events), 2)

    def test_bad_event_skipped(self):
        text = ics("SUMMARY:Raro\nDTEND:20261108T130000Z",  # no start: must not take the whole calendar down
                   event("Bien", "DTSTART:20261109T120000Z", "DTEND:20261109T130000Z"))
        self.assertIn("Bien", [e["title"] for e in agenda.parse_calendars([text], START)])

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


@needs_ical
class AgendaReaderTest(unittest.TestCase):
    URL0, URL1 = "https://example.com/0.ics", "https://example.com/1.ics"

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.config = Path(self.dir.name) / "calendars"
        self.config.write_text(f"Uno|#5ee1ff|{self.URL0}\nDos|#7cf5b0|{self.URL1}\n")
        self.answers = {self.URL0: GOOD, self.URL1: ics(event("Cumple", "DTSTART;VALUE=DATE:20261114", "DTEND;VALUE=DATE:20261115"))}
        self.clock = datetime(2026, 11, 7, 10, 0, tzinfo=TZ)
        self.agenda = agenda.Agenda(self.config, fetch=self.fetch, now=lambda: self.clock)

    def tearDown(self):
        self.dir.cleanup()

    def fetch(self, url):
        answer = self.answers[url]
        if isinstance(answer, Exception):
            raise answer
        return answer

    def titles(self):
        return [e["title"] for e in self.agenda.snapshot()["events"]]

    def test_snapshot_has_no_urls(self):
        self.agenda.refresh()
        snap = self.agenda.snapshot()
        self.assertEqual(snap["calendars"], [{"name": "Uno", "color": "#5ee1ff"}, {"name": "Dos", "color": "#7cf5b0"}])
        self.assertNotIn("https://", json.dumps(snap))

    def test_failure_keeps_last_good(self):
        self.agenda.refresh()
        self.answers[self.URL0] = OSError("down " + self.URL0)
        self.agenda.refresh()
        self.assertEqual(self.titles(), ["Dentista"])
        self.assertFalse(self.agenda.snapshot()["stale"])
        self.clock += timedelta(minutes=31)
        self.assertTrue(self.agenda.snapshot()["stale"])

    def test_one_bad_calendar_doesnt_hide_others(self):
        self.answers[self.URL0] = TimeoutError()
        self.clock = datetime(2026, 11, 8, 10, 0, tzinfo=TZ)  # so the 14th is inside the week
        self.agenda.refresh()
        self.assertEqual(self.titles(), ["Cumple"])
        self.assertTrue(self.agenda.snapshot()["stale"])

    def test_garbage_doesnt_replace_last_good(self):
        self.agenda.refresh()
        self.answers[self.URL0] = "<html>not a calendar</html>"
        self.agenda.refresh()
        self.assertIn("Dentista", self.titles())

    def test_midnight_rollover(self):
        self.agenda.refresh()
        self.assertEqual(self.titles(), ["Dentista"])
        self.clock = datetime(2026, 11, 8, 0, 0, 30, tzinfo=TZ)
        self.assertEqual(self.titles(), ["Cumple"])

    def test_no_config(self):
        self.config.unlink()
        self.agenda.refresh()
        self.assertEqual(self.agenda.snapshot(), {"calendars": [], "events": [], "stale": False})

    def test_parse_error_is_stale_not_a_crash(self):
        self.agenda.refresh()
        with unittest.mock.patch.object(agenda, "parse_calendars", side_effect=ImportError("no module")):
            self.agenda.refresh()  # drops the cache
            self.assertEqual(self.agenda.snapshot()["events"], [])
            self.assertTrue(self.agenda.snapshot()["stale"])

    def test_retries_sooner_until_first_copy(self):
        self.answers[self.URL0] = TimeoutError()
        self.agenda.refresh()
        self.assertEqual(self.agenda.wait(600), 60)
        self.answers[self.URL0] = GOOD
        self.agenda.refresh()
        self.assertEqual(self.agenda.wait(600), 600)


class FetchTest(unittest.TestCase):
    def answer(self, size):
        return unittest.mock.patch.object(agenda.urllib.request, "urlopen", return_value=io.BytesIO(b"x" * size))

    def test_big_calendar_is_read(self):  # an old calendar keeps every past event
        with self.answer(5_000_000):
            self.assertEqual(len(agenda._fetch("https://example.com/a.ics")), 5_000_000)

    def test_too_big(self):
        with self.answer(agenda.MAX_BYTES + 1), self.assertRaises(agenda.TooBig):
            agenda._fetch("https://example.com/a.ics")


if __name__ == "__main__":
    unittest.main()
