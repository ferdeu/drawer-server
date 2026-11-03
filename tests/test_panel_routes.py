"""Tests for the panel's camera routes. Run on the phone: bash tests/run-on-phone.sh"""
import json
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "termux" / "panel"))
import panel  # noqa: E402

CRLF = "\r\n"


class FakeStills:
    count = 3

    def __init__(self, image=b"\xff\xd8jpeg"):
        self.image, self.asked = image, []

    def get(self, n):
        if not 1 <= n <= self.count:
            raise IndexError(n)
        self.asked.append(n)
        return self.image


class FakeGo2rtc:
    """Answers like go2rtc: the player script over HTTP, and a websocket that echoes what it gets."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen()
        self.port = self.sock.getsockname()[1]
        self.requests = []
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        while True:
            conn, _ = self.sock.accept()
            threading.Thread(target=self.handle, args=(conn,), daemon=True).start()

    def handle(self, conn):
        head = b""
        while (CRLF * 2).encode() not in head:
            head += conn.recv(4096)
        self.requests.append(head.decode())
        if head.startswith(b"GET /video-rtc.js"):
            conn.sendall(CRLF.join(["HTTP/1.0 200 OK", "Content-Type: text/javascript", "",
                                    "export class VideoRTC {}"]).encode())
        elif b"src=cam1 " in head:  # go2rtc turns the websocket down but keeps the connection open
            conn.sendall(CRLF.join(["HTTP/1.1 400 Bad Request", "Content-Length: 0", "", ""]).encode())
            while data := conn.recv(4096):
                self.requests.append(data.decode())
        else:
            conn.sendall(CRLF.join(["HTTP/1.1 101 Switching Protocols", "Upgrade: websocket",
                                    "Connection: Upgrade", "", ""]).encode())
            if b"src=cam3" in head:  # a camera that went silent: hold the line, send nothing
                time.sleep(30)
            while data := conn.recv(4096):
                conn.sendall(data)
        conn.close()


class RoutesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), panel.Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.go2rtc = FakeGo2rtc()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        self.saved = panel.STILLS, panel.CAMERA_NAMES, panel.is_home, panel.GO2RTC_PORT
        panel.GO2RTC_PORT = self.go2rtc.port
        panel.STILLS, panel.CAMERA_NAMES = FakeStills(), ["Entrada", "Lateral", "Fondo"]
        panel.is_home = lambda ip: True

    def tearDown(self):
        panel.STILLS, panel.CAMERA_NAMES, panel.is_home, panel.GO2RTC_PORT = self.saved

    def fetch(self, path, headers=None):
        try:
            with urllib.request.urlopen(urllib.request.Request(self.base + path, headers=headers or {}), timeout=10) as r:
                return r.status, r.read(), r.headers
        except urllib.error.HTTPError as e:
            return e.code, b"", e.headers

    def test_still(self):
        code, body, headers = self.fetch("/api/camera/1.jpg?t=123")
        self.assertEqual((code, body), (200, b"\xff\xd8jpeg"))
        self.assertEqual(headers["Content-Type"], "image/jpeg")
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_no_image_yet(self):
        panel.STILLS.image = None
        self.assertEqual(self.fetch("/api/camera/2.jpg")[0], 204)

    def test_bad_paths(self):
        for path in ("/api/camera/0.jpg", "/api/camera/9.jpg", "/api/camera/../x", "/api/camera/1.png",
                     "/api/camera/01.jpg", "/api/camera/1.jpg/x"):
            self.assertEqual(self.fetch(path)[0], 404, path)
        self.assertEqual(panel.STILLS.asked, [])

    def test_away(self):
        panel.is_home = lambda ip: False
        self.assertEqual(self.fetch("/api/camera/1.jpg")[0], 403)
        self.assertEqual(panel.STILLS.asked, [])

    def test_status_cameras(self):
        cams = json.loads(self.fetch("/api/status")[1])["cameras"]
        self.assertEqual(cams, {"names": ["Entrada", "Lateral", "Fondo"], "home": True})

    def test_status_system(self):
        s = json.loads(self.fetch("/api/status")[1])
        self.assertGreaterEqual(s["system"]["ncpu"], 1)
        self.assertIsInstance(s["system"]["services"], list)
        self.assertIn(s["system"]["load_word"], ("calm", "busy", "very_busy"))
        self.assertIsNotNone(s["uptime_h"])  # Android 15 refuses /proc/uptime: it comes from sysinfo()

    def test_no_cameras(self):
        panel.STILLS, panel.CAMERA_NAMES = None, []
        self.assertEqual(self.fetch("/api/camera/1.jpg")[0], 404)
        self.assertEqual(self.fetch("/live/ws?src=cam1")[0], 404)
        self.assertIsNone(json.loads(self.fetch("/api/status")[1])["cameras"])

    def upgrade(self, path, host="192.168.1.50:8080", origin="http://192.168.1.50:8080", extra=()):
        s = socket.create_connection(("127.0.0.1", self.server.server_port), timeout=5)
        s.sendall(CRLF.join([f"GET {path} HTTP/1.1", f"Host: {host}", f"Origin: {origin}",
                             "Connection: Upgrade", "Upgrade: websocket", "Sec-WebSocket-Version: 13",
                             "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==", *extra, "", ""]).encode())
        return s

    def answer(self, s):
        head = b""
        while (CRLF * 2).encode() not in head:
            data = s.recv(4096)
            if not data:
                break
            head += data
        return head

    def test_live_other_website(self):
        # a page from another site, open on a home device, must not get the video
        s = self.upgrade("/live/ws?src=cam1", origin="http://ads.example.com")
        self.assertTrue(self.answer(s).startswith(b"HTTP/1.0 403"))
        s.close()

    def test_rebinding_host(self):
        # a site's own name pointed at the server (DNS rebinding) is turned away too
        s = self.upgrade("/live/ws?src=cam1", host="evil.example:8080", origin="http://evil.example:8080")
        self.assertTrue(self.answer(s).startswith(b"HTTP/1.0 403"))
        s.close()
        for path in ("/api/camera/1.jpg", "/live/video-rtc.js"):
            self.assertEqual(self.fetch(path, {"Host": "evil.example:8080"})[0], 403, path)
        self.assertEqual(panel.STILLS.asked, [])

    def test_live_silent_camera_closes(self):
        # nothing from go2rtc for LIVE_IDLE_S: the panel hangs up instead of waiting forever
        saved, panel.LIVE_IDLE_S = panel.LIVE_IDLE_S, 0.5
        try:
            s = self.upgrade("/live/ws?src=cam3")
            self.assertTrue(self.answer(s).startswith(b"HTTP/1.1 101"))
            s.settimeout(5)
            self.assertEqual(s.recv(4096), b"")
            s.close()
        finally:
            panel.LIVE_IDLE_S = saved

    def test_live_proxy(self):
        s = self.upgrade("/live/ws?src=cam2_hd")
        head = self.answer(s)
        self.assertTrue(head.startswith(b"HTTP/1.1 101"), head)
        s.sendall(b"ping")
        self.assertEqual(s.recv(4096), b"ping")
        s.close()
        sent = self.go2rtc.requests[-1]
        self.assertTrue(sent.startswith("GET /api/ws?src=cam2_hd HTTP/1.1" + CRLF), sent)
        self.assertNotIn("Origin:", sent)  # go2rtc refuses websockets from other origins

    def test_live_needs_websocket(self):
        # a plain request would turn the pass-through into an open door to go2rtc's API
        asked = len(self.go2rtc.requests)
        self.assertEqual(self.fetch("/live/ws?src=cam2")[0], 400)
        self.assertEqual(len(self.go2rtc.requests), asked)

    def test_live_refused_hangs_up(self):
        # go2rtc said no: pass its answer on and close, so nothing else reaches go2rtc
        s = self.upgrade("/live/ws?src=cam1")
        self.assertTrue(self.answer(s).startswith(b"HTTP/1.1 400"))
        asked = len(self.go2rtc.requests)
        try:
            s.sendall(f"GET /api/streams HTTP/1.1{CRLF}Host: x{CRLF}{CRLF}".encode())
            self.assertEqual(s.recv(4096), b"")
        except OSError:
            pass  # closed already: also fine
        s.close()
        time.sleep(0.2)
        self.assertEqual(len(self.go2rtc.requests), asked)

    def test_live_forwards_only_websocket_headers(self):
        s = self.upgrade("/live/ws?src=cam2_hd", extra=["Cookie: secret=1", "X-Forwarded-For: 10.0.0.9"])
        self.assertTrue(self.answer(s).startswith(b"HTTP/1.1 101"))
        s.close()
        sent = self.go2rtc.requests[-1]
        self.assertNotIn("Cookie", sent)
        self.assertNotIn("X-Forwarded-For", sent)
        self.assertIn("Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==", sent)

    def test_live_bad_source(self):
        for path in ("/live/ws?src=cam4", "/live/ws?src=cam0", "/live/ws?src=cam1_x", "/live/ws?src=exec:sh",
                     "/live/ws"):
            self.assertEqual(self.fetch(path)[0], 404, path)

    def test_live_away(self):
        panel.is_home = lambda ip: False
        self.assertEqual(self.fetch("/live/ws?src=cam1")[0], 403)
        self.assertEqual(self.fetch("/live/video-rtc.js")[0], 403)

    def post(self, path, origin=None):
        headers = {"Origin": origin} if origin else {}
        try:
            with urllib.request.urlopen(urllib.request.Request(self.base + path, data=b"", headers=headers), timeout=10) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code

    def speed_setup(self, per_day=4):
        saved = panel.speed_per_day, panel.speedtest, panel.SPEED_LOG, panel.SPEED_TRIES
        self.addCleanup(lambda: setattr(panel, "speed_per_day", saved[0]) or setattr(panel, "speedtest", saved[1])
                        or setattr(panel, "SPEED_LOG", saved[2]) or setattr(panel, "SPEED_TRIES", saved[3]))
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        panel.SPEED_LOG = Path(tmp.name) / "speed.csv"
        panel.SPEED_TRIES = Path(tmp.name) / "speed-tries"
        panel.speed_per_day = lambda: per_day
        panel.speedtest = lambda: [int(time.time()), 55.5, 15.5, 32, "Moreno, AR"]

    def test_speedtest_button(self):
        self.speed_setup()
        self.assertEqual(self.post("/api/speedtest", origin=self.base), 202)
        for _ in range(50):
            if not panel._speed["running"]:
                break
            time.sleep(0.05)
        speed = json.loads(self.fetch("/api/status")[1])["speed"]
        self.assertEqual(speed["last"][1:], [55.5, 15.5, 32, "Moreno, AR"])  # a comma in the name survives the CSV
        self.assertEqual((speed["per_day"], len(speed["day"]), speed["error"]), (4, 1, None))
        # each test moves ~100 MB: a second tap right away is turned down
        self.assertEqual(self.post("/api/speedtest", origin=self.base), 429)

    def test_speedtest_other_website(self):
        self.speed_setup()
        self.assertEqual(self.post("/api/speedtest", origin="http://ads.example.com"), 403)
        self.assertFalse(panel.SPEED_LOG.exists())

    def test_speedtest_off(self):
        self.speed_setup(per_day=None)
        self.assertEqual(self.post("/api/speedtest", origin=self.base), 404)
        self.assertIsNone(json.loads(self.fetch("/api/status")[1])["speed"])

    def test_speedtest_failure_shows(self):
        self.speed_setup()
        def broken():
            raise ValueError("no servers")
        panel.speedtest = broken
        self.assertEqual(self.post("/api/speedtest", origin=self.base), 202)
        for _ in range(50):
            if not panel._speed["running"]:
                break
            time.sleep(0.05)
        speed = json.loads(self.fetch("/api/status")[1])["speed"]
        self.assertEqual((speed["error"], speed["last"]), ("no servers", None))
        # a failed test counts: it doesn't run again right away (it may have moved its 100 MB)
        self.assertEqual(self.post("/api/speedtest", origin=self.base), 429)
        self.assertGreater(speed["next_ok"], time.time())
        panel._speed["error"] = None

    def test_speedtest_day_cap(self):
        self.speed_setup()
        hour_ago = int(time.time()) - 3600
        # a full day's tests in the last hours, oldest first
        panel.SPEED_TRIES.write_text("".join(f"{hour_ago - i * 600}\n" for i in reversed(range(panel.SPEED_DAY_CAP))))
        self.assertEqual(self.post("/api/speedtest", origin=self.base), 429)
        # yesterday's tries don't count
        panel.SPEED_TRIES.write_text("".join(f"{hour_ago - 86400 - i}\n" for i in range(panel.SPEED_DAY_CAP)))
        self.assertEqual(self.post("/api/speedtest", origin=self.base), 202)
        for _ in range(50):
            if not panel._speed["running"]:
                break
            time.sleep(0.05)

    def test_speed_per_day_setting(self):
        saved = panel.CONFIG, panel.shutil.which
        self.addCleanup(lambda: setattr(panel, "CONFIG", saved[0]) or setattr(panel.shutil, "which", saved[1]))
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        panel.CONFIG, panel.shutil.which = Path(tmp.name), lambda name: "/bin/" + name
        self.assertIsNone(panel.speed_per_day())  # no setting: no speed test at all
        for text, want in (("4", 4), ("0", 0), ("9", 6), ("-1", 0), ("abc", 0), ("", 0)):
            (panel.CONFIG / "speedtest").write_text(text + "\n")
            self.assertEqual(panel.speed_per_day(), want, text)

    def test_player_script(self):
        code, body, headers = self.fetch("/live/video-rtc.js")
        self.assertEqual((code, body), (200, b"export class VideoRTC {}"))
        self.assertIn("javascript", headers["Content-Type"])


class RecordingsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), panel.Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        self.saved = panel.STORE, panel.REC_BOOT, panel.REC_STATE, panel.CONFIG, panel.is_home
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.day = time.strftime("%Y-%m-%d")
        self.data = bytes(range(250)) * 4  # 1000 known bytes
        self.clip_dir = root / "recordings" / "Entrada" / self.day
        self.clip_dir.mkdir(parents=True)
        (self.clip_dir / "143005-42.mp4").write_bytes(self.data)
        (self.clip_dir / "143005-42.jpg").write_bytes(b"\xff\xd8jpeg")
        (root / "config").mkdir()
        (root / "boot").mkdir()
        panel.STORE = panel.ClipStore(root / "recordings")
        panel.CONFIG = root / "config"
        panel.REC_BOOT = root / "boot" / "70-recorder.sh"
        panel.REC_BOOT.write_text("x")
        panel.REC_STATE = root / "recorder.json"
        panel.is_home = lambda ip: True
        panel._rec_any["t"] = 0.0  # each test has its own clips
        self.root = root

    def tearDown(self):
        panel.STORE, panel.REC_BOOT, panel.REC_STATE, panel.CONFIG, panel.is_home = self.saved
        self.tmp.cleanup()

    def fetch(self, path, headers=None):
        try:
            with urllib.request.urlopen(urllib.request.Request(self.base + path, headers=headers or {}), timeout=10) as r:
                return r.status, r.read(), r.headers
        except urllib.error.HTTPError as e:
            return e.code, b"", e.headers

    def routes(self):
        return ["/api/recordings", f"/api/recordings/Entrada/{self.day}", f"/rec/Entrada/{self.day}/143005-42.mp4"]

    def write_state(self, age=0, **extra):
        state = {"time": int(time.time()) - age, "bytes": 5, "disk_full": False,
                 "cameras": [{"name": "Lateral", "n": 2, "state": "paused", "obstructed": "moving",
                              "last_motion": 0, "last_frame": 0, "today": 3},
                             {"name": "Fondo", "n": 3, "state": "off", "obstructed": None,
                              "last_motion": 0, "last_frame": 0, "today": 4}]}
        state.update(extra)
        panel.REC_STATE.write_text(json.dumps(state))

    def test_list_and_day(self):
        cams = json.loads(self.fetch("/api/recordings")[1])["cameras"]
        self.assertEqual([(c["name"], c["days"]) for c in cams], [("Entrada", [self.day])])
        clips = json.loads(self.fetch(f"/api/recordings/Entrada/{self.day}")[1])["clips"]
        self.assertEqual(clips, [{"file": "143005-42.mp4", "time": "14:30:05", "len": 42, "thumb": True, "bytes": 1006}])

    def test_file_and_range(self):
        url = f"/rec/Entrada/{self.day}/143005-42.mp4"
        code, body, h = self.fetch(url)
        self.assertEqual((code, body, h["Accept-Ranges"], h["Content-Type"]), (200, self.data, "bytes", "video/mp4"))
        code, body, h = self.fetch(url, {"Range": "bytes=0-1"})
        self.assertEqual((code, body, h["Content-Range"]), (206, self.data[:2], "bytes 0-1/1000"))
        code, body, h = self.fetch(url, {"Range": "bytes=990-"})
        self.assertEqual((code, body, h["Content-Range"]), (206, self.data[990:], "bytes 990-999/1000"))
        code, body, h = self.fetch(url, {"Range": "bytes=-5"})
        self.assertEqual((code, body, h["Content-Range"]), (206, self.data[-5:], "bytes 995-999/1000"))
        code, body, h = self.fetch(url, {"Range": "bytes=5000-"})
        self.assertEqual((code, h["Content-Range"]), (416, "bytes */1000"))
        code, body, h = self.fetch(f"/rec/Entrada/{self.day}/143005-42.jpg")
        self.assertEqual((code, h["Content-Type"]), (200, "image/jpeg"))

    def test_away_and_other_site(self):
        panel.is_home = lambda ip: False
        for path in self.routes():
            self.assertEqual(self.fetch(path)[0], 403, path)
        panel.is_home = lambda ip: True
        for path in self.routes():
            self.assertEqual(self.fetch(path, {"Origin": "http://evil.example"})[0], 403, path)
            self.assertEqual(self.fetch(path)[0], 200, path)

    def delete(self, path, headers=None):
        req = urllib.request.Request(self.base + path, method="DELETE", headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, None

    def test_delete_clip_route(self):
        url = f"/rec/Entrada/{self.day}/143005-42.mp4"
        self.assertEqual(self.delete(url), (200, {"clips": 1, "bytes": 1006}))
        self.assertEqual(self.fetch(url)[0], 404)
        self.assertEqual(self.delete(url), (404, None))

    def test_delete_day_route(self):
        (self.clip_dir / "150000-8.mp4").write_bytes(b"abc")
        (self.clip_dir / "160000.part.mp4").write_bytes(b"rec")
        self.assertEqual(self.delete(f"/api/recordings/Entrada/{self.day}"), (200, {"clips": 2, "bytes": 1009}))
        self.assertEqual(sorted(p.name for p in self.clip_dir.iterdir()), ["160000.part.mp4"])

    def delete_routes(self):
        return [f"/rec/Entrada/{self.day}/143005-42.mp4", f"/api/recordings/Entrada/{self.day}"]

    def test_delete_away(self):
        panel.is_home = lambda ip: False
        for path in self.delete_routes():
            self.assertEqual(self.delete(path)[0], 403, path)
        self.assertTrue((self.clip_dir / "143005-42.mp4").exists())

    def test_delete_other_site(self):
        for path in self.delete_routes():
            self.assertEqual(self.delete(path, {"Origin": "http://evil.example"})[0], 403, path)
        self.assertTrue((self.clip_dir / "143005-42.mp4").exists())

    def test_delete_hidden(self):
        (panel.CONFIG / "panel-recordings").write_text("show=no\n")
        for path in self.delete_routes():
            self.assertEqual(self.delete(path)[0], 404, path)
        self.assertTrue((self.clip_dir / "143005-42.mp4").exists())

    def test_delete_path_tricks(self):
        (self.root / "secret-1.mp4").write_bytes(b"secret")
        for path in (f"/rec/..%2F/{self.day}/143005-42.mp4", f"/rec/Entrada/{self.day}/..%2F..%2Fsecret-1.mp4",
                     f"/rec/Entrada/{self.day}/143005-42.jpg", "/rec/Entrada/2026-1-1/143005-42.mp4",
                     f"/api/recordings/%2e%2e/{self.day}", "/api/recordings/Entrada/..", "/api/recordings",
                     "/api/status", "/"):
            self.assertEqual(self.delete(path)[0], 404, path)
        self.assertTrue((self.root / "secret-1.mp4").exists())
        self.assertTrue((self.clip_dir / "143005-42.mp4").exists())
        self.assertTrue((self.clip_dir / "143005-42.jpg").exists())

    def test_hidden(self):
        (panel.CONFIG / "panel-recordings").write_text("show=no\n")
        for path in self.routes():
            self.assertEqual(self.fetch(path)[0], 404, path)
        self.assertIsNone(json.loads(self.fetch("/api/status")[1])["recordings"])

    def test_encoded_folder(self):
        d = self.root / "recordings" / "Patio%20trasero" / self.day
        d.mkdir(parents=True)
        (d / "090000-10.mp4").write_bytes(b"abc")
        cams = json.loads(self.fetch("/api/recordings")[1])["cameras"]
        self.assertIn("Patio trasero", [c["name"] for c in cams])
        code, body, _ = self.fetch(f"/rec/Patio%2520trasero/{self.day}/090000-10.mp4")
        self.assertEqual((code, body), (200, b"abc"))
        code, body, _ = self.fetch(f"/api/recordings/Patio%2520trasero/{self.day}")
        self.assertEqual(code, 200)

    def test_path_tricks(self):
        (self.clip_dir / "143005.part.mp4").write_bytes(b"x")
        (self.root / "secret.mp4").write_bytes(b"secret")
        try:
            (self.clip_dir / "150000-5.mp4").symlink_to(self.root / "secret.mp4")
        except OSError:
            self.skipTest("no symlinks")
        for path in (f"/rec/..%2F/{self.day}/143005-42.mp4", f"/rec/Entrada/{self.day}/../../x",
                     "/rec/Entrada/2026-1-1/143005-42.mp4", f"/rec/Entrada/{self.day}/143005.part.mp4",
                     f"/rec/Entrada/{self.day}/150000-5.mp4", f"/rec/Entrada/{self.day}/nothing-1.mp4"):
            self.assertEqual(self.fetch(path)[0], 404, path)

    def test_status_recorder(self):
        self.write_state()
        s = json.loads(self.fetch("/api/status")[1])
        self.assertEqual(s["recorder"], {"stale": False, "disk_full": False, "bytes": 5, "today": 7, "cameras": [
            {"name": "Lateral", "state": "paused", "obstructed": "moving"},
            {"name": "Fondo", "state": "off", "obstructed": None}]})
        self.assertIn({"name": "Recorder", "ok": True}, s["services"])
        self.assertEqual(s["recordings"], {"home": True})
        self.write_state(age=120)
        s = json.loads(self.fetch("/api/status")[1])
        self.assertTrue(s["recorder"]["stale"])
        self.assertIn({"name": "Recorder", "ok": False}, s["services"])
        panel.REC_STATE.write_text("{not json")
        self.assertTrue(json.loads(self.fetch("/api/status")[1])["recorder"]["stale"])
        panel.REC_STATE.unlink()
        self.assertTrue(json.loads(self.fetch("/api/status")[1])["recorder"]["stale"])
        panel.REC_BOOT.unlink()
        s = json.loads(self.fetch("/api/status")[1])
        self.assertIsNone(s["recorder"])
        self.assertNotIn("Recorder", [v["name"] for v in s["services"]])

    def test_recorder_off_clips_kept_no_walk_each_poll(self):
        # step 12 turned off but clips kept: still shown, without walking every clip on each poll
        panel.REC_BOOT.unlink()
        calls = []
        real = panel.STORE.has_clips
        panel.STORE.has_clips = lambda: calls.append(1) or real()
        panel.STORE.cameras = lambda: self.fail("status walked every clip")
        for _ in range(3):
            self.assertEqual(json.loads(self.fetch("/api/status")[1])["recordings"], {"home": True})
        self.assertEqual(self.fetch(f"/rec/Entrada/{self.day}/143005-42.jpg")[0], 200)
        self.assertEqual(len(calls), 1)  # asked once, then cached
        panel._rec_any["t"] -= 120  # a minute later it asks again
        (self.clip_dir / "143005-42.mp4").unlink()
        self.assertEqual(json.loads(self.fetch("/api/status")[1])["recordings"], {"off": True})
        self.assertEqual(len(calls), 2)

    def test_status_disk_full(self):
        self.write_state(disk_full=True)
        self.assertTrue(json.loads(self.fetch("/api/status")[1])["recorder"]["disk_full"])


class DiskTest(unittest.TestCase):
    def setUp(self):
        self.saved = (panel.CONFIG, panel.BACKUP_PAUSED, panel.backup_bytes, panel.recordings_bytes, panel.shutil.disk_usage)
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        panel.CONFIG = root
        panel.BACKUP_PAUSED = root / "backup-paused.json"
        panel.shutil.disk_usage = lambda p: type("U", (), {"total": 100_000_000_000, "used": 0, "free": 40_000_000_000})()
        self.root = root
        self.measures(20e9, 3.1e9)

    def tearDown(self):
        panel.CONFIG, panel.BACKUP_PAUSED, panel.backup_bytes, panel.recordings_bytes, panel.shutil.disk_usage = self.saved
        self.tmp.cleanup()

    def measures(self, backup, recordings):
        panel.backup_bytes = lambda: backup
        panel.recordings_bytes = lambda: recordings

    def test_pause_plan(self):
        plan = panel.backup_pause_plan
        self.assertEqual(plan(60, 50, True, {"a": False}, set()), ({"a"}, set()))
        self.assertEqual(plan(48, 50, True, {"a": True}, {"a"}), (set(), set()))  # between 95 and 100%
        self.assertEqual(plan(47, 50, True, {"a": True}, {"a"}), (set(), {"a"}))
        self.assertEqual(plan(60, 50, False, {"a": True}, {"a"}), (set(), {"a"}))  # setting turned off
        self.assertEqual(plan(60, None, True, {"a": True}, {"a"}), (set(), {"a"}))  # no share
        self.assertEqual(plan(10, 50, False, {"b": True}, set()), (set(), set()))  # a person's pause stays
        self.assertEqual(plan(60, 50, True, {"a": True, "b": False}, {"a"}), ({"b"}, set()))

    def test_disk_rows(self):
        (self.root / "disk").write_text("backup_gb=50\n")
        d = panel.disk()
        self.assertEqual(d["kinds"], [{"kind": "backup", "gb": 20.0, "share_gb": 50.0},
                                      {"kind": "recordings", "gb": 3.1, "share_gb": 10.0}])
        self.assertEqual((d["total_gb"], d["free_gb"], d["warn"]), (100.0, 40.0, None))

    def test_no_share_is_size_only(self):
        self.assertEqual(panel.disk()["kinds"][0], {"kind": "backup", "gb": 20.0, "share_gb": None})

    def test_recordings_at_cap_no_warning(self):
        (self.root / "disk").write_text("backup_gb=50\n")
        self.measures(5e9, 10e9)  # recordings share is 10% of 100 GB
        self.assertIsNone(panel.disk()["warn"])

    def test_backup_near(self):
        (self.root / "disk").write_text("backup_gb=50\n")
        self.measures(46e9, 3e9)
        self.assertEqual(panel.disk()["warn"], "near")
        panel.BACKUP_PAUSED.write_text('["a"]')
        self.assertEqual(panel.disk()["warn"], "paused")

    def test_kind_missing(self):
        self.measures(None, 3e9)
        self.assertEqual([k["kind"] for k in panel.disk()["kinds"]], ["recordings"])

    def test_paused_file_unreadable_is_empty(self):
        panel.BACKUP_PAUSED.write_text("{not json")
        self.assertEqual(panel.paused_by_us(), set())


class BackupKeeperTest(unittest.TestCase):
    """backup() with Syncthing's HTTP layer replaced: pauses and resumes only what it should."""

    def setUp(self):
        self.saved = (panel.CONFIG, panel.BACKUP_PAUSED, panel.SYNCTHING_CONFIG, panel.urllib.request.urlopen,
                      panel.shutil.disk_usage)
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        panel.CONFIG = root
        panel.BACKUP_PAUSED = root / "backup-paused.json"
        panel.SYNCTHING_CONFIG = root / "config.xml"
        panel.SYNCTHING_CONFIG.write_text("<apikey>k</apikey>")
        panel.shutil.disk_usage = lambda p: type("U", (), {"total": 100_000_000_000, "used": 0, "free": 40_000_000_000})()
        (root / "disk").write_text("backup_gb=50\nbackup_pause=yes\n")
        self.local = {"a": 60e9, "b": 0}
        self.paused = {"a": False, "b": True}  # b was paused by a person
        self.patched, self.down, self.timeout_after_apply = [], False, False
        panel.urllib.request.urlopen = self.fake

    def tearDown(self):
        (panel.CONFIG, panel.BACKUP_PAUSED, panel.SYNCTHING_CONFIG, panel.urllib.request.urlopen,
         panel.shutil.disk_usage) = self.saved
        self.tmp.cleanup()

    def fake(self, req, timeout=None):
        import io
        path = req.full_url.split("8384", 1)[1]
        if req.get_method() == "PATCH":
            if self.down:
                raise urllib.error.URLError("down")
            fid = path.rsplit("/", 1)[1]
            self.assertEqual(req.headers["X-api-key"], "k")
            body = json.loads(req.data)
            self.patched.append((fid, body["paused"]))
            self.paused[fid] = body["paused"]
            if self.timeout_after_apply:
                raise TimeoutError("timed out")
            return io.BytesIO(b"{}")
        if path == "/rest/system/status":
            out = {"myID": "ME"}
        elif path == "/rest/config/devices":
            out = []
        elif path == "/rest/system/connections":
            out = {"connections": {}, "total": {"inBytesTotal": 0}}
        elif path == "/rest/config/folders":
            out = [{"id": i, "label": i, "devices": [], "paused": p} for i, p in self.paused.items()]
        else:
            fid = path.split("folder=")[1]
            out = {"globalBytes": 1, "needBytes": 0, "needFiles": 0, "localBytes": int(self.local[fid])}
        return io.BytesIO(json.dumps(out).encode())

    def test_pauses_at_share_and_resumes_only_its_own(self):
        result = panel.backup()
        self.assertEqual(self.patched, [("a", True)])
        self.assertEqual(panel.paused_by_us(), {"a"})
        self.assertEqual(result["local_bytes"], 60_000_000_000)
        self.local["a"] = 40e9  # photos got deleted: under 95%
        panel.backup()
        self.assertEqual(self.patched, [("a", True), ("a", False)])
        self.assertEqual(panel.paused_by_us(), set())
        self.assertTrue(self.paused["b"])  # a person's pause is never touched

    def test_setting_off_resumes(self):
        panel.backup()
        (panel.CONFIG / "disk").write_text("backup_gb=50\n")
        panel.backup()
        self.assertEqual(self.patched[-1], ("a", False))
        self.assertEqual(panel.paused_by_us(), set())

    def test_person_resumed_it_drops_the_memory(self):
        panel.backup()
        self.paused["a"] = False
        self.local["a"] = 49e9  # between 95 and 100%: nothing to do
        panel.backup()
        self.assertEqual(panel.paused_by_us(), set())

    def test_unwritable_file_sends_no_pause(self):
        panel.BACKUP_PAUSED = Path(self.tmp.name) / "no-such-dir" / "x" / "backup-paused.json"
        saved = panel.remember_paused
        def boom(ids):
            raise OSError("disk full")
        panel.remember_paused = boom
        try:
            panel.backup()
        finally:
            panel.remember_paused = saved
        self.assertEqual(self.patched, [])
        self.assertFalse(self.paused["a"])

    def test_failed_pause_patch_is_forgotten_next_pass(self):
        self.down = True
        panel.backup()
        self.assertEqual(self.patched, [])
        self.assertEqual(panel.paused_by_us(), {"a"})  # kept for one pass: the pause may have applied
        self.local["a"] = 49e9  # nothing to do now, and the folder is still unpaused
        self.down = False
        panel.backup()
        self.assertEqual(panel.paused_by_us(), set())

    def test_timeout_after_pause_applied_still_resumes(self):
        self.timeout_after_apply = True
        panel.backup()
        self.assertTrue(self.paused["a"])  # Syncthing applied it, the reply never came
        self.assertEqual(panel.paused_by_us(), {"a"})
        self.timeout_after_apply = False
        self.local["a"] = 40e9
        panel.backup()
        self.assertEqual(self.patched[-1], ("a", False))
        self.assertFalse(self.paused["a"])
        self.assertEqual(panel.paused_by_us(), set())

    def test_restart_still_resumes(self):
        panel.backup()
        # nothing is kept in memory between passes: the file alone says what the panel paused
        self.assertEqual(panel.paused_by_us(), {"a"})
        self.local["a"] = 40e9
        panel.backup()
        self.assertEqual(self.patched[-1], ("a", False))


if __name__ == "__main__":
    unittest.main()
