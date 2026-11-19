import json
import os
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path

import config as cfg
import notify
from core import DATA, claude_bin, lock, log, put, state

SETTINGS = Path(os.environ.get("OPS_CLAUDE_SETTINGS", Path.home() / ".claude" / "settings.json"))
PROBE_HOME = DATA / "claude-probe"
ENV_KEY = "CLAUDE_CODE_OAUTH_TOKEN"
TOKEN_RE = re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")
ACTIVE_EVERY, IDLE_EVERY, FRESH = 180, 900, 1800
MAIN = "main"

_usage = {}
_probe_lock = threading.Lock()
_full = {"warned": False}
_refreshing = {"on": False}


def secret_key(aid):
    return f"claude.account.{aid}"


def enabled(aid):
    return aid not in (cfg.get("claude.disabled") or [])


def set_enabled(aid, on):
    if aid != MAIN and not any(a["id"] == aid for a in accounts()):
        raise ValueError("unknown account")
    off = [x for x in cfg.get("claude.disabled") or [] if x != aid] + ([] if on else [aid])
    cfg.set("claude.disabled", off or None, "user", "Accounts page")


def accounts():
    return [a for a in cfg.get("claude.accounts") or [] if isinstance(a, dict) and a.get("id")]


def _read_settings():
    try:
        data = json.loads(SETTINGS.read_text())
    except FileNotFoundError:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"{SETTINGS} is not a JSON object")
    return data


def active_id():
    try:
        token = str((_read_settings().get("env") or {}).get(ENV_KEY) or "")
    except ValueError:
        return "other"
    if not token:
        return MAIN
    return next((a["id"] for a in accounts() if cfg.secret(secret_key(a["id"])) == token), "other")


