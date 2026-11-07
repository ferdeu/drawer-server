"""One-time Spotify login for the fridge view's "now playing" strip. Run by scripts/spotify-login.sh.

Reads SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET from the environment, opens Spotify's consent page in the
browser, catches the answer on http://127.0.0.1:8888/callback and writes three lines (client id, client secret,
refresh token) to stdout, which must be a pipe: the secrets never show on screen. Messages go to stderr.
Standard library only.
"""
import base64
import json
import os
import secrets
import sys
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

REDIRECT = "http://127.0.0.1:8888/callback"
SCOPE = "user-read-playback-state"


def main():
    client_id, secret = os.environ.get("SPOTIFY_CLIENT_ID", ""), os.environ.get("SPOTIFY_CLIENT_SECRET", "")
    if not client_id or not secret:
        sys.exit("Put SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in .env")
    if sys.stdout.isatty():
        sys.exit("This prints secrets: pipe it to the phone (bash scripts/spotify-login.sh)")
    state = secrets.token_urlsafe(16)
    got = {}

    class Callback(BaseHTTPRequestHandler):
        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(url.query)
            if url.path != "/callback":
                self.send_error(404)
                return
            ok = q.get("state") == [state] and "code" in q
            if ok:
                got["code"] = q["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("Listo, ya podés cerrar esta pestaña.\nDone, you can close this tab.\n".encode()
                             if ok else b"Spotify said no, or the answer didn't match. Run the script again.\n")

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 8888), Callback)
    auth = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode({
        "client_id": client_id, "response_type": "code", "redirect_uri": REDIRECT, "scope": SCOPE, "state": state})
    print("Opening Spotify in the browser: log in with the account whose music the tablet shows, then accept.",
          file=sys.stderr)
    print(f"If no browser opens, copy this address into one:\n  {auth}", file=sys.stderr)
    webbrowser.open(auth)
    while "code" not in got:
        server.handle_request()
    server.server_close()

    body = urllib.parse.urlencode({"grant_type": "authorization_code", "code": got["code"],
                                   "redirect_uri": REDIRECT}).encode()
    req = urllib.request.Request("https://accounts.spotify.com/api/token", data=body, method="POST")
    req.add_header("Authorization", "Basic " + base64.b64encode(f"{client_id}:{secret}".encode()).decode())
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=20) as r:
        refresh = json.loads(r.read())["refresh_token"]
    sys.stdout.write(f"{client_id}\n{secret}\n{refresh}\n")


if __name__ == "__main__":
    main()
