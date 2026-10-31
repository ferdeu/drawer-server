"""Tests for the panel's camera routes. Run on the phone: bash tests/run-on-phone.sh"""
import json
import socket
import sys
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

    def test_player_script(self):
        code, body, headers = self.fetch("/live/video-rtc.js")
        self.assertEqual((code, body), (200, b"export class VideoRTC {}"))
        self.assertIn("javascript", headers["Content-Type"])


if __name__ == "__main__":
    unittest.main()
