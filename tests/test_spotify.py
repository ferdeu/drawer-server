"""Tests for the fridge view's "now playing" (spotify.py). Run on the phone: bash tests/run-on-phone.sh"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "termux" / "panel"))
import spotify  # noqa: E402

TOKEN = (200, json.dumps({"access_token": "tok", "expires_in": 3600}).encode())
PLAYER = (200, json.dumps({
    "is_playing": True, "progress_ms": 61000,
    "device": {"name": "Parlante cocina", "id": "dev1"},
    "item": {
        "name": "Canción", "duration_ms": 200000,
        "artists": [{"name": "A"}, {"name": "B"}],
        "album": {"name": "Disco", "images": [
            {"url": "https://i.scdn.co/640", "width": 640}, {"url": "https://i.scdn.co/300", "width": 300},
            {"url": "https://i.scdn.co/64", "width": 64}]},
    },
}).encode())


class FakeOpener:
    """Answers token and player requests from two queues; records what was asked."""

    def __init__(self, tokens=(), players=()):
        self.tokens, self.players, self.asked = list(tokens), list(players), []

    def __call__(self, req):
        self.asked.append(req)
        queue = self.tokens if "accounts.spotify.com" in req.full_url else self.players
        answer = queue.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def count(self, host):
        return sum(host in r.full_url for r in self.asked)


class SpotifyTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.config = Path(self.dir.name) / "spotify"
        self.config.write_text("id\nsecret\nrefresh\n")
        self.time = 1000.0

    def tearDown(self):
        self.dir.cleanup()

    def make(self, opener):
        return spotify.Spotify(self.config, opener=opener, clock=lambda: self.time)

    def test_no_config_no_network(self):
        self.config.unlink()
        opener = FakeOpener()
        self.assertIsNone(self.make(opener).now_playing())
        self.assertEqual(opener.asked, [])

    def test_playing(self):
        opener = FakeOpener([TOKEN], [PLAYER])
        self.assertEqual(self.make(opener).now_playing(), {
            "song": "Canción", "artist": "A, B", "album": "Disco", "cover": "https://i.scdn.co/300",
            "progress_ms": 61000, "duration_ms": 200000, "device": "Parlante cocina", "device_id": "dev1"})
        token_req, player_req = opener.asked
        self.assertEqual(token_req.get_method(), "POST")
        self.assertIn(b"grant_type=refresh_token", token_req.data)
        self.assertTrue(token_req.get_header("Authorization").startswith("Basic "))
        self.assertEqual(player_req.full_url, "https://api.spotify.com/v1/me/player")
        self.assertEqual(player_req.get_header("Authorization"), "Bearer tok")

    def test_nothing_playing(self):
        paused = (200, json.dumps({"is_playing": False, "item": None}).encode())
        opener = FakeOpener([TOKEN], [(204, b""), paused])
        player = self.make(opener)
        self.assertIsNone(player.now_playing())
        self.time += 6
        self.assertIsNone(player.now_playing())

    def test_expired_token_retries_once(self):
        opener = FakeOpener([TOKEN, TOKEN], [(401, b""), PLAYER])
        self.assertEqual(self.make(opener).now_playing()["song"], "Canción")
        self.assertEqual(opener.count("accounts.spotify.com"), 2)

    def test_token_reused(self):
        opener = FakeOpener([TOKEN], [PLAYER, PLAYER])
        player = self.make(opener)
        player.now_playing()
        self.time += 6
        player.now_playing()
        self.assertEqual(opener.count("accounts.spotify.com"), 1)

    def test_new_refresh_token_saved(self):
        token = (200, json.dumps({"access_token": "tok", "expires_in": 3600, "refresh_token": "new"}).encode())
        self.make(FakeOpener([token], [PLAYER])).now_playing()
        self.assertEqual(self.config.read_text().splitlines(), ["id", "secret", "new"])
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o600)

    def test_cache(self):
        opener = FakeOpener([TOKEN], [PLAYER])
        player = self.make(opener)
        player.now_playing()
        self.time += 4
        self.assertEqual(player.now_playing()["song"], "Canción")
        self.assertEqual(opener.count("api.spotify.com"), 1)

    def test_configured(self):
        self.assertTrue(self.make(FakeOpener()).configured())
        self.config.write_text("id\nsecret\n")  # login never finished
        self.assertFalse(self.make(FakeOpener()).configured())

    def test_access_token(self):
        opener = FakeOpener([TOKEN])
        player = self.make(opener)
        self.assertEqual(player.access_token(), "tok")
        self.assertEqual(player.access_token(), "tok")  # reused while it lasts
        self.assertEqual(opener.count("accounts.spotify.com"), 1)

    def test_access_token_without_login(self):
        self.config.unlink()
        opener = FakeOpener()
        self.assertIsNone(self.make(opener).access_token())
        self.assertEqual(opener.asked, [])

    def test_new_login_drops_the_old_token(self):
        # logging in again (e.g. to allow more) must not keep using the old login's token for up to an hour
        second = (200, json.dumps({"access_token": "tok2", "expires_in": 3600}).encode())
        player = self.make(FakeOpener([TOKEN, second]))
        self.assertEqual(player.access_token(), "tok")
        self.config.write_text("id\nsecret\nnewlogin\n")
        self.assertEqual(player.access_token(), "tok2")

    def test_rotated_refresh_token_keeps_the_token(self):
        rotated = (200, json.dumps({"access_token": "tok", "expires_in": 3600, "refresh_token": "new"}).encode())
        opener = FakeOpener([rotated])
        player = self.make(opener)
        player.access_token()
        player.access_token()
        self.assertEqual(opener.count("accounts.spotify.com"), 1)

    def test_errors_are_none(self):
        self.assertIsNone(self.make(FakeOpener([OSError("no internet")])).now_playing())
        self.assertIsNone(self.make(FakeOpener([TOKEN], [(500, b"")])).now_playing())
        self.assertIsNone(self.make(FakeOpener([TOKEN], [(200, b"not json")])).now_playing())


if __name__ == "__main__":
    unittest.main()
