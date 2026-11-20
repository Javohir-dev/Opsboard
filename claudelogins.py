"""Claude Code's own sign-ins: where each one is kept, whose it is, and what it has used.

One sign-in per account lives in its own config folder (Claude Code keeps that folder's credentials in the
Keychain under a name derived from the folder). The account in use is the one in Claude Code's default entry.
Values are passed between entries and never logged or returned to the page.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
import uuid
from pathlib import Path
from urllib import error, request

import safety
from core import DATA, claude_bin, epoch

API = os.environ.get("OPS_ANTHROPIC_URL", "https://api.anthropic.com").rstrip("/")
BASE = "Claude Code-credentials"
SLOTS = DATA / "claude-logins"
USAGE_EVERY, USAGE_BACKOFF = 900, 1800

_identity = {}
_usage = {}
_agent = {}


def main_json():
    return Path(os.environ.get("OPS_CLAUDE_JSON", Path.home() / ".claude.json"))


def main_file():
    return Path(os.environ.get("OPS_CLAUDE_CREDENTIALS", Path.home() / ".claude" / ".credentials.json"))


def keychain():
    return sys.platform == "darwin" and not os.environ.get("OPS_CLAUDE_CREDENTIALS") and bool(shutil.which("security"))


def slot_dir(slot):
    return SLOTS / slot


def service(slot=None):
    if slot is None:
        return BASE
    folder = unicodedata.normalize("NFC", str(slot_dir(slot)))
    return f"{BASE}-{hashlib.sha256(folder.encode()).hexdigest()[:8]}"


def _user():
    return os.environ.get("USER") or "claude-code-user"


def _security(args, stdin=None):
    try:
        return subprocess.run(["security", *args], input=stdin, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None


def read(slot=None):
    """The whole stored sign-in as a dict, or None."""
    if keychain():
        r = _security(["find-generic-password", "-a", _user(), "-s", service(slot), "-w"])
        raw = r.stdout.strip() if r and r.returncode == 0 else ""
        if not raw and slot is None:
            r = _security(["find-generic-password", "-s", service(), "-w"])
            raw = r.stdout.strip() if r and r.returncode == 0 else ""
    else:
        try:
            raw = (main_file() if slot is None else slot_dir(slot) / ".credentials.json").read_text()
        except OSError:
            raw = ""
    try:
        data = json.loads(raw) if raw else None
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def write(slot, data):
    raw = json.dumps(data, separators=(",", ":"))
    if keychain():
        safety.allow_keychain()
        line = f'add-generic-password -U -a "{_user()}" -s "{service(slot)}" -X "{raw.encode().hex()}"\n'
        r = _security(["-i"], stdin=line) if len(line) < 4000 else _security(["add-generic-password", "-U", "-a", _user(), "-s", service(slot), "-w", raw])
        if not r or r.returncode != 0:
            return False
    else:
        path = main_file() if slot is None else slot_dir(slot) / ".credentials.json"
        safety.allow_write(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(raw)
        os.replace(tmp, path)
    return (read(slot) or {}).get("claudeAiOauth") == data.get("claudeAiOauth")


def forget(slot):
    safety.allow_write(slot_dir(slot))
    safety.backup(slot_dir(slot), "claude-logins")
    if keychain():
        safety.allow_keychain()
        _security(["delete-generic-password", "-a", _user(), "-s", service(slot)])
    shutil.rmtree(slot_dir(slot), ignore_errors=True)


def oauth(slot=None):
    return (read(slot) or {}).get("claudeAiOauth") or {}


def put_oauth(slot, value):
    """Replace only the Claude sign-in inside an entry; whatever else Claude Code keeps there stays."""
    data = read(slot) or {}
    data["claudeAiOauth"] = value
    return write(slot, data)


def access(slot=None):
    """A usable access token, or (None, why)."""
    o = oauth(slot)
    if not o.get("accessToken"):
        return None, "not signed in"
    if o.get("expiresAt") and o["expiresAt"] / 1000 - 60 <= time.time():
        return None, "sign-in needs renewing"
    return o["accessToken"], ""


def _get(path, token, agent="opsboard"):
    req = request.Request(f"{API}{path}", headers={"Authorization": f"Bearer {token}", "anthropic-beta": "oauth-2025-04-20", "Content-Type": "application/json", "User-Agent": agent})
    with request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def cli_agent():
    """Claude Code's own client name: Anthropic lists limit resets only for it."""
    if "v" not in _agent:
        try:
            out = subprocess.run([claude_bin(), "--version"], capture_output=True, text=True, timeout=20).stdout
        except (OSError, subprocess.SubprocessError):
            out = ""
        found = re.search(r"\d+\.\d+\.\d+", out)
        _agent["v"] = found.group(0) if found else "2.1.328"
    return f"claude-cli/{_agent['v']} (external, cli)"


USAGE_PATH = "/api/oauth/usage?cedar_ember=1"
RESET_NAMES = {"five_hour": "Session", "seven_day": "Weekly", "seven_day_overage_included": "Fable"}


