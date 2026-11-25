"""Claude Code sessions that wait for the user (a permission prompt or a question) and get no answer are reported to Telegram.
A permission request held by the PermissionRequest hook can also be allowed or denied from there."""

import json
import os
import secrets
import threading
import time
from pathlib import Path

import config as cfg
from core import log

SESSIONS = Path(os.environ.get("OPS_CLAUDE_SESSIONS", Path.home() / ".claude" / "sessions"))
GRACE = 20
HOLD = 30 * 60
KINDS = {"permission_request", "question_request", "permission_prompt", "elicitation_dialog", "question", "idle_prompt"}
NOW = KINDS - {"idle_prompt"}
HELD = {"permission_request", "question_request"}
ON_NEW = None
_waiting, _decided, _lock = {}, {}, threading.Lock()


def _mtime(path):
    if not path:
        return None
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
    """Returns False when ignored, True when noted, or the request id a permission_request hook polls with."""
    sid, kind = str(ev.get("session_id") or ""), str(ev.get("type") or "")
    if not sid or kind not in KINDS or not cfg.get("telegram.claude_wait"):
        return False
    if kind == "idle_prompt" and not cfg.get("telegram.claude_wait_idle"):
        return False
    with _lock:
        cur = _waiting.get(sid)
        if cur and cur.get("req") and kind != "permission_request":
            return True
        if cur and cur["kind"] != "idle_prompt" and kind == "idle_prompt":
            return True
        req = secrets.token_hex(4) if kind in HELD else None
        questions = [q for q in (ev.get("questions") or []) if isinstance(q, dict)][:4] if kind == "question_request" else []
        _waiting[sid] = {
            "kind": kind,
            "at": time.time(),
            "cwd": str(ev.get("cwd") or ""),
            "transcript": str(ev.get("transcript_path") or ""),
            "message": str(ev.get("message") or "")[:600],
            "base": None,
            "req": req,
            "questions": questions,
            "answers": {},
            "cockpit": bool(ev.get("cockpit")),
            "alerted": kind in NOW and ON_NEW is not None,
        }
        item = dict(_waiting[sid], sid=sid)
    log.info("claude wait: %s %s in %s", kind, sid[:8], ev.get("cwd") or "?")
    if item["alerted"]:
        threading.Thread(target=_alert_now, args=(item, ON_NEW), daemon=True).start()
    return req or True


def _alert_now(item, notify):
    meta = _session(item["sid"]) or {}
    if meta.get("entrypoint") in ("sdk-cli", "background") and not item.get("cockpit"):
        return
    try:
        notify(dict(item, name=meta.get("name") or "", minutes=0))
    except Exception:  # noqa: BLE001
        log.exception("claude wait alert failed")


def answer(req, index, text):
    """One question of a held AskUserQuestion answered from Telegram; returns (done, entry) or None when it is closed."""
    with _lock:
        sid = next((s for s, w in _waiting.items() if w.get("req") == req and w["kind"] == "question_request"), None)
        if not sid:
            return None
        w = _waiting[sid]
        qs = w["questions"]
        if not 0 <= index < len(qs):
            raise ValueError("unknown question")
        w["answers"][str(qs[index].get("question") or "")] = str(text)[:2000]
        done = len(w["answers"]) >= len(qs)
        if done:
            _waiting.pop(sid)
            _decided[req] = {"behavior": "allow", "answers": w["answers"]}
        return done, dict(w)


def decide(req, behavior, message=""):
    """A Telegram button answered a held permission request; False when it was already answered or expired."""
    if behavior not in ("allow", "deny"):
        raise ValueError("unknown decision")
    with _lock:
        sid = next((s for s, w in _waiting.items() if w.get("req") == req), None)
        if not sid:
            return False
        _waiting.pop(sid)
        _decided[req] = {"behavior": behavior, "message": str(message or "")[:2000]}
    log.info("claude wait: %s %s from Telegram", req, behavior)
    return True


def poll(req):
    with _lock:
        if req in _decided:
            d = _decided.pop(req)
            return {"decision": d["behavior"], "answers": d.get("answers"), "message": d.get("message") or ""}
        return {"decision": None, "open": any(w.get("req") == req for w in _waiting.values())}


def check(now=None, send=None, closed=None):
    now = now or time.time()
    if not cfg.get("telegram.claude_wait"):
        with _lock:
            _waiting.clear()
        return []
    wait = max(1, int(cfg.get("telegram.claude_wait_minutes") or 5)) * 60
    due, gone = [], []
    with _lock:
        for sid, w in list(_waiting.items()):
            seen = _mtime(w["transcript"])
            if w["base"] is None:
                if now - w["at"] >= GRACE:
                    w["base"] = seen
                continue
            if seen != w["base"] or (w["alerted"] and now - w["at"] > HOLD):
                gone.append(_waiting.pop(sid))
                log.info("claude wait: %s answered", sid[:8])
                continue
            if not w["alerted"] and now - w["at"] >= wait:
                if w.get("req"):
                    w["alerted"] = True
                    due.append((sid, dict(w)))
                else:
                    due.append((sid, _waiting.pop(sid)))
    for w in gone:
        if w.get("alerted") and closed:
            try:
                closed(w)
            except Exception:  # noqa: BLE001
                log.exception("claude wait close failed")
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


def pending_answers(req):
    with _lock:
        w = next((w for w in _waiting.values() if w.get("req") == req), None)
        return dict(w["answers"]) if w else None


def public():
    """What the Cockpit page shows: every session waiting for the user, oldest first."""
    home = str(Path.home())
    with _lock:
        items = [dict(w, sid=sid) for sid, w in _waiting.items()]
    out = []
    for w in sorted(items, key=lambda x: x["at"]):
        meta = _session(w["sid"]) or {}
        if meta.get("entrypoint") in ("sdk-cli", "background") and not w.get("req") and not w.get("cockpit"):
            continue
        out.append({
            "sid": w["sid"], "req": w.get("req"), "kind": w["kind"], "at": w["at"], "message": w["message"],
            "questions": w.get("questions") or [], "answers": w.get("answers") or {},
            "cwd": (w["cwd"] or "").replace(home, "~", 1), "name": meta.get("name") or "", "where": meta.get("entrypoint") or "",
        })
    return out


def pending():
    with _lock:
        return {k: dict(v) for k, v in _waiting.items()}
