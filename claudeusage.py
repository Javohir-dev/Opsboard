import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib import error, request

API = os.environ.get("OPS_ANTHROPIC_URL", "https://api.anthropic.com").rstrip("/")
KEYCHAIN_SERVICE = "Claude Code-credentials"
CREDENTIALS_FILE = Path(os.environ.get("OPS_CLAUDE_CREDENTIALS", Path.home() / ".claude" / ".credentials.json"))
MIN_INTERVAL, MAX_INTERVAL, RATE_LIMITED = 600, 3600, 1800

_token = {"value": None, "expires": 0.0}
_status = {"next": 0.0, "interval": MIN_INTERVAL, "error": ""}
_last = {"data": None, "at": 0.0}


def _read_credentials():
    if os.environ.get("OPS_CLAUDE_CREDENTIALS") or sys.platform != "darwin":
        try:
            return json.loads(CREDENTIALS_FILE.read_text())
        except (OSError, ValueError):
            return None
    try:
        r = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0 or not r.stdout.strip():
        return None
    try:
        return json.loads(r.stdout)
    except ValueError:
        return None


def token():
    """Claude Code's own OAuth access token, kept in memory only and never refreshed here."""
    now = time.time()
    if _token["value"] and _token["expires"] - 60 > now:
        return _token["value"], ""
    creds = _read_credentials()
    oauth = (creds or {}).get("claudeAiOauth") or {}
    value, expires = oauth.get("accessToken"), (oauth.get("expiresAt") or 0) / 1000
    if not value:
        _token.update(value=None, expires=0)
        return None, "Claude Code is not signed in here, or reading its credentials was not allowed"
    if expires and expires - 60 <= now:
        _token.update(value=None, expires=0)
        return None, "Claude Code's sign-in has expired — open Claude Code once to renew it"
    _token.update(value=value, expires=expires or now + 3600)
    return value, ""


def fetch():
    """Live usage from the endpoint Claude Code uses for Account & Usage. Returns (utilization, error)."""
    if time.time() < _status["next"]:
        return _last["data"], _status["error"]
    value, problem = token()
    if not value:
        _status.update(next=time.time() + MIN_INTERVAL, error=problem)
        return None, problem
    req = request.Request(
        f"{API}/api/oauth/usage",
        headers={"Authorization": f"Bearer {value}", "anthropic-beta": "oauth-2025-04-20", "Content-Type": "application/json", "User-Agent": "opsboard"},
    )
    try:
        with request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except error.HTTPError as exc:
        if exc.code in (401, 403):
            _token.update(value=None, expires=0)
        if exc.code == 429:
            _status["interval"] = min(MAX_INTERVAL, max(RATE_LIMITED, _status["interval"] * 2))
        problem = f"usage request failed (HTTP {exc.code})"
        _status.update(next=time.time() + _status["interval"], error=problem)
        return None, problem
    except (error.URLError, OSError, ValueError) as exc:
        problem = f"usage request failed ({exc.__class__.__name__})"
        _status.update(next=time.time() + _status["interval"], error=problem)
        return None, problem
    _status.update(interval=MIN_INTERVAL, next=time.time() + MIN_INTERVAL, error="")
    _last.update(data=data, at=time.time())
    return data, ""


def last_fetched():
    return _last["at"]


def reset():
    _token.update(value=None, expires=0)
    _status.update(next=0.0, interval=MIN_INTERVAL, error="")
    _last.update(data=None, at=0.0)