def switch(aid):
    """Claude Code reads env from its user settings for every new session — VS Code included."""
    data = _read_settings()
    env = dict(data.get("env") or {})
    if aid == MAIN:
        env.pop(ENV_KEY, None)
    else:
        token = cfg.secret(secret_key(aid)) if any(a["id"] == aid for a in accounts()) else ""
        if not token:
            raise ValueError("unknown account")
        env[ENV_KEY] = token
    if env:
        data["env"] = env
    else:
        data.pop("env", None)
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS.with_name(SETTINGS.name + ".opsboard.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, SETTINGS)
    log.info("claude account: switched to %s", aid)


def parse_probe(lines):
    """Windows from Claude Code's own rate_limit_event, in percent; an error string when the run failed."""
    windows, error = None, ""
    for line in lines:
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if msg.get("type") == "rate_limit_event":
            info = msg.get("rate_limit_info") or {}
            uni = info.get("unifiedWindows") or {}
            windows = {
                k: {"percent": round(float((uni.get(k) or {}).get("utilization") or 0) * 100), "resets_at": int((uni.get(k) or {}).get("resetsAt") or 0), "status": (uni.get(k) or {}).get("status") or ""}
                for k in ("five_hour", "seven_day")
                if k in uni
            }
            if not windows and info.get("rateLimitType") in ("five_hour", "seven_day"):
                windows = {info["rateLimitType"]: {"percent": 100 if info.get("status") == "rejected" else 0, "resets_at": int(info.get("resetsAt") or 0), "status": info.get("status") or ""}}
        elif msg.get("type") == "result" and msg.get("is_error") and not windows:
            error = str(msg.get("result") or msg.get("subtype") or "the request failed")[:200]
    return windows, error


def probe(aid):
    token = cfg.secret(secret_key(aid))
    if not token:
        return {"error": "no token saved", "at": time.time()}
    PROBE_HOME.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ANTHROPIC_", "CLAUDE_CODE_", "CLAUDE_CONFIG_DIR"))}
    env.update({ENV_KEY: token, "CLAUDE_CONFIG_DIR": str(PROBE_HOME)})
    cmd = [claude_bin(), "-p", "Reply with: ok", "--model", "haiku", "--output-format", "stream-json", "--verbose", "--max-turns", "1", "--tools", "", "--strict-mcp-config", "--no-session-persistence"]
    try:
        r = subprocess.run(cmd, cwd=PROBE_HOME, env=env, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"error": f"claude did not run ({exc.__class__.__name__})", "at": time.time()}
    windows, error = parse_probe(r.stdout.splitlines())
    if windows:
        return {"windows": windows, "at": time.time()}
    tail = (r.stderr.strip().splitlines() or [""])[-1]
    return {"error": (error or tail or f"no limits in the answer (exit {r.returncode})")[:200], "at": time.time()}


def main_usage():
    with lock:
        cu = dict(state.get("claude_usage") or {})
    windows = {}
    for lim in cu.get("limits") or []:
        k = {"session": "five_hour", "weekly_all": "seven_day"}.get(lim.get("kind"))
        if k:
            windows[k] = {"percent": int(lim.get("percent") or 0), "resets_at": int(lim.get("resets_at") or 0), "status": lim.get("severity") or ""}
    if not windows:
        return {"error": cu.get("live_error") or ("" if cfg.get("claude.live_usage") else "Live Claude usage is off"), "at": 0}
    return {"windows": windows, "at": cu.get("fetched") or 0}


def usage(aid):
    return main_usage() if aid == MAIN else _usage.get(aid) or {}


def level(u, now=None):
    now = now or time.time()
    vals = [w["percent"] for w in (u.get("windows") or {}).values() if not (w.get("resets_at") and w["resets_at"] < now)]
    return max(vals) if vals else (0 if u.get("windows") else None)


def busy():
    with lock:
        sessions = list(state.get("sessions") or [])
        runs = list(state.get("runs") or [])
    return any(s.get("status") == "busy" for s in sessions) or any(r.get("status") == "running" for r in runs)


def pick(current, now=None):
    now = now or time.time()
    below = int(cfg.get("claude.switch_to") or 60)
    pool = [MAIN] + [a["id"] for a in accounts()]
    cands = []
    for aid in pool:
        u = usage(aid)
        lv = level(u, now)
        if aid != current and enabled(aid) and lv is not None and lv < below and now - (u.get("at") or 0) < FRESH:
            cands.append((lv, aid))
    return min(cands)[1] if cands else None


def label(aid):
    return "Claude Code login" if aid == MAIN else next((a.get("label") or aid for a in accounts() if a["id"] == aid), aid)


def auto_switch():
    if not cfg.get("claude.auto_switch") or not accounts():
        return None
    current = active_id()
    if current == "other":
        return None
    lv = level(usage(current))
    if lv is None or lv < int(cfg.get("claude.switch_at") or 80):
        _full["warned"] = False
        return None
    if busy():
        return None
    target = pick(current)
    if target and target != MAIN:
        _usage[target] = probe(target)
        fresh = level(_usage[target])
        if fresh is None or fresh >= int(cfg.get("claude.switch_to") or 60):
            target = pick(current)
    if not target:
        if not _full["warned"]:
            _full["warned"] = True
            notify.claude_account({"kind": "claude_full", "from": label(current), "level": lv})
        return None
    switch(target)
    _full["warned"] = False
    notify.claude_account({"kind": "claude_switch", "from": label(current), "to": label(target), "level": lv, "to_level": level(usage(target))})
    return target


def public():
    current = active_id()
    now = time.time()
    rows = []
    for aid in [MAIN] + [a["id"] for a in accounts()]:
        u = usage(aid)
        rows.append({"id": aid, "label": label(aid), "active": aid == current, "enabled": enabled(aid), "windows": u.get("windows") or {}, "at": u.get("at") or 0, "error": u.get("error") or "", "level": level(u, now), "masked": cfg.masked(cfg.secret(secret_key(aid))) if aid != MAIN else ""})
    return {"active": current, "accounts": rows, "busy": busy(), "refreshing": _refreshing["on"], "settings": str(SETTINGS).replace(str(Path.home()), "~", 1)}


def collect():
    current = active_id()
    now = time.time()
    if _probe_lock.acquire(blocking=False):
        try:
            for a in accounts():
                due = ACTIVE_EVERY if a["id"] == current else IDLE_EVERY
                if now - (_usage.get(a["id"]) or {}).get("at", 0) >= due:
                    _usage[a["id"]] = probe(a["id"])
        finally:
            _probe_lock.release()
    try:
        auto_switch()
    except (OSError, ValueError) as exc:
        log.warning("claude account: auto switch failed: %s", exc)
    put("claude_accounts", public())


def add(name, token):
    name, token = str(name or "").strip()[:40], str(token or "").strip()
    if not name:
        raise ValueError("give the account a name")
    if not TOKEN_RE.fullmatch(token):
        raise ValueError("this does not look like a token from claude setup-token")
    if any(cfg.secret(secret_key(a["id"])) == token for a in accounts()):
        raise ValueError("this token is already added")
    aid = uuid.uuid4().hex[:8]
    cfg.set_secret(secret_key(aid), token)
    result = probe(aid)
    if not result.get("windows"):
        cfg.set_secret(secret_key(aid), "")
        raise ValueError(f"Claude did not accept this token: {result.get('error')}")
    _usage[aid] = result
    cfg.set("claude.accounts", accounts() + [{"id": aid, "label": name}], "user", "Settings page")
    put("claude_accounts", public())
    return aid


def remove(aid):
    if not any(a["id"] == aid for a in accounts()):
        raise ValueError("unknown account")
    if active_id() == aid:
        switch(MAIN)
    set_enabled(aid, True)
    cfg.set("claude.accounts", [a for a in accounts() if a["id"] != aid] or None, "user", "Settings page")
    cfg.set_secret(secret_key(aid), "")
    _usage.pop(aid, None)
    put("claude_accounts", public())


def refresh_all():
    """Every account at once, in the background; the page shows a spinner until it is done."""
    if _refreshing["on"]:
        return
    _refreshing["on"] = True
    put("claude_accounts", public())

    def run():
        try:
            import system

            system.collect_claude_usage()
            with _probe_lock:
                for a in accounts():
                    _usage[a["id"]] = probe(a["id"])
        finally:
            _refreshing["on"] = False
            put("claude_accounts", public())

    threading.Thread(target=run, daemon=True, name="claude-accounts-refresh").start()
