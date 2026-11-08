"""One Spotify account for the fridge view: what's playing, and short-lived tokens for its player.
Used by panel.py (deployed side by side). config_path holds three lines: client id, client secret,
refresh token (written by scripts/spotify-login.sh). Those are secrets: never printed, never sent to the
page. Only an access token (lasts an hour) goes to the page at home, so the tablet can play.
"""
import base64
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

TOKEN_URL = "https://accounts.spotify.com/api/token"
PLAYER_URL = "https://api.spotify.com/v1/me/player"
CACHE_S = 5  # many open pages, one call


def _open(req):
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


class Spotify:
    def __init__(self, config_path, opener=_open, clock=time.time):
        self.config_path, self.opener, self.clock = Path(config_path), opener, clock
        self.lock = threading.Lock()
        self.token, self.token_until, self.token_for = None, 0.0, None  # token_for: the refresh token it came from
        self.cached, self.cached_at = None, None

    def _config(self):
        try:
            lines = self.config_path.read_text().split()
        except OSError:
            return None
        return lines if len(lines) == 3 else None

    def _save_refresh(self, config, refresh):
        tmp = self.config_path.with_name(self.config_path.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(f"{config[0]}\n{config[1]}\n{refresh}\n")
        os.replace(tmp, self.config_path)

    def _access_token(self, config):
        client_id, secret, refresh = config
        if self.token and self.clock() < self.token_until and self.token_for == refresh:
            return self.token  # a new login (other refresh token) gets a new one right away
        basic = base64.b64encode(f"{client_id}:{secret}".encode()).decode()
        body = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": refresh}).encode()
        req = urllib.request.Request(TOKEN_URL, data=body, method="POST")
        req.add_header("Authorization", "Basic " + basic)
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        status, data = self.opener(req)
        if status != 200:
            return None
        answer = json.loads(data)
        self.token = answer["access_token"]
        self.token_until = self.clock() + int(answer.get("expires_in", 3600)) - 60
        self.token_for = refresh
        if answer.get("refresh_token") and answer["refresh_token"] != refresh:
            self._save_refresh(config, answer["refresh_token"])
            self.token_for = answer["refresh_token"]
        return self.token

    def configured(self):
        return self._config() is not None

    def access_token(self):
        """A token for the fridge page's own player (lasts up to an hour), or None."""
        config = self._config()
        if not config:
            return None
        with self.lock:
            try:
                return self._access_token(config)
            except Exception:  # no internet, bad answer
                return None

    def _ask(self, config):
        status, data = 0, b""
        for _ in range(2):  # a 401 means the token died early: get a new one, once
            token = self._access_token(config)
            if not token:
                return None
            req = urllib.request.Request(PLAYER_URL)
            req.add_header("Authorization", "Bearer " + token)
            status, data = self.opener(req)
            if status != 401:
                break
            self.token = None
        if status != 200:
            return None
        player = json.loads(data)
        item = player.get("item")
        if not player.get("is_playing") or not item:
            return None
        album = item.get("album") or {}
        images = [i for i in album.get("images") or [] if i.get("url")]
        cover = min(images, key=lambda i: abs((i.get("width") or 0) - 300))["url"] if images else ""
        return {
            "song": item.get("name", ""),
            "artist": ", ".join(a.get("name", "") for a in item.get("artists") or []),
            "album": album.get("name", ""),
            "cover": cover,
            "progress_ms": player.get("progress_ms") or 0,
            "duration_ms": item.get("duration_ms") or 0,
            "device": (player.get("device") or {}).get("name", ""),
            "device_id": (player.get("device") or {}).get("id") or "",
        }

    def now_playing(self):
        """A dict with song, artist, album, cover, progress_ms, duration_ms, device and device_id, or None."""
        config = self._config()
        if not config:
            return None
        with self.lock:
            now = self.clock()
            if self.cached_at is not None and now - self.cached_at < CACHE_S:
                return self.cached
            try:
                self.cached = self._ask(config)
            except Exception:  # no internet, bad answer: just nothing playing
                self.cached = None
            self.cached_at = now
            return self.cached
