"""Claude Code sessions that wait for the user (a permission prompt or a question) and get no answer are reported to Telegram."""

import json
import os
import threading
import time
from pathlib import Path

import config as cfg
from core import log

SESSIONS = Path(os.environ.get("OPS_CLAUDE_SESSIONS", Path.home() / ".claude" / "sessions"))
GRACE = 20
KINDS = {"permission_prompt", "elicitation_dialog", "question", "idle_prompt"}
_waiting, _lock = {}, threading.Lock()


def _mtime(path):
    try:
        return Path(path).stat().st_mtime
    except (OSError, TypeError):
        return None


def _session(sid):
    for f in SESSIONS.glob("*.json"):
        try:
            meta = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if meta.get("sessionId") == sid:
            return meta
    return None


def report(ev):
    sid, kind = str(ev.get("session_id") or ""), str(ev.get("type") or "")
    if not sid or kind not in KINDS:
        return False
    if kind == "idle_prompt" and not cfg.get("telegram.claude_wait_idle"):
        return False
    with _lock:
        if sid in _waiting and _waiting[sid]["kind"] != "idle_prompt" and kind == "idle_prompt":
            return True
        _waiting[sid] = {
            "kind": kind,
            "at": time.time(),
            "cwd": str(ev.get("cwd") or ""),
            "transcript": str(ev.get("transcript_path") or ""),
            "message": str(ev.get("message") or "")[:600],
            "base": None,
        }
    log.info("claude wait: %s %s in %s", kind, sid[:8], ev.get("cwd") or "?")
    return True


def check(now=None, send=None):
    now = now or time.time()
    if not cfg.get("telegram.claude_wait"):
        with _lock:
            _waiting.clear()
        return []
    wait = max(1, int(cfg.get("telegram.claude_wait_minutes") or 5)) * 60
    due = []
    with _lock:
        for sid, w in list(_waiting.items()):
            seen = _mtime(w["transcript"])
            if w["base"] is None:
                if now - w["at"] >= GRACE:
                    w["base"] = seen
                continue
            if seen != w["base"]:
                _waiting.pop(sid)
                log.info("claude wait: %s answered", sid[:8])
                continue
            if now - w["at"] >= wait:
                due.append((sid, _waiting.pop(sid)))
    sent = []
    for sid, w in due:
        meta = _session(sid)
        if meta is None or meta.get("entrypoint") in ("sdk-cli", "background"):
            continue
        item = dict(w, sid=sid, name=meta.get("name") or "", minutes=int((now - w["at"]) // 60))
        log.info("claude wait: alert for %s after %s min", sid[:8], item["minutes"])
        if send:
            try:
                send(item)
            except Exception:  # noqa: BLE001
                log.exception("claude wait alert failed")
        sent.append(item)
    return sent


def pending():
    with _lock:
        return {k: dict(v) for k, v in _waiting.items()}