def parse_resets(data):
    """Limit resets Anthropic has granted this account: [{id, label, left, total, ends, clears, usable, why, used}]."""
    block = (data or {}).get("cedar_ember") or {}
    out = []
    for g in block.get("grants") or []:
        if not isinstance(g, dict) or not re.fullmatch(r"[a-z0-9_-]{1,40}", str(g.get("id") or "")) or not g.get("resets_total"):
            continue
        used = g.get("percent_used") or {}
        out.append({
            "id": g["id"],
            "label": str(g.get("label") or g["id"])[:160],
            "left": int(g.get("resets_left") or 0),
            "total": int(g.get("resets_total") or 0),
            "ends": int(epoch(g.get("ends_at") or "") or 0),
            "clears": [RESET_NAMES.get(k, k.replace("seven_day_", "Weekly ").replace("_", " ")) for k in g.get("clears") or []],
            "used": {RESET_NAMES.get(k, k): v for k, v in used.items() if isinstance(v, int)},
            "usable": bool(g.get("usable_now")) and not g.get("paused") and int(g.get("resets_left") or 0) > 0,
            "needs_limit": bool(g.get("use_requires_limit")),
            "keeps_week": bool(g.get("gives_back_weekly")),
            "why": str(g.get("unavailable_reason") or ""),
        })
    return out


def claim_reset(token, org, grant):
    """Spend one granted reset. Only ever called from the person's own confirmed click. Returns (ok, result, data)."""
    body = json.dumps({"program": "cedar_ember", "grant_id": grant, "request_id": uuid.uuid4().hex}).encode()
    req = request.Request(f"{API}/api/organizations/{org}/reset_rate_limits", data=body, method="POST", headers={"Authorization": f"Bearer {token}", "anthropic-beta": "oauth-2025-04-20", "Content-Type": "application/json", "User-Agent": cli_agent()})
    try:
        with request.urlopen(req, timeout=25) as resp:
            d = json.loads(resp.read().decode())
    except error.HTTPError as exc:
        return False, f"HTTP {exc.code}", {}
    except (error.URLError, OSError, ValueError) as exc:
        return False, exc.__class__.__name__, {}
    return d.get("result") == "reset", str(d.get("result") or "unavailable"), d if isinstance(d, dict) else {}


def identity(token):
    """Whose token this is, asked from Anthropic once per token: {uuid, email, name, org, plan} or None."""
    if not token:
        return None
    key = hashlib.sha256(token.encode()).hexdigest()
    if key not in _identity:
        try:
            d = _get("/api/oauth/profile", token)
        except (error.URLError, OSError, ValueError):
            return None
        acct, org = d.get("account") or {}, d.get("organization") or {}
        if not acct.get("uuid"):
            return None
        if len(_identity) > 50:
            _identity.clear()
        _identity[key] = {
            "uuid": acct["uuid"],
            "email": acct.get("email") or "",
            "name": acct.get("display_name") or acct.get("full_name") or "",
            "org": org.get("name") or "",
            "org_uuid": org.get("uuid") or "",
            "plan": str(org.get("organization_type") or "").replace("_", " ").title(),
        }
    return _identity[key]


def account_json(slot=None):
    try:
        return json.loads((main_json() if slot is None else slot_dir(slot) / ".claude.json").read_text()).get("oauthAccount") or {}
    except (OSError, ValueError):
        return {}


def put_account_json(slot, value):
    """Set oauthAccount in Claude Code's state file, leaving every other key as it is."""
    path = main_json() if slot is None else slot_dir(slot) / ".claude.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict) or data.get("oauthAccount") == value:
        return
    safety.allow_write(path)
    if slot is not None:
        safety.backup(path.parent, "claude-logins")
    data["oauthAccount"] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".opsboard.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def scoped(token, key, force=False):
    """Per-model weekly limits (Fable…) from the usage endpoint, at most every 15 minutes per account; the last answer otherwise."""
    st = _usage.setdefault(key, {"next": 0.0, "windows": {}, "at": 0.0})
    now = time.time()
    if token and (force or now >= st["next"]):
        try:
            d = _get(USAGE_PATH, token, cli_agent())
            st["resets"] = parse_resets(d)
            windows = {}
            for item in d.get("limits") or []:
                model = (((item.get("scope") or {}).get("model") or {}).get("display_name")) or ""
                if item.get("kind") == "weekly_scoped" and model:
                    resets = int(epoch(item.get("resets_at") or "") or 0)
                    windows["seven_day_" + model.lower().replace(" ", "_")] = {"percent": int(item.get("percent") or 0), "resets_at": resets, "status": item.get("severity") or "", "label": model}
            st.update(windows=windows, at=now, next=now + USAGE_EVERY)
        except error.HTTPError as exc:
            st["next"] = now + (USAGE_BACKOFF if exc.code == 429 else USAGE_EVERY)
        except (error.URLError, OSError, ValueError):
            st["next"] = now + 300
    return st["windows"]


def resets(key):
    return (_usage.get(key) or {}).get("resets") or []


def reset():
    _identity.clear()
    _usage.clear()
