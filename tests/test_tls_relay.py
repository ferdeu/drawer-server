"""Tests for the fridge page's https door (tls_relay.py). Run on the phone: bash tests/run-on-phone.sh
tls-test.pem/.key: a self-signed certificate for 127.0.0.1 made only for these tests."""
import socket
import ssl
import sys
import threading
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "termux" / "panel"))
import tls_relay  # noqa: E402


class Backend:
    """Stands in for the panel's plain http server: answers one request, or echoes everything."""

    def __init__(self, echo=False):
        self.sock = socket.create_server(("127.0.0.1", 0))
        self.port, self.echo, self.connections = self.sock.getsockname()[1], echo, 0
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        while True:
            conn, _ = self.sock.accept()
            self.connections += 1
            with conn:
                if self.echo:
                    while data := conn.recv(4096):
                        conn.sendall(data)
                else:
                    got = b""
                    while b"\r\n\r\n" not in got and (part := conn.recv(4096)):
                        got += part
                    conn.sendall(b"HTTP/1.0 200 OK\r\n\r\nhello " + got.split(b" ")[1])


class TlsRelayTest(unittest.TestCase):
    def start(self, backend, allow=lambda ip: True, **more):
        relay = tls_relay.TlsRelay(HERE / "tls-test.pem", HERE / "tls-test.key", backend.port,
                                   port=0, bind="127.0.0.1", allow=allow, **more)
        threading.Thread(target=relay.serve_forever, daemon=True).start()
        self.addCleanup(relay.close)
        return relay

    def client(self, relay):
        ctx = ssl.create_default_context(cafile=str(HERE / "tls-test.pem"))
        raw = socket.create_connection(("127.0.0.1", relay.port), timeout=5)
        tls = ctx.wrap_socket(raw, server_hostname="127.0.0.1")
        self.addCleanup(tls.close)
        return tls

    def read_all(self, sock):
        out = b""
        while part := sock.recv(4096):
            out += part
        return out

    def test_request_goes_through(self):
        relay = self.start(Backend())
        tls = self.client(relay)
        tls.sendall(b"GET /fridge HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
        self.assertTrue(self.read_all(tls).endswith(b"hello /fridge"))

    def test_both_ways_like_live_video(self):
        relay = self.start(Backend(echo=True))
        tls = self.client(relay)
        for word in (b"one", b"two" * 5000, b"three"):
            tls.sendall(word)
            got = b""
            while len(got) < len(word):
                got += tls.recv(65536)
            self.assertEqual(got, word)

    def test_away_is_refused(self):
        backend = Backend()
        relay = self.start(backend, allow=lambda ip: False)
        with self.assertRaises(OSError):  # closed before the handshake
            self.client(relay).sendall(b"GET / HTTP/1.1\r\n\r\n")
        self.assertEqual(backend.connections, 0)

    def test_plain_http_sent_to_https(self):
        relay = self.start(Backend())
        with socket.create_connection(("127.0.0.1", relay.port), timeout=5) as s:
            s.sendall(b"GET /fridge HTTP/1.1\r\nHost: 192.168.1.170:8443\r\n\r\n")
            answer = self.read_all(s)
        self.assertTrue(answer.startswith(b"HTTP/1.0 301"))
        self.assertIn(b"\r\nLocation: https://192.168.1.170:8443/fridge\r\n", answer)

    def test_plain_http_with_a_name_is_not_redirected(self):
        relay = self.start(Backend())
        with socket.create_connection(("127.0.0.1", relay.port), timeout=5) as s:
            s.sendall(b"GET / HTTP/1.1\r\nHost: evil.example\r\n\r\n")
            answer = self.read_all(s)
        self.assertTrue(answer.startswith(b"HTTP/1.0 400"))
        self.assertNotIn(b"evil", answer)

    def test_connections_are_capped(self):
        relay = self.start(Backend(), max_open=1)
        held = socket.create_connection(("127.0.0.1", relay.port), timeout=5)  # takes the only place
        time.sleep(0.3)
        with self.assertRaises(OSError):
            self.client(relay).sendall(b"GET / HTTP/1.1\r\n\r\n")
        held.close()  # its place is freed
        time.sleep(0.3)
        tls = self.client(relay)
        tls.sendall(b"GET /y HTTP/1.1\r\n\r\n")
        self.assertTrue(self.read_all(tls).endswith(b"hello /y"))

    def test_silent_client_does_not_block_others(self):
        relay = self.start(Backend())
        lazy = socket.create_connection(("127.0.0.1", relay.port), timeout=5)  # connects, sends nothing
        self.addCleanup(lazy.close)
        tls = self.client(relay)
        tls.sendall(b"GET /x HTTP/1.1\r\n\r\n")
        self.assertTrue(self.read_all(tls).endswith(b"hello /x"))


if __name__ == "__main__":
    unittest.main()
