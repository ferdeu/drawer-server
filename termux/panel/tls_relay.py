"""The fridge page's https door. Spotify only plays inside a page opened over https, so the panel also
listens on PANEL_HTTPS_PORT (8443): each connection is decrypted here and passed byte for byte to the
panel's own plain port on 127.0.0.1. Home only, like the cameras. Used by panel.py (deployed side by side).
The certificate is made by scripts/08-panel.sh and signed by a home certificate the tablet trusts.
"""
import ipaddress
import re
import select
import socket
import ssl
import sys
import threading

IDLE_S = 300  # nothing either way for this long: the connection is dropped
_HOST = re.compile(rb"\r\nHost: *([^\r\n]+)", re.IGNORECASE)
_PATH = re.compile(rb"^[A-Z]+ (/[^ \r\n]*) ")


class TlsRelay:
    def __init__(self, cert, key, target_port, port=8443, bind="0.0.0.0", allow=lambda ip: True, max_open=64):
        self.ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.ctx.load_cert_chain(cert, key)
        self.target_port, self.allow = target_port, allow
        self.places = threading.BoundedSemaphore(max_open)  # one device can't take every thread
        self.sock = socket.create_server((bind, port))
        self.port = self.sock.getsockname()[1]

    def serve_forever(self):
        while True:
            try:
                conn, addr = self.sock.accept()
            except OSError:  # closed
                return
            if not self.allow(addr[0]) or not self.places.acquire(blocking=False):
                conn.close()
                continue
            # the handshake waits on the browser: in the connection's own thread, never here
            threading.Thread(target=self.handle_one, args=(conn,), daemon=True).start()

    def handle_one(self, conn):
        try:
            self.handle(conn)
        finally:
            self.places.release()

    def close(self):
        self.sock.close()

    def handle(self, conn):
        try:
            conn.settimeout(15)
            first = conn.recv(1, socket.MSG_PEEK)
            if first and first != b"\x16":  # not a TLS hello: http:// typed by hand
                self.redirect(conn)
                return
            tls = self.ctx.wrap_socket(conn, server_side=True)
            up = socket.create_connection(("127.0.0.1", self.target_port), timeout=5)
        except OSError:
            conn.close()
            return
        try:
            self.pump(tls, up)
        except OSError:
            pass
        except Exception as e:
            print(f"https: {type(e).__name__}", file=sys.stderr, flush=True)
        finally:
            up.close()
            tls.close()

    def pump(self, tls, up):
        """Both directions in this one thread: an ssl socket must not be used by two threads at once."""
        tls.settimeout(30)
        up.settimeout(30)
        while True:
            # bytes already decrypted wait inside the ssl object, where select can't see them
            ready = [tls] if tls.pending() else select.select([tls, up], [], [], IDLE_S)[0]
            if not ready:
                return
            for s in ready:
                data = s.recv(65536)
                if not data:
                    return
                (up if s is tls else tls).sendall(data)

    def redirect(self, conn):
        head = conn.recv(4096)
        host, path = _HOST.search(head), _PATH.match(head)
        name = host.group(1).decode("latin-1").strip() if host else ""
        try:
            ipaddress.ip_address(name.rsplit(":", 1)[0] if name.count(":") == 1 else name)
        except ValueError:
            conn.sendall(b"HTTP/1.0 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
        else:
            where = "https://" + name + (path.group(1).decode("latin-1") if path else "/")
            conn.sendall(f"HTTP/1.0 301 Moved\r\nLocation: {where}\r\nContent-Length: 0\r\n\r\n".encode("latin-1"))
        conn.close()
