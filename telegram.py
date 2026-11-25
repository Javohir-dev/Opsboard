import html
import json
import os
import platform
import random
import re
import secrets
import signal
import socket
import subprocess
import threading
import time
from pathlib import Path
from urllib import error, request

import claudeaccounts
import config as cfg
import notify
from core import DATA, claude_bin, lock, log, project_root, state

API = os.environ.get("OPS_TELEGRAM_API", "https://api.telegram.org").rstrip("/")
PAIR_TTL = 15 * 60
CHAT_TIMEOUT = 20 * 60
CHAT_FILE = DATA / "telegram-chat.json"
PIPE_ICON = {"success": "🟢", "failed": "🔴", "running": "🔵", "pending": "🟡", "canceled": "⚪", "skipped": "⚪", "manual": "🟡", "created": "🟡"}

_status = {"bot": "", "error": "", "running": False}
_pair = {"code": "", "until": 0.0}
_boot = time.time()
esc = html.escape
WIDGET_HANDLERS = []
REPLY_HOOKS = []
MR_AGENTS = []
WIDGETS = Path(__file__).resolve().parent / "widgets"
LIVE_FILE = DATA / "telegram-live.json"
LIVE_TTL = 24 * 3600
LIVE = {}
EXTRA_COMMANDS = {}
_live_lock = threading.Lock()


class TelegramError(Exception):
    pass


def call(method, token=None, http_timeout=15, **params):
    tok = token or cfg.secret("telegram.token")
    if not tok:
        raise TelegramError("no Telegram token")
    body = json.dumps({k: v for k, v in params.items() if v is not None}).encode()
    req = request.Request(f"{API}/bot{tok}/{method}", data=body, headers={"Content-Type": "application/json"})
    try:
        with request.urlopen(req, timeout=http_timeout) as resp:
            out = json.loads(resp.read().decode())
    except error.HTTPError as exc:
        try:
            out = json.loads(exc.read().decode())
        except (ValueError, OSError):
            raise TelegramError(f"Telegram answered {exc.code}") from None
    except (error.URLError, OSError, ValueError) as exc:
        raise TelegramError(f"cannot reach Telegram ({exc.__class__.__name__})") from None
    if not out.get("ok"):
        raise TelegramError(str(out.get("description") or "Telegram error")[:200])
    return out["result"]


def connected(bot):
    _status.update(bot=bot, running=True, error="")
    _pair.update(code="", until=0)


def chat_id():
    value = cfg.get("telegram.chat_id")
    return int(value) if str(value or "").lstrip("-").isdigit() else None


def pair_code():
    if not _pair["code"] or time.time() > _pair["until"]:
        _pair.update(code=secrets.token_hex(4), until=time.time() + PAIR_TTL)
    return _pair["code"]


def public():
    configured = bool(cfg.secret("telegram.token"))
    out = {
        "configured": configured,
        "bot": _status["bot"],
        "running": _status["running"],
        "error": _status["error"],
        "linked": bool(chat_id()),
        "user": cfg.get("telegram.user") or "",
        "chat_busy": CHAT.busy,
    }
    if configured and not out["linked"] and _status["bot"]:
        out["code"] = pair_code()
        out["link"] = f"https://t.me/{_status['bot']}?start={out['code']}"
    return out


_notes, _notes_lock, _origins = [], threading.Lock(), {}
NOTES_KEEP, NOTES_SPAN = 20, 3 * 3600


def _remember(text):
    plain = html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()
    if plain:
        with _notes_lock:
            _notes.append((time.time(), plain[:1500]))
            del _notes[:-NOTES_KEEP]


def send_file(path, caption="", origin=""):
    """A file another Claude Code session sends through the bot; the chat later knows which session sent it."""
    path = Path(path)
    target = chat_id()
    if not target or not path.is_file():
        return None
    boundary = secrets.token_hex(12)
    parts = [f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{target}\r\n".encode()]
    if caption:
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n{caption[:1000]}\r\n".encode())
    parts += [f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; filename=\"{path.name}\"\r\n\r\n".encode(), path.read_bytes(), f"\r\n--{boundary}--\r\n".encode()]
    req = request.Request(f"{API}/bot{cfg.secret('telegram.token')}/sendDocument", data=b"".join(parts), headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with request.urlopen(req, timeout=60) as resp:
            out = json.loads(resp.read().decode())
    except (error.URLError, OSError, ValueError) as exc:
        log.warning("telegram file send failed: %s", exc.__class__.__name__)
        return None
    msg = out.get("result") if out.get("ok") else None
    if msg:
        _remember(f"[file {path.name} sent by session {origin or '?'}] {caption}")
        with _notes_lock:
            _origins[msg["message_id"]] = origin or "?"
            while len(_origins) > 200:
                _origins.pop(next(iter(_origins)))
    return msg


def send_text(text, origin=""):
    if not text.strip():
        return None
    msg = send(md_to_html(text))
    if msg:
        _remember(f"[message from session {origin or '?'}] {text}")
        with _notes_lock:
            _origins[msg["message_id"]] = origin or "?"
    return msg


def _live_sessions():
    """One line per running Claude Code session, so the chat can tell which one a message is about."""
    with lock:
        rows = list(state.get("sessions") or [])
    home = str(Path.home())
    out = []
    for x in rows[:15]:
        cwd = str(x.get("cwd") or "")
        folder = re.sub(r"[^A-Za-z0-9]", "-", cwd)
        name = x.get("title") or x.get("name") or ""
        if x.get("name") and x.get("name") != name:
            name = f"{name} ({x['name']})"
        status = "working" if x.get("status") == "busy" else "idle"
        prompt = re.sub(r"\s+", " ", str(x.get("last_prompt") or ""))[:120]
        out.append(f"- {name} · {status} · {cwd.replace(home, '~', 1)} · {x.get('entrypoint') or ''} · "
                   f"transcript ~/.claude/projects/{folder}/{x.get('id')}.jsonl" + (f" · last prompt: {prompt}" if prompt else ""))
    return "\n".join(out)


def recent_notes(since):
    with _notes_lock:
        return [(t, x) for t, x in _notes if t > since and t > time.time() - NOTES_SPAN]


def send(text, buttons=None, chat=None, plain=False, reply_to=None, note=False):
    target = chat or chat_id()
    if not target:
        return None
    if note:
        _remember(text)
    params = {"chat_id": target, "text": text[:4096], "disable_web_page_preview": True, "reply_markup": {"inline_keyboard": buttons} if buttons else None}
    if reply_to:
        params["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
    if not plain:
        params["parse_mode"] = "HTML"
    try:
        return call("sendMessage", **params)
    except TelegramError as exc:
        log.warning("telegram send failed: %s", exc)
        return None


def _mrs():
    with lock:
        return [m for m in (state.get("review") or {}).get("mrs", []) if m.get("state") == "opened"]


def _mr(iid):
    with lock:
        return next((m for m in (state.get("review") or {}).get("mrs", []) if m["iid"] == iid), None)


def _ref(iid):
    return ("#" if cfg.get("review.host") == "github" else "!") + str(iid)


def _host():
    return "GitHub" if cfg.get("review.host") == "github" else "GitLab"


def _url_button(text, url):
    return [{"text": text, "url": url}] if url and url.startswith("https://") else []


def _dur(s):
    s = max(0, int(s))
    return f"{s}s" if s < 60 else f"{s // 60}m" if s < 3600 else f"{s / 3600:.1f}h"


def mr_agent(m):
    import runs

    run = next((r for r in runs.load_runs() if r.get("iid") == m["iid"] and r["status"] == "running"), None)
    if run:
        return {"who": cfg.get("claude.fix_skill") or "fix", "since": run.get("started") or 0, "fix": True}
    for hook in MR_AGENTS:
        try:
            hit = hook(m)
        except Exception:  # noqa: BLE001
            log.exception("mr agent hook failed")
            hit = None
        if hit:
            return hit
    return None


def _hex(c):
    c = str(c or "").lstrip("#")
    return c.lower() if re.fullmatch(r"[0-9a-fA-F]{6}", c) else ""


def _recent_done(n=3):
    with lock:
        mrs = [m for m in (state.get("review") or {}).get("mrs", []) if m.get("state") in ("merged", "closed")]
    return sorted(mrs, key=lambda m: -(m.get("merged") or m.get("closed") or m.get("updated") or 0))[:n]


def mrs_data(limit=6):
    mrs = _mrs()
    with lock:
        colors = dict((state.get("review") or {}).get("labels") or {})
        jira = {i["key"]: i.get("status", "") for i in (state.get("jira") or {}).get("issues") or []}
        aliases = dict(state.get("key_aliases") or {})
    rows = []
    for m in mrs:
        flags = (1 if m.get("approved") else 0) | (2 if m.get("conflicts") else 0) | (4 if m.get("role") == "assignee" else 0) | (8 if m.get("draft") else 0)
        labels = [[n, _hex((colors.get(n) or {}).get("color")) or "6b7280", _hex((colors.get(n) or {}).get("text")) or "ffffff"] for n in m.get("labels") or []]
        key = (m.get("keys") or [""])[0]
        status = jira.get(aliases.get(key, key), "")
        agent = mr_agent(m) or {}
        rows.append([m["iid"], m["title"], m.get("pipeline") or "", m.get("threads") or 0, m.get("threads_total") or 0, flags, labels, f"{key} · {status}" if key and status else key, agent.get("who", ""), int(agent.get("since") or 0), 1 if agent.get("fix") else 0])
    base = mrs[0]["url"].rsplit("/", 1)[0] + "/" if mrs and mrs[0].get("url", "").startswith("https://") else ""
    head = {"h": _ref(0)[0], "b": base, "n": len(rows), "t": int(time.time())}
    if not rows:
        done = _recent_done()
        if done and done[0].get("url", "").startswith("https://"):
            head["b"] = done[0]["url"].rsplit("/", 1)[0] + "/"
        head["r"] = [[m["iid"], m["title"] if len(m["title"]) <= 60 else m["title"][:59].rstrip() + "…", 1 if m["state"] == "merged" else 0, int(m.get("merged") or m.get("closed") or m.get("updated") or 0)] for m in done]
    for keep in range(min(limit, len(rows)), -1, -1):
        for width in (90, 60, 40):
            out = json.dumps(dict(head, l=[[r[0], r[1] if len(r[1]) <= width else r[1][: width - 1].rstrip() + "…", *r[2:]] for r in rows[:keep]]), ensure_ascii=False, separators=(",", ":"))
            if len(out.encode()) <= 1024:
                return out
    return json.dumps(dict(head, l=[]))


def register_live(name, source, data, caption, action=None):
    LIVE[name] = {"html": Path(source), "data": data, "caption": caption, "action": action}


def _live_state():
    try:
        return json.loads(LIVE_FILE.read_text())
    except (OSError, ValueError):
        return {}


def _save_live_state(st):
    tmp = LIVE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st))
    os.replace(tmp, LIVE_FILE)


def send_live(name):
    w = LIVE[name]
    data = w["data"]()
    msg = send_widget(w["html"].read_text(encoding="utf-8"), w["caption"](), data)
    if not msg:
        return None
    with _live_lock:
        st = _live_state()
        if (st.get(name) or {}).get("mid"):
            delete(st[name]["mid"])
        st[name] = {"mid": msg["message_id"], "data": data, "at": time.time()}
        _save_live_state(st)
    return msg


def _content(data):
    try:
        return {k: v for k, v in json.loads(data or "{}").items() if k != "t"}
    except ValueError:
        return None


def refresh_live(name, force=False):
    with _live_lock:
        st = _live_state()
        cur = st.get(name)
        if name not in LIVE or not cur or time.time() - cur.get("at", 0) > LIVE_TTL:
            return False
        data = LIVE[name]["data"]()
        if not force and _content(data) == _content(cur.get("data")):
            return True
        if edit_widget(cur["mid"], data):
            cur["data"] = data
            _save_live_state(st)
            return True
        return False


def on_live_widget(q):
    with _live_lock:
        st = _live_state()
    name = next((n for n, c in st.items() if n in LIVE and c.get("mid") == q.get("message_id")), None)
    if not name:
        return None
    data = q.get("data") or ""
    if data == "u":
        return "ok" if refresh_live(name, force=True) else "Could not update"
    action = LIVE[name]["action"]
    out = action(data) if action else "Unknown action"
    refresh_live(name)
    return out


def mrs_action(data):
    kind, _, rest = data.partition(":")
    iid, _, flags = rest.partition(":")
    if kind != "f" or not iid.isdigit() or not any(m["iid"] == int(iid) for m in _mrs()):
        return "Unknown action"
    try:
        _, busy = _launch_fix(int(iid), True, "s" in flags)
    except (ValueError, OSError) as exc:
        return str(exc)[:190]
    return busy or "ok"


def _claude_usage():
    import system

    with lock:
        usage = dict(state.get("claude_usage") or {})
    if not (cfg.get("claude.live_usage") and usage.get("limits")):
        usage = system.claude_usage(live=False) or {}
    return _active_usage() or usage


def _active_usage():
    """Limits of the account new sessions use, when that is a setup-token account and not Claude Code's own sign-in."""
    import claudeaccounts as ca

    aid = ca.active_id()
    if aid == ca.MAIN or aid == ca.twin() or ca.signed_in(aid):
        return None
    u = ca.usage(aid)
    names = {"five_hour": "Session (5hr)", "seven_day": "Weekly (7 day)"}
    limits = [
        {"label": names.get(k) or f"Weekly {w.get('label') or k}", "kind": k, "percent": int(w.get("percent") or 0), "severity": "critical" if "rejected" in str(w.get("status")) else "warning" if "warning" in str(w.get("status")) else "normal", "resets_at": int(w.get("resets_at") or 0)}
        for k, w in (u.get("windows") or {}).items()
    ]
    return {"limits": limits, "fetched": u.get("at") or 0, "account": {"email": ca.label(aid), "org": "setup token"}, "source": "account", "live_error": u.get("error") or ""}


def usage_data():
    u = _claude_usage()
    acct = u.get("account") or {}
    limits = [[lim["label"], 0 if lim.get("resets_at") and lim["resets_at"] < time.time() else lim["percent"], int(lim.get("resets_at") or 0), lim.get("severity") or ""] for lim in u.get("limits") or []]
    d = {"e": acct.get("email") or "", "o": acct.get("org") or "", "l": limits, "s": u.get("source") or "", "f": int(u.get("fetched") or 0), "x": (u.get("live_error") or "")[:160], "t": int(time.time())}
    return json.dumps(d, ensure_ascii=False, separators=(",", ":"))


def usage_caption():
    limits = _claude_usage().get("limits") or []
    return "<b>Claude usage</b>" + "".join(f" · {esc(lim['label'].split(' (')[0])} {lim['percent']}%" for lim in limits[:2])


def live_loop():
    while True:
        time.sleep(20)
        if not chat_id():
            continue
        for name in list(LIVE):
            try:
                refresh_live(name)
            except Exception:  # noqa: BLE001
                log.exception("live widget %s refresh failed", name)


register_live("mrs", WIDGETS / "mrs.html", lambda: mrs_data(), lambda: f"<b>Open requests</b> · {len(_mrs())}" if _mrs() else "✅ <b>No open requests</b> — all merged or closed", mrs_action)
register_live("usage", WIDGETS / "usage.html", usage_data, usage_caption)


def help_text():
    extra = "".join(f"\n/{k} — {esc(v[0][:1].lower() + v[0][1:])}" for k, v in EXTRA_COMMANDS.items())
    chat = "\n\nAny other message goes to Claude on your Mac. /new starts a fresh conversation, /cancel stops the current answer." if cfg.get("telegram.claude_chat") else ""
    return f"<b>Opsboard</b>\n/mrs — your open requests\n/mr 7376 — one request\n/sessions — Claude sessions that are working, with their agents\n/usage — Claude plan limits and when they reset\n/info — linked accounts, this Mac and the bot's settings{extra}{chat}"


def cmd_mrs():
    mrs = _mrs()
    if not mrs:
        done = _recent_done()
        lines = ["✅ <b>No open requests</b>", "Everything is merged or closed."]
        if done:
            lines += ["", "<b>Recently finished</b>"] + [f"{'🟣' if m['state'] == 'merged' else '⚪'} <b>{_ref(m['iid'])}</b> {esc(m['title'][:70])} · {m['state']} {_dur(time.time() - (m.get('merged') or m.get('closed') or m.get('updated') or time.time()))} ago" for m in done]
        return "\n".join(lines), None
    lines, buttons = ["<b>Open requests</b>"], []
    for m in mrs[:20]:
        th = f" · 💬 {m['threads'] or 0} open of {m['threads_total']}" if m.get("threads_total") else ""
        lines.append(
            f"{PIPE_ICON.get(m.get('pipeline'), '⚪')} <b>{_ref(m['iid'])}</b> {esc(m['title'][:100])}{th}{' · ✅ approved' if m.get('approved') else ''}{' · ⚠️ conflict' if m.get('conflicts') else ''}"
        )
        buttons.append({"text": _ref(m["iid"]), "callback_data": f"mr:{m['iid']}"})
    return "\n\n".join(lines), [buttons[i : i + 4] for i in range(0, len(buttons), 4)]


def cmd_mr(iid):
    m = _mr(iid)
    if not m:
        return f"{_ref(iid)} is not one of your requests.", None
    lines = [
        f"<b>{_ref(iid)}</b> {esc(m['title'])}",
        f"<code>{esc(m.get('source', ''))}</code> → <code>{esc(m.get('target', ''))}</code>",
        f"{PIPE_ICON.get(m.get('pipeline'), '⚪')} pipeline {esc(m.get('pipeline') or 'none')}",
        "✅ approved by " + esc(", ".join(m["approved_by"])) if m.get("approved") else "⏳ not approved yet",
    ]
    if m.get("threads_total"):
        lines.append(f"💬 {m['threads'] or 0} open of {m['threads_total']} threads")
    if m.get("conflicts"):
        lines.append("⚠️ merge conflict")
    link = _url_button(f"Open in {_host()}", m.get("url"))
    return "\n".join(lines), [link] if link else None


def cmd_sessions():
    with lock:
        sessions = list(state.get("sessions") or [])
    busy = [s for s in sessions if s.get("status") == "busy"]
    lines = [f"<b>Claude sessions</b> · {len(busy)} working · {len(sessions) - len(busy)} idle"]
    for s in sorted(busy, key=lambda x: -(x.get("status_since") or 0)):
        agents = [a for a in s.get("agents") or [] if isinstance(a, dict) and a.get("status") == "running"]
        jobs = [j for j in s.get("jobs") or [] if isinstance(j, dict) and j.get("status") in (None, "running")]
        doing = s.get("doing") or {}
        since = s.get("status_since") or s.get("started") or time.time()
        bits = [
            f"🤖 {len(agents)} agent{'s' if len(agents) != 1 else ''} running" if agents else "no agents",
            f"⚙️ {len(jobs)} background job{'s' if len(jobs) != 1 else ''}" if jobs else "",
            f"⏱ {_dur(time.time() - since)}",
        ]
        block = f"🟢 <b>{esc(s.get('title') or s.get('name') or '')}</b>\n<code>{esc(Path(s.get('cwd') or '').name)}</code>{(' · ' + esc(s['branch'])) if s.get('branch') else ''}\n" + " · ".join(
            b for b in bits if b
        )
        if doing:
            block += f"\n▸ {esc(str(doing.get('tool', '')))}: {esc(str(doing.get('what', ''))[:120])}"
        block += "".join(f"\n   • {esc(a.get('description') or a.get('type') or 'agent')}" for a in agents[:8])
        lines.append(block)
    if not busy:
        lines.append("Nothing is working right now.")
    return "\n\n".join(lines), None


def _claude_account():
    import system

    try:
        acct = json.loads(system.CLAUDE_STATE.read_text()).get("oauthAccount") or {}
    except (OSError, ValueError):
        return {}
    return {"email": acct.get("emailAddress") or "", "org": acct.get("organizationName") or "", "plan": str(acct.get("organizationType") or "").replace("_", " ").title()}


def cmd_info():
    with lock:
        mac = dict(state.get("mac") or {})
        version = dict(state.get("version") or {})
        review = dict(state.get("review") or {})
        jira = dict((state.get("jira") or {}).get("account") or {})
        tracker_err = (state.get("jira") or {}).get("error")
        usage = list((state.get("claude_usage") or {}).get("limits") or [])
    gh = cfg.get("review.host") == "github"
    host_url = (cfg.get("github.url") if gh else cfg.get("gitlab.url")) or ""
    project = (cfg.get("github.repo") if gh else cfg.get("gitlab.project")) or ""
    host_user = review.get("user") or cfg.get("github.username" if gh else "gitlab.username") or ""
    acct = _claude_account()
    chat = _load_chat()
    root = project_root()
    lines = [
        "<b>Opsboard</b>",
        f"🖥 {esc(socket.gethostname().removesuffix('.local'))} · {esc(mac.get('chip') or platform.machine())} · {esc(mac.get('os') or platform.system())}",
        f"📦 v{esc(version.get('current') or '?')}{' · ⬆️ ' + esc(version['latest']) + ' available' if version.get('update') else ''} · up {_dur(time.time() - _boot)}",
        "",
        "<b>Telegram</b>",
        f"👤 linked to @{esc(cfg.get('telegram.user') or '?')} (chat {chat_id()})",
        f"🤖 bot @{esc(_status['bot'])}",
        f"🔔 new thread notifications {'on' if cfg.get('telegram.notify') else 'off'}",
        f"💬 Claude chat {'on — ' + esc(PERMISSIONS.get(cfg.get('telegram.chat_permission') or 'plan', '')) if cfg.get('telegram.claude_chat') else 'off'}"
        + (f" · conversation since {time.strftime('%d %b %H:%M', time.localtime(chat['at']))}" if cfg.get("telegram.claude_chat") and chat.get("session_id") and chat.get("at") else ""),
        "",
        f"<b>{'GitHub' if gh else 'GitLab'}</b>",
        f"🌐 {esc(host_url.removeprefix('https://'))} · <code>{esc(project)}</code>" if host_url or project else "🌐 not set up",
        f"👤 {esc(host_user)}" + (f" · ⚠️ {esc(review['error'][:120])}" if review.get("error") else "") if host_user or review.get("error") else "",
        f"🔀 {sum(1 for m in review.get('mrs') or [] if m.get('state') == 'opened')} open request(s)" if review.get("mrs") is not None else "",
    ]
    if cfg.get("jira.site"):
        lines += [
            "",
            "<b>Jira</b>",
            f"🌐 {esc(cfg.get('jira.site').removeprefix('https://'))}",
            f"👤 {esc(jira.get('name') or cfg.get('jira.name') or '')} · {esc(jira.get('email') or cfg.get('jira.email') or '')}" + (f" · ⚠️ {esc(tracker_err[:120])}" if tracker_err else ""),
        ]
    lines += ["", "<b>Claude</b>"]
    if acct.get("email"):
        lines.append(f"👤 {esc(acct['email'])}" + (f" · {esc(acct['org'])}" if acct.get("org") else "") + (f" · {esc(acct['plan'])}" if acct.get("plan") else ""))
    lines.append(f"🧰 Claude Code {esc(cfg.get('claude.version') or '?')}" + (f" · fix skill <code>{esc(cfg.get('claude.fix_skill'))}</code>" if cfg.get("claude.fix_skill") else ""))
    for lim in usage:
        if not lim.get("resets_at") or lim["resets_at"] > time.time():
            lines.append(f"📊 {esc(lim['label'])}: {lim['percent']}%")
    lines += [
        "",
        "<b>Project</b>",
        f"📁 <code>{esc(str(root).replace(str(Path.home()), '~', 1) if root else 'not set')}</code>" + (f" · profile {esc(cfg.get('project.profile'))}" if cfg.get("project.profile") else ""),
    ]
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip(), None


PERMISSIONS = {"plan": "read and answer only", "acceptEdits": "may edit files", "auto": "may edit files and run commands"}


def _bar(pct, width=10):
    full = max(0, min(width, round(pct / 100 * width)))
    return "▰" * full + "▱" * (width - full)


def _until(ts):
    left = ts - time.time()
    if left <= 0:
        return "reset — open /usage in Claude Code to refresh"
    when = time.strftime("%H:%M" if left < 20 * 3600 else "%a %d %b, %H:%M", time.localtime(ts))
    return f"resets in {_dur(left)} · {when}"


def cmd_usage():
    import system

    live_on = bool(cfg.get("claude.live_usage"))
    usage = _claude_usage()
    acct = usage.get("account") or {}
    if not usage.get("limits"):
        hint = "Run /usage once in Claude Code — it saves your limits there." if acct.get("email") else "Claude Code is not signed in on this Mac."
        return f"<b>Claude usage</b>\nNo limits saved yet. {hint}", None
    lines = ["<b>Claude usage</b>"]
    if acct.get("email"):
        lines.append(f"👤 {esc(acct['email'])}" + (f" · {esc(acct['org'])}" if acct.get("org") else "") + (f" · {esc(acct['plan'])}" if acct.get("plan") else ""))
    lines.append("")
    for lim in usage["limits"]:
        past = lim.get("resets_at") and lim["resets_at"] < time.time()
        pct = 0 if past else lim["percent"]
        dot = "🔴" if pct >= 95 or lim.get("severity") == "critical" else "🟠" if pct >= 80 or lim.get("severity") == "warning" else "🟢"
        lines.append(f"{dot} <b>{esc(lim['label'])}</b> · {'—' if past else str(pct) + '%'}\n<code>{_bar(pct)}</code>" + (f"\n{_until(lim['resets_at'])}" if lim.get("resets_at") else "") + "\n")
    lines.append("")
    if usage.get("source") == "account":
        lines.append(f"🔑 measured by Opsboard {_dur(time.time() - (usage.get('fetched') or 0))} ago · Claude Code itself cannot show usage with a setup token")
    elif usage.get("source") == "live":
        lines.append("⚡ live — updated every 10 minutes")
    else:
        age = time.time() - (usage.get("fetched") or 0)
        lines.append(f"🗂 from Claude Code's cache, updated {_dur(age)} ago" + ("" if live_on else " · turn on Live Claude usage in Settings for fresh numbers"))
    if usage.get("live_error"):
        lines.append(f"⚠️ live usage: {esc(usage['live_error'])}")
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip(), None


OPENED = {
    "uz": ("{who} thread ochdi", "{who} {n} ta thread ochdi"),
    "en": ("{who} opened a thread", "{who} opened {n} threads"),
    "ru": ("{who} открыл тред", "{who} открыл {n} треда"),
}
FIX_STATE = {
    "uz": {
        "started": "▶ {name} ishga tushdi · {at}",
        "done": "✅ {name} tugadi",
        "error": "❌ {name} xato bilan tugadi",
        "stopped": "⏹ {name} to'xtatildi",
        "busy": "Bu MR uchun fix allaqachon ishlayapti",
        "from_board": "Opsboard'dan",
    },
    "en": {"from_board": "from Opsboard", "started": "▶ {name} started · {at}", "done": "✅ {name} finished", "error": "❌ {name} failed", "stopped": "⏹ {name} stopped", "busy": "A fix is already running for this request"},
    "ru": {
        "started": "▶ {name} запущен · {at}",
        "done": "✅ {name} завершён",
        "error": "❌ {name} завершился с ошибкой",
        "stopped": "⏹ {name} остановлен",
        "busy": "Для этого запроса исправление уже идёт",
        "from_board": "из Opsboard",
    },
}
_pending, _fix_msgs, _sent_texts, _thread_msgs, _pending_lock = {}, {}, {}, {}, threading.Lock()
THREAD_GROUP = 3


def _bot_lang():
    chosen = cfg.get("telegram.language") or "auto"
    if chosen in OPENED:
        return chosen
    ui = (cfg.get("ui.language") or "")[:2]
    return ui if ui in OPENED else "uz"


def _fix_buttons(iid):
    skill = cfg.get("claude.fix_skill") or "fix"
    return [[{"text": f"⚡ {skill} ultra", "callback_data": f"fix:{iid}:p"}, {"text": f"🚀 {skill} ultra-skip", "callback_data": f"fix:{iid}:ps"}]]


MERGED = {
    "uz": {
        "heads": ["🎉 {ref} merge qilindi!", "🚀 {ref} {target} ga qo'shildi", "🥳 Tabriklayman — {ref} merge bo'ldi!", "✅ {ref} qabul qilindi va merge qilindi", "🏁 {ref} marraga yetdi — merged!"],
        "by": "👤 merge qildi: {who} · {at}",
        "open": "⏱ ochiq turdi: {d}",
        "threads": "💬 {n} ta thread",
        "approved": "👍 approve: {who}",
    },
    "en": {
        "heads": ["🎉 {ref} is merged!", "🚀 {ref} landed in {target}", "🥳 Congrats — {ref} got merged!", "✅ {ref} was accepted and merged", "🏁 {ref} crossed the finish line — merged!"],
        "by": "👤 merged by {who} · {at}",
        "open": "⏱ open for {d}",
        "threads": "💬 {n} threads",
        "approved": "👍 approved by {who}",
    },
    "ru": {
        "heads": ["🎉 {ref} слит!", "🚀 {ref} попал в {target}", "🥳 Поздравляю — {ref} слит!", "✅ {ref} принят и слит", "🏁 {ref} на финише — слит!"],
        "by": "👤 слил: {who} · {at}",
        "open": "⏱ был открыт: {d}",
        "threads": "💬 тредов: {n}",
        "approved": "👍 одобрил: {who}",
    },
}


def _span(seconds, lang):
    seconds = max(0, int(seconds))
    days, hours, minutes = seconds // 86400, seconds % 86400 // 3600, seconds % 3600 // 60
    units = {"uz": ("kun", "soat", "daqiqa"), "en": ("d", "h", "m"), "ru": ("д", "ч", "мин")}[lang]
    parts = [f"{days} {units[0]}" if days else "", f"{hours} {units[1]}" if hours else "", f"{minutes} {units[2]}" if minutes and not days else ""]
    return " ".join(p for p in parts if p) or f"1 {units[2]}"


def _merged_text(item):
    lang = _bot_lang()
    w = MERGED[lang]
    ref = f"<b>{_ref(item['iid'])}</b>"
    head = random.choice(w["heads"]).format(ref=ref, target=f"<code>{esc(item.get('target') or '')}</code>")
    lines = [head]
    if item.get("mr_title"):
        lines.append(f"<i>{esc(item['mr_title'][:160])}</i>")
    lines.append("")
    if item.get("source") or item.get("target"):
        lines.append(f"🔀 <code>{esc(item.get('source') or '')}</code> → <code>{esc(item.get('target') or '')}</code>")
    if item.get("merged_by"):
        lines.append(w["by"].format(who=f"<b>{esc(item['merged_by'])}</b>", at=time.strftime("%H:%M", time.localtime(item.get("merged_at") or time.time()))))
    if item.get("created"):
        lines.append(w["open"].format(d=_span((item.get("merged_at") or time.time()) - item["created"], lang)))
    if item.get("threads_total"):
        lines.append(w["threads"].format(n=item["threads_total"]))
    if item.get("approved_by"):
        lines.append(w["approved"].format(who=esc(", ".join(item["approved_by"]))))
    return "\n".join(lines)


def on_notify(item):
    if not chat_id():
        return
    if item.get("kind") == "battery":
        if cfg.get("telegram.notify"):
            lang, mins = _bot_lang(), item.get("minutes")
            span = _span(mins * 60, lang) if mins else ""
            left = (
                {"uz": f"Shu tarzda taxminan <b>{span}</b>ga yetadi.", "en": f"At this rate it lasts about <b>{span}</b>.", "ru": f"При таком расходе хватит примерно на <b>{span}</b>."}[lang]
                if mins
                else ""
            )
            words = {
                "uz": "🪫 <b>Batareya {n}% qoldi</b>\n{left}\nMac'ni quvvatga ulang.",
                "en": "🪫 <b>Battery at {n}%</b>\n{left}\nPlug in the Mac.",
                "ru": "🪫 <b>Батарея {n}%</b>\n{left}\nПодключите Mac к зарядке.",
            }
            send(words[lang].format(n=item.get("level"), left=left).replace("\n\n", "\n"), note=True)
        return
    if item.get("kind") == "claude_propose":
        if "telegram" in (cfg.get("claude.ask_in") or []):
            send_proposal(item)
        return
    if item.get("kind") == "claude_switch" and item.get("how") != "automatically":
        return
    if item.get("kind") in ("claude_switch", "claude_full", "claude_duplicate"):
        if cfg.get("telegram.notify"):
            head, body = notify.text(item)
            send(f"{'🔀' if item['kind'] == 'claude_switch' else '⛽'} <b>{esc(head)}</b>\n{esc(body)}", note=True)
        return
    if item.get("kind") == "merged":
        if cfg.get("telegram.notify"):
            link = _url_button(f"Open in {_host()}", item.get("url"))
            send(_merged_text(item), [link] if link else None, note=True)
        return
    if item.get("kind") == "run":
        if not item.get("silent"):
            _fix_finished(item)
        return
    if item.get("kind") == "run_started":
        if item.get("source") != "telegram":
            _fix_started_elsewhere(item)
        return
    if item.get("kind") != "thread" or not cfg.get("telegram.notify"):
        return
    iid = item.get("iid")
    with _pending_lock:
        group = _pending.setdefault(iid, {"authors": [], "n": 0, "title": item.get("mr_title") or ""})
        group["n"] += 1
        if item.get("author") and item["author"] not in group["authors"]:
            group["authors"].append(item["author"])
        first = group["n"] == 1
    if first:
        threading.Timer(THREAD_GROUP, _flush_threads, args=(iid,)).start()


KEYCAP = {str(d): f"{d}\ufe0f\u20e3" for d in range(10)}


def emoji_number(n):
    return "".join(KEYCAP.get(c, c) for c in str(n))


def _thread_text(iid, group):
    one, many = OPENED[_bot_lang()]
    who = ", ".join(group["authors"]) or "?"
    line = (one if group["n"] == 1 else many).format(who=f"<b>{esc(who)}</b>", n=emoji_number(group["n"]))
    m = _mr(iid) or {}
    title = group["title"] or m.get("title") or ""
    role = {"uz": " · sizga assign qilingan", "en": " · assigned to you", "ru": " · назначен вам"}[_bot_lang()] if m.get("role") == "assignee" else ""
    return f"💬 <b>{_ref(iid)}</b>{role} — {line}" + (f"\n<i>{esc(title[:140])}</i>" if title else "")


def _flush_threads(iid):
    with _pending_lock:
        group = _pending.pop(iid, None)
    if group:
        text = _thread_text(iid, group)
        msg = send(text, _fix_buttons(iid), note=True)
        if msg:
            with _pending_lock:
                _sent_texts[msg["message_id"]] = text
                _thread_msgs[iid] = msg["message_id"]
                while len(_sent_texts) > 200:
                    _sent_texts.pop(next(iter(_sent_texts)))


def _launch_fix(iid, push, skiptests=False):
    import runs

    if any(r.get("iid") == iid and r["status"] == "running" for r in runs.load_runs()):
        return None, FIX_STATE[_bot_lang()]["busy"]
    runs.launch_fix({"iid": iid, "threads": True, "conflict": True, "skiptests": skiptests, "push": push, "source": "telegram"})
    return next((r for r in runs.load_runs() if r.get("iid") == iid and r["status"] == "running"), None), ""


WAIT_ALERT = {
    "uz": {
        "permission_prompt": "ruxsat so'rayapti", "permission_request": "ruxsat so'rayapti", "elicitation_dialog": "savol beryapti",
        "question": "savol beryapti", "question_request": "savol beryapti", "idle_prompt": "keyingi buyruqni kutyapti",
        "head": "⏳ <b>Claude {what}</b> — {m} daqiqadan beri javob yo'q", "now": "❓ <b>Claude {what}</b>",
        "allow": "✅ Ruxsat", "deny": "❌ Rad etish", "allowed": "✅ Telegram'dan ruxsat berildi · {at}", "denied": "❌ Telegram'dan rad etildi · {at}",
        "answered": "✅ Javob: {a} · {at}", "mac": "💻 Mac'da javob berildi", "closed": "Bu so'rov yopilgan — Mac'da javob berilgan.",
        "own": "✍️ O'z javobingizni yozish uchun shu xabarga reply qiling.", "q": "Savol {i}/{n}",
    },
    "en": {
        "permission_prompt": "is asking for permission", "permission_request": "is asking for permission", "elicitation_dialog": "is asking a question",
        "question": "is asking a question", "question_request": "is asking a question", "idle_prompt": "is waiting for your next message",
        "head": "⏳ <b>Claude {what}</b> — no answer for {m} min", "now": "❓ <b>Claude {what}</b>",
        "allow": "✅ Allow", "deny": "❌ Deny", "allowed": "✅ Allowed from Telegram · {at}", "denied": "❌ Denied from Telegram · {at}",
        "answered": "✅ Answer: {a} · {at}", "mac": "💻 Answered on the Mac", "closed": "This request is closed — it was answered on the Mac.",
        "own": "✍️ Reply to this message to write your own answer.", "q": "Question {i}/{n}",
    },
    "ru": {
        "permission_prompt": "просит разрешение", "permission_request": "просит разрешение", "elicitation_dialog": "задаёт вопрос",
        "question": "задаёт вопрос", "question_request": "задаёт вопрос", "idle_prompt": "ждёт следующего сообщения",
        "head": "⏳ <b>Claude {what}</b> — без ответа {m} мин", "now": "❓ <b>Claude {what}</b>",
        "allow": "✅ Разрешить", "deny": "❌ Отклонить", "allowed": "✅ Разрешено из Telegram · {at}", "denied": "❌ Отклонено из Telegram · {at}",
        "answered": "✅ Ответ: {a} · {at}", "mac": "💻 Ответили на Mac", "closed": "Запрос закрыт — на него ответили на Mac.",
        "own": "✍️ Ответьте на это сообщение, чтобы написать свой ответ.", "q": "Вопрос {i}/{n}",
    },
}
_wait_msgs = {}


def _wait_text(item):
    w = WAIT_ALERT[_bot_lang()]
    what = w.get(item["kind"], item["kind"])
    lines = [w["head"].format(what=what, m=item["minutes"]) if item.get("minutes") else w["now"].format(what=what)]
    where = " · ".join(x for x in (item.get("name"), (item.get("cwd") or "").replace(str(Path.home()), "~", 1)) if x)
    if where:
        lines.append(f"📂 <code>{esc(where)}</code>")
    qs = item.get("questions") or []
    if item["kind"] == "question_request" and qs:
        for i, q in enumerate(qs):
            lines.append(("\n" + w["q"].format(i=i + 1, n=len(qs)) + "\n" if len(qs) > 1 else "\n") + f"<b>{esc(str(q.get('question') or ''))}</b>")
            for o in q.get("options") or []:
                desc = f" — {esc(str(o.get('description') or ''))}" if o.get("description") else ""
                lines.append(f"• {esc(str(o.get('label') or ''))}{desc}")
        lines.append(f"\n<i>{w['own']}</i>")
    elif item.get("message"):
        lines.append(f"<i>{esc(item['message'])}</i>")
    return "\n".join(lines)


def _wait_buttons(item):
    w, req = WAIT_ALERT[_bot_lang()], item.get("req")
    if not req:
        return None
    if item["kind"] == "permission_request":
        return [[{"text": w["allow"], "callback_data": f"cw:{req}:a"}, {"text": w["deny"], "callback_data": f"cw:{req}:d"}]]
    rows, qs = [], item.get("questions") or []
    for qi, q in enumerate(qs):
        for oi, o in enumerate((q.get("options") or [])[:8]):
            label = str(o.get("label") or "")[:40]
            rows.append([{"text": (f"{qi + 1}. " if len(qs) > 1 else "") + label, "callback_data": f"cq:{req}:{qi}:{oi}"}])
    return rows or None


def claude_wait_alert(item):
    text = _wait_text(item)
    msg = send(text, _wait_buttons(item), note=True)
    if msg and item.get("req"):
        with _pending_lock:
            _wait_msgs[item["req"]] = {"mid": msg["message_id"], "text": text, "item": item, "done": []}
            while len(_wait_msgs) > 100:
                _wait_msgs.pop(next(iter(_wait_msgs)))
    return msg


def claude_wait_closed(w):
    with _pending_lock:
        tracked = _wait_msgs.pop(w.get("req"), None) if w.get("req") else None
    if tracked:
        edit(tracked["mid"], f"{tracked['text']}\n\n{WAIT_ALERT[_bot_lang()]['mac']}")


def _wait_status(req, status):
    with _pending_lock:
        tracked = _wait_msgs.pop(req, None)
    if tracked:
        edit(tracked["mid"], f"{tracked['text']}\n\n{status}")


def _wait_decide(req, allow, message=""):
    import claudewait

    w = WAIT_ALERT[_bot_lang()]
    if not claudewait.decide(req, "allow" if allow else "deny", message):
        _wait_status(req, w["mac"])
        return w["closed"]
    _wait_status(req, w["allowed" if allow else "denied"].format(at=time.strftime("%H:%M")))
    return ""


def _wait_answer(req, qi, text):
    import claudewait

    w = WAIT_ALERT[_bot_lang()]
    out = claudewait.answer(req, qi, text)
    if out is None:
        _wait_status(req, w["mac"])
        return w["closed"]
    done, entry = out
    if done:
        shown = "; ".join(entry["answers"].values())
        _wait_status(req, w["answered"].format(a=esc(shown[:300]), at=time.strftime("%H:%M")))
    return ""


def _wait_option(req, qi, oi):
    with _pending_lock:
        tracked = _wait_msgs.get(req)
    qs = (tracked or {}).get("item", {}).get("questions") or []
    try:
        label = str(qs[qi]["options"][oi]["label"])
    except (IndexError, KeyError, TypeError):
        return WAIT_ALERT[_bot_lang()]["closed"]
    return _wait_answer(req, qi, label)


def _wait_reply(msg):
    mid = (msg.get("reply_to_message") or {}).get("message_id")
    with _pending_lock:
        req = next((r for r, t in _wait_msgs.items() if t["mid"] == mid), None)
        tracked = _wait_msgs.get(req) if req else None
    if not tracked:
        return False
    if tracked["item"]["kind"] != "question_request":
        return False
    import claudewait

    open_q = [i for i, q in enumerate(tracked["item"].get("questions") or []) if str(q.get("question") or "") not in (claudewait.pending_answers(req) or {})]
    note = _wait_answer(req, open_q[0] if open_q else 0, (msg.get("text") or "").strip())
    if note:
        send(esc(note))
    else:
        react(msg.get("message_id"), "👍")
    return True


REPLY_HOOKS.append(_wait_reply)


def _fix_name(push, skiptests):
    skill = cfg.get("claude.fix_skill") or "fix"
    return f"{skill} ultra-skip" if skiptests else f"{skill} ultra" if push else skill


def _fix_started_elsewhere(item):
    with _pending_lock:
        mid = _thread_msgs.get(item.get("iid"))
    if not mid or not chat_id():
        return
    words = FIX_STATE[_bot_lang()]
    name = _fix_name(item.get("push"), item.get("skiptests"))
    try:
        call("editMessageReplyMarkup", chat_id=chat_id(), message_id=mid, reply_markup={"inline_keyboard": []})
    except TelegramError as exc:
        log.warning("telegram: could not remove fix buttons: %s", exc)
    send(words["started"].format(name=esc(name), at=time.strftime("%H:%M")) + f" · {words['from_board']}", reply_to=mid, note=True)
    with _pending_lock:
        _fix_msgs[item["run_id"]] = {"message_id": mid, "name": name}


def _start_fix(cq, iid, push, skiptests=False):
    msg = cq.get("message") or {}
    words = FIX_STATE[_bot_lang()]
    name = _fix_name(push, skiptests)
    run, busy = _launch_fix(iid, push, skiptests)
    if busy:
        return busy
    with _pending_lock:
        base = _sent_texts.get(msg.get("message_id")) or _thread_text_from(msg)
    status = words["started"].format(name=esc(name), at=time.strftime("%H:%M"))
    edit(msg.get("message_id"), f"{base}\n\n{status}")
    if run:
        with _pending_lock:
            _fix_msgs[run["id"]] = {"message_id": msg.get("message_id"), "base": base, "name": name}
    return ""


def _thread_text_from(msg):
    text, out = msg.get("text") or "", []
    for ent in sorted(msg.get("entities") or [], key=lambda e: e["offset"]):
        out.append(ent)
    if not out:
        return esc(text)
    units = text.encode("utf-16-le")
    html, pos = [], 0
    for ent in out:
        start, end = ent["offset"] * 2, (ent["offset"] + ent["length"]) * 2
        if start < pos:
            continue
        html.append(esc(units[pos:start].decode("utf-16-le")))
        chunk = esc(units[start:end].decode("utf-16-le"))
        tag = {"bold": "b", "italic": "i", "code": "code"}.get(ent["type"])
        html.append(f"<{tag}>{chunk}</{tag}>" if tag else chunk)
        pos = end
    html.append(esc(units[pos:].decode("utf-16-le")))
    return "".join(html)


def _fix_finished(item):
    with _pending_lock:
        tracked = _fix_msgs.pop(item.get("run_id"), None)
    if not tracked:
        return
    words = FIX_STATE[_bot_lang()]
    o = item.get("outcome") or {}
    th = o.get("threads") or {}
    key = "error" if item.get("status") == "error" else "stopped" if o.get("status") == "stopped" else "done"
    bits = [o.get("status") or "", str(o.get("commit") or "")[:10], (f"{th['replied']} replied, {th.get('open', 0)} open" if 'replied' in th else f"{th.get('resolved', 0)}/{th.get('resolved', 0) + th.get('open', 0)} threads") if th else ""]
    detail = " · ".join(b for b in bits if b)
    status = words[key].format(name=esc(tracked["name"])) + (f" · {esc(detail)}" if detail else "")
    if tracked.get("base"):
        edit(tracked["message_id"], f"{tracked['base']}\n\n{status}")
    send(status, reply_to=tracked["message_id"], note=True)


def md_to_html(text):
    out = []
    for i, part in enumerate(re.split(r"```", text or "")):
        if i % 2:
            out.append("<pre>" + esc(re.sub(r"^[\w+-]*\n", "", part).rstrip()) + "</pre>")
            continue
        s = esc(part)
        s = re.sub(r"^#{1,6} +(.+)$", r"<b>\1</b>", s, flags=re.M)
        s = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", s)
        s = re.sub(r"\*\*([^*\n]+)\*\*", r"<b>\1</b>", s)
        s = re.sub(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', s)
        s = re.sub(r"^[-*] +", "• ", s, flags=re.M)
        s = re.sub(r"(?:^&gt; ?.*(?:\n|$))+", lambda m: "<blockquote expandable>" + re.sub(r"^&gt; ?", "", m.group(0).rstrip("\n"), flags=re.M) + "</blockquote>\n", s, flags=re.M)
        out.append(s)
    return "".join(out).strip()


def edit(message_id, text, plain=False, chat=None, buttons=None):
    params = {"chat_id": chat or chat_id(), "message_id": message_id, "text": text[:4096], "disable_web_page_preview": True}
    if buttons:
        params["reply_markup"] = {"inline_keyboard": buttons}
    if not plain:
        params["parse_mode"] = "HTML"
    try:
        return call("editMessageText", **params)
    except TelegramError as exc:
        if "not modified" in str(exc):
            return True
        log.warning("telegram edit failed: %s", exc)
        return None


def send_widget(source, caption, chat_data=None, notify=True, height=None):
    if not chat_id():
        return None
    try:
        return call("sendWidget", chat_id=chat_id(), html=source, caption=caption[:1024], parse_mode="HTML", chat_data=chat_data, height=height, allow_queries=True, disable_notification=None if notify else True)
    except TelegramError as exc:
        log.warning("telegram widget failed: %s", exc)
        return None


def edit_widget(message_id, chat_data, caption=None):
    try:
        call("editMessageWidgetData", chat_id=chat_id(), message_id=message_id, chat_data=chat_data)
    except TelegramError as exc:
        if "not modified" not in str(exc):
            log.warning("telegram widget edit failed: %s", exc)
            return False
    if caption:
        try:
            call("editMessageCaption", chat_id=chat_id(), message_id=message_id, caption=caption[:1024], parse_mode="HTML")
        except TelegramError as exc:
            if "not modified" not in str(exc):
                log.warning("telegram caption edit failed: %s", exc)
    return True


def delete(message_id):
    try:
        call("deleteMessage", chat_id=chat_id(), message_id=message_id)
        return True
    except TelegramError:
        return False


def handle_widget_query(q):
    if not chat_id() or (q.get("chat") or {}).get("id") != chat_id():
        return
    answer = None
    for handler in [on_live_widget, *WIDGET_HANDLERS]:
        try:
            answer = handler(q)
        except Exception:  # noqa: BLE001
            log.exception("widget handler failed")
            answer = "error"
        if answer is not None:
            break
    try:
        call("answerWidgetQuery", widget_query_id=q["id"], data=str(answer)[:1024] if answer is not None else None)
    except TelegramError as exc:
        log.warning("widget answer failed: %s", exc)


def react(message_id, emoji="👀"):
    try:
        call("setMessageReaction", chat_id=chat_id(), message_id=message_id, reaction=[{"type": "emoji", "emoji": emoji}])
    except TelegramError:
        pass


def _chunks(text, size=3800):
    out, chunk = [], ""
    for line in (text or "").splitlines(keepends=True):
        while len(line) > size:
            out.append(line[:size])
            line = line[size:]
        if len(chunk) + len(line) > size:
            out.append(chunk)
            chunk = ""
        chunk += line
    if chunk.strip():
        out.append(chunk)
    return out


PANEL_LINES, PANEL_WIDTH = 6, 60
DETAILS = {"uz": "📄 Batafsil", "en": "📄 Details", "ru": "📄 Подробнее"}
_details = {}


def split_panel(text):
    """The answer as status lines plus details: the part before a '---' line, or else its first short lines."""
    text = (text or "").strip()
    head, sep, tail = text.partition("\n---")
    if sep:
        tail = tail.split("\n", 1)[1] if "\n" in tail else ""
    lines = [ln.strip() for ln in head.splitlines() if ln.strip()]
    panel = []
    for ln in lines[:PANEL_LINES]:
        ln = re.sub(r"^[-*•] +", "", re.sub(r"^#+ +", "", ln))
        panel.append(ln if len(ln) <= PANEL_WIDTH else ln[: PANEL_WIDTH - 1].rstrip() + "…")
    rest = "\n".join(lines[PANEL_LINES:]) if not sep else ""
    details = "\n\n".join(x for x in (rest, tail.strip()) if x)
    if not sep and any(len(ln) > PANEL_WIDTH for ln in lines[:PANEL_LINES]):
        details = text
    return "\n".join(panel), details


STATUS = ("🟢", "🟡", "🔴", "⚪", "👉", "✅", "⚠️", "❌")
PANELIZE = (
    "Rewrite the answer below as a phone status panel. Output ONLY:\n"
    "2 to 6 lines, each '<emoji> <label> · <short value>', at most 40 characters, no sentences. "
    "Emoji: 🔴 problem or the user must act, 🟡 watch, 🟢 fine, ⚪ none. 🔴 lines first. If the user must do "
    "something, the last line is '👉 <the action>'. Keep the answer's language. Nothing else.\n\nANSWER:\n"
)


def is_panel(panel):
    lines = [ln for ln in panel.splitlines() if ln.strip()]
    return bool(lines) and all(ln.lstrip().startswith(STATUS) for ln in lines)


def haiku(prompt, timeout=90):
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_CODE_")}
    cmd = [claude_bin(), "-p", prompt, "--model", "haiku", "--max-turns", "1", "--tools", "", "--strict-mcp-config", "--no-session-persistence"]
    try:
        r = subprocess.run(cmd, cwd=str(Path.home()), env=env, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def panelize(text):
    """A cheap model turns an answer that ignored the panel format into one; None when it cannot."""
    out = "\n".join(ln.strip() for ln in (haiku(PANELIZE + text[:6000]) or "").splitlines() if ln.strip())
    return out if is_panel(out) else None


TOPIC = (
    "A user chats with an assistant in Telegram. Decide whether his NEW message continues the PREVIOUS exchange "
    "(a follow-up, refers to it, answers it) or starts a different topic. Reply with exactly one word: SAME or NEW.\n\n"
)
TOPIC_AFTER = 120


def new_topic(prev_q, prev_a, text):
    out = haiku(f"{TOPIC}PREVIOUS USER: {prev_q[:800]}\nPREVIOUS ASSISTANT: {prev_a[:800]}\n\nNEW: {text[:800]}", timeout=30)
    return (out or "").strip().upper().startswith("NEW")


def _spaced(panel):
    """A blank line between the problem lines, the rest and the action line, so it reads at a glance."""
    lines = [ln.strip() for ln in panel.splitlines() if ln.strip()]
    out, prev = [], None
    for ln in lines:
        group = "act" if ln.startswith("👉") else "bad" if ln.startswith(("🔴", "❌")) else "rest"
        if prev and group != prev:
            out.append("")
        out.append(ln)
        prev = group
    return "\n".join(out)


def deliver_panel(text, placeholder=None, lang="uz"):
    if "\n---" not in text and len(text) <= 300 and len([ln for ln in text.splitlines() if ln.strip()]) <= 3:
        deliver(text, placeholder)
        return
    panel, details = split_panel(text)
    if not is_panel(panel):
        made = panelize(text)
        if made:
            panel, details = made, text
    buttons = None
    if details:
        key = secrets.token_hex(4)
        _details[key] = details
        while len(_details) > 50:
            _details.pop(next(iter(_details)))
        buttons = [[{"text": DETAILS.get(lang, DETAILS["uz"]), "callback_data": f"det:{key}"}]]
    body = md_to_html(_spaced(panel)) or esc(DETAILS.get(lang, ""))
    if placeholder and edit(placeholder, body, buttons=buttons):
        return
    send(body, buttons)


def show_details(cq, key):
    text = _details.get(key)
    if not text:
        return "This answer is too old — ask again."
    deliver(text)
    try:
        call("editMessageReplyMarkup", chat_id=chat_id(), message_id=(cq.get("message") or {}).get("message_id"), reply_markup={"inline_keyboard": []})
    except TelegramError:
        pass
    return ""


def deliver(text, placeholder=None):
    """Turn the placeholder into the answer; send the rest as new messages only when it is too long for one."""
    formatted = md_to_html(text)
    if len(formatted) <= 4000:
        if placeholder and edit(placeholder, formatted):
            return
        if not placeholder and send(formatted):
            return
    parts = _chunks(text)
    first, rest = (parts[0], parts[1:]) if parts else ("", [])
    if not (placeholder and edit(placeholder, first, plain=True)):
        send(first, plain=True)
    for part in rest:
        send(part, plain=True)


DOING = {
    "en": {
        "read": "📖 reading {x}",
        "search": "🔍 searching files",
        "run": "⚙️ running: {x}",
        "edit": "✍️ editing {x}",
        "web": "🌐 looking it up online",
        "agent": "🤖 asking a helper agent",
        "tool": "🛠 using {x}",
        "think": "💭 thinking",
    },
    "uz": {
        "read": "📖 {x} ni o'qiyapman",
        "search": "🔍 fayllar ichidan qidiryapman",
        "run": "⚙️ ishga tushiryapman: {x}",
        "edit": "✍️ {x} ni tahrirlayapman",
        "web": "🌐 internetdan qarayapman",
        "agent": "🤖 yordamchi agentdan so'rayapman",
        "tool": "🛠 {x} dan foydalanyapman",
        "think": "💭 o'ylayapman",
    },
    "ru": {
        "read": "📖 читаю {x}",
        "search": "🔍 ищу по файлам",
        "run": "⚙️ запускаю: {x}",
        "edit": "✍️ правлю {x}",
        "web": "🌐 смотрю в интернете",
        "agent": "🤖 спрашиваю агента-помощника",
        "tool": "🛠 использую {x}",
        "think": "💭 думаю",
    },
}
CANCELLED = {"en": "⏹ Cancelled.", "uz": "⏹ To'xtatildi.", "ru": "⏹ Отменено."}
RE_UZ = re.compile(
    r"\b(nima|qanday|qanaqa|qayer|qachon|nega|nechta|bormi|yo'q|ha|kerak|qil|ber|ko'r|o'z|bo'l|emas|uchun|bilan|shu|bu|menga|mening|qaysi|yoz|qara|ayt|tushuntir|salom|rahmat|iltimos|ishla|tekshir|qanaqa|ekan|edi|kim|endi|hozir|keyin|yana)\w*|[og]['ʻ’]|\w(lar|ni|ga|da|dan|ning|mi)\b",
    re.I,
)
RE_EN = re.compile(r"\b(the|what|how|why|is|are|can|please|show|tell|does|which|where|when)\b", re.I)


def lang_of(text):
    chosen = cfg.get("telegram.language") or "auto"
    if chosen in WORKING:
        return chosen
    text = text or ""
    if re.search(r"[А-Яа-яЁё]", text):
        return "ru"
    uz, en = len(RE_UZ.findall(text)), len(RE_EN.findall(text))
    if uz > en:
        return "uz"
    if en:
        return "en"
    ui = (cfg.get("ui.language") or "")[:2]
    return ui if ui in WORKING else "uz"


def _doing(block, lang):
    name, inp = block.get("name", ""), block.get("input") or {}
    words = DOING[lang]
    path = Path(str(inp.get("file_path") or inp.get("notebook_path") or "")).name
    if name == "Read":
        return words["read"].format(x=path or "a file")
    if name in ("Grep", "Glob"):
        return words["search"]
    if name == "Bash":
        return words["run"].format(x=str(inp.get("description") or str(inp.get("command") or "").split("\n")[0])[:80])
    if name in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        return words["edit"].format(x=path or "a file")
    if name in ("WebFetch", "WebSearch"):
        return words["web"]
    if name in ("Agent", "Task"):
        return words["agent"]
    return words["tool"].format(x=name)


def _load_chat():
    try:
        return json.loads(CHAT_FILE.read_text())
    except (OSError, ValueError):
        return {}


def _save_chat(data):
    CHAT_FILE.write_text(json.dumps(data))


IDLE_CLOSE = 3 * 3600
FRESH_AFTER = 6 * 3600
CHAT_ROLE = (
    "You answer Javohir in his Opsboard Telegram bot, running on his Mac. The bot also sends him notifications "
    "(new review threads, fix runs, Claude sessions waiting for permission or an answer, battery, merges). "
    "Each message may start with [Opsboard notifications since your last turn] and [He replied to] blocks: "
    "read them first, they are what his message is about. Permission prompts and questions of other Claude Code "
    "sessions arrive as their own bot messages with buttons; when he wants to allow or answer one, tell him to use "
    "those buttons or reply to that message (VS Code sessions), otherwise to answer on the Mac. "
    "Other Claude Code sessions on this Mac also send him files and screenshots through the bot; a [He replied to] block "
    "then names the sending session and folder. Answer from what that message and its caption say; when the question "
    "is about that session's work, read its transcript (~/.claude/projects/<folder>/<session>.jsonl) or the code it names.\n\n"
    "How to write every answer (the bot shows only the first part on his phone; the rest is behind a Details button):\n"
    "Part 1 — a status panel: 2 to 6 lines, each '<emoji> <label> · <short value>', at most 40 characters, no sentences. "
    "Emoji: 🟢 fine, 🟡 watch, 🔴 problem or he must act, ⚪ nothing/none. Put the 🔴 lines first. If he must do "
    "something, the last line is '👉 <the action>'.\n"
    "Then a line with only '---'.\n"
    "Part 2 — details: short '- ' bullets, ids in `code`, no closing offers. Omit part 2 (and the ---) when the panel says it all.\n"
    "Answer in his language."
)
EXTRA = {"en": "🔔 Claude came back:", "uz": "🔔 Claude qaytib keldi:", "ru": "🔔 Claude вернулся:"}
QUEUED = {"en": "⏳ Queued — after the current answer", "uz": "⏳ Navbatda — joriy javobdan keyin", "ru": "⏳ В очереди — после текущего ответа"}


class ClaudeChat:
    """One long-lived Claude Code process per linked chat: messages queue into it, and it stays alive between turns
    so it can come back on its own (a background job finished, another session answered)."""

    def __init__(self):
        self.proc = None
        self.mode = ""
        self.turns = []
        self.doing = ""
        self.lang = "uz"
        self.last = time.time()
        self.seen = time.time() - NOTES_SPAN
        self.prev = None
        self.lock = threading.Lock()

    @property
    def busy(self):
        return bool(self.turns)

    def _start(self):
        mode = cfg.get("telegram.chat_permission") or "plan"
        root = project_root()
        chat = _load_chat()
        sid = chat.get("session_id") if time.time() - (chat.get("last") or chat.get("at") or 0) < FRESH_AFTER else None
        cmd = [claude_bin(), "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose", "--permission-mode", mode, "--append-system-prompt", CHAT_ROLE] + (["--resume", sid] if sid else [])
        self.proc = subprocess.Popen(
            cmd,
            cwd=str(root) if root and root.is_dir() else str(Path.home()),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        self.mode = mode
        threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()
        threading.Thread(target=self._tick, args=(self.proc,), daemon=True).start()

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def ask(self, text, message_id=None, quoted=""):
        lang = lang_of(text)
        prev = self.prev
        if prev and not self.turns and time.time() - self.last > TOPIC_AFTER and new_topic(prev[0], prev[1], text):
            log.info("telegram chat: new topic, fresh conversation")
            with self.lock:
                self.close()
                self.proc = None
                _save_chat({})
                self.prev = None
        asked = text
        ctx = [f"- {time.strftime('%H:%M', time.localtime(t))} {x}" for t, x in recent_notes(self.seen)]
        self.seen = time.time()
        if ctx:
            text = "[Opsboard notifications since your last turn]\n" + "\n".join(ctx) + "\n\n" + text
        if quoted:
            text = f"[He replied to]\n{quoted[:1500]}\n\n" + text
        live = _live_sessions()
        if live:
            text = "[Live Claude Code sessions on this Mac]\n" + live + "\n\n" + text
        if message_id:
            react(message_id)
        with self.lock:
            if self.alive() and self.mode != (cfg.get("telegram.chat_permission") or "plan") and not self.turns:
                self.close()
            if not self.alive():
                try:
                    self._start()
                except OSError as exc:
                    send(f"Could not start Claude: {esc(str(exc))}")
                    return
            queued = bool(self.turns)
            msg = send(esc(QUEUED[lang] if queued else WORKING[lang]))
            self.turns.append({"placeholder": (msg or {}).get("message_id"), "started": time.time(), "lang": lang, "asked": asked})
            self.lang, self.last = lang, time.time()
            try:
                self.proc.stdin.write(json.dumps({"type": "user", "message": {"role": "user", "content": text}}) + "\n")
                self.proc.stdin.flush()
            except (OSError, ValueError):
                self.turns.pop()
                send("Claude is not running — send the message again.")

    def _read(self, proc):
        for line in proc.stdout:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("session_id") and ev.get("type") in ("system", "result"):
                chat = _load_chat()
                if chat.get("session_id") != ev["session_id"]:
                    chat = {"session_id": ev["session_id"], "at": time.time()}
                if ev.get("type") == "result" or "last" not in chat:
                    chat["last"] = time.time()
                    _save_chat(chat)
            if ev.get("type") == "assistant" and not ev.get("parent_tool_use_id"):
                for b in (ev.get("message") or {}).get("content") or []:
                    if b.get("type") == "tool_use":
                        self.doing = _doing(b, self.lang)
                    elif b.get("type") == "thinking":
                        self.doing = DOING[self.lang]["think"]
            elif ev.get("type") == "result":
                with self.lock:
                    turn = self.turns.pop(0) if self.turns else None
                    self.doing, self.last = "", time.time()
                answer = str(ev.get("result") or "").strip()
                if turn and answer and not ev.get("is_error"):
                    self.prev = (turn.get("asked") or "", answer)
                if ev.get("is_error") or not answer:
                    note = "⚠️ " + esc((answer or "Claude did not answer").strip()[-800:])
                    if not (turn and turn["placeholder"] and edit(turn["placeholder"], note)):
                        send(note)
                elif turn:
                    deliver_panel(answer, turn["placeholder"], turn["lang"])
                else:
                    send(f"<i>{esc(EXTRA[self.lang])}</i>")
                    deliver_panel(answer, None, self.lang)
        err = (proc.stderr.read() or "").strip() if proc.stderr else ""
        with self.lock:
            left = []
            if self.proc is proc:
                left, self.turns = self.turns, []
                self.proc = None
        for turn in left:
            text = CANCELLED[turn["lang"]] if proc.returncode and proc.returncode < 0 else "⚠️ " + esc((err or "Claude stopped")[-500:])
            if not (turn["placeholder"] and edit(turn["placeholder"], text)):
                send(text)

    def _tick(self, proc):
        while proc.poll() is None:
            time.sleep(1)
            with self.lock:
                turn = self.turns[0] if self.turns else None
                idle = not self.turns and time.time() - self.last > IDLE_CLOSE
            if idle:
                self.close()
                return
            if not turn:
                continue
            try:
                call("sendChatAction", chat_id=chat_id(), action="typing")
            except TelegramError:
                pass

    def close(self):
        proc = self.proc
        if proc and proc.poll() is None:
            try:
                proc.stdin.close()
            except OSError:
                pass

    def cancel(self):
        proc = self.proc
        if not proc or proc.poll() is not None:
            return False
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        return True

    def reset(self):
        self.cancel()
        self.prev = None
        _save_chat({})


CHAT = ClaudeChat()


WORKING = {"uz": "⏳ So'rovingiz ustida ishlayapman, kuting…", "en": "⏳ Working on your request, please wait…", "ru": "⏳ Работаю над вашим запросом, подождите…"}


def reply_for(text, message_id=None, quoted=""):
    words = text.strip().split()
    cmd = words[0].split("@")[0].lower() if words and words[0].startswith("/") else ""
    num = next((int(a.lstrip("!#")) for a in words[1:] if a.lstrip("!#").isdigit()), None)
    if cmd in ("/start", "/help"):
        return help_text(), None
    if cmd == "/mrs":
        return (None, None) if send_live("mrs") else cmd_mrs()
    if cmd == "/mr":
        return cmd_mr(num) if num else ("Usage: /mr 7376", None)
    if cmd == "/sessions":
        return cmd_sessions()
    if cmd == "/info":
        return cmd_info()
    if cmd == "/usage":
        return (None, None) if _claude_usage().get("limits") and send_live("usage") else cmd_usage()
    if cmd[1:] in EXTRA_COMMANDS:
        return EXTRA_COMMANDS[cmd[1:]][1]()
    if cmd == "/new":
        CHAT.reset()
        return "🆕 New conversation with Claude.", None
    if cmd == "/cancel":
        return (None, None) if CHAT.cancel() else ("Nothing to cancel.", None)
    if cmd:
        return "Unknown command.\n\n" + help_text(), None
    if not cfg.get("telegram.claude_chat"):
        return "Claude chat is off — Opsboard → Settings → Telegram → <i>Claude chat</i>.\n\n" + help_text(), None
    threading.Thread(target=CHAT.ask, args=(text.strip(), message_id, quoted), daemon=True).start()
    return None, None


def handle_message(msg):
    chat = msg.get("chat") or {}
    if chat.get("type") != "private" or msg.get("date", 0) < _boot - 60:
        return
    text = msg.get("text") or ""
    linked = chat_id()
    if not linked:
        parts = text.split()
        if parts[:1] == ["/start"] and len(parts) == 2 and _pair["code"] and secrets.compare_digest(parts[1], _pair["code"]) and time.time() <= _pair["until"]:
            who = (msg.get("from") or {}).get("username") or (msg.get("from") or {}).get("first_name") or ""
            cfg.set("telegram.chat_id", str(chat["id"]), "user", "Telegram pairing")
            cfg.set("telegram.user", who, "user", "Telegram pairing")
            _pair.update(code="", until=0)
            send("✅ Linked to this Opsboard.\n\n" + help_text(), chat=chat["id"])
        elif parts[:1] == ["/start"]:
            send("This Opsboard is not linked yet. Open Opsboard → Settings → Telegram and use the link shown there.", chat=chat["id"])
        return
    if chat["id"] != linked or not text.strip():
        return
    if msg.get("reply_to_message") and any(hook(msg) for hook in REPLY_HOOKS):
        return
    rep = msg.get("reply_to_message") or {}
    quoted = rep.get("text") or rep.get("caption") or ""
    with _notes_lock:
        origin = _origins.get(rep.get("message_id"))
    if origin:
        quoted = f"{quoted}\n(sent by the Claude Code session {origin})"
    text_out, buttons = reply_for(text, msg.get("message_id"), quoted)
    if text_out:
        send(text_out, buttons)


PROPOSAL = {
    "uz": {"title": "Claude akkauntini almashtiraymi?", "now": "Hozir", "to": "Taklif", "s": "5 soat", "w": "Hafta", "why": "{name} limiti {n}% dan oshdi ({lim}% chegara).", "busy": "⚠️ Hozir sessiya ishlayapti — u ham yangi akkauntga o'tadi.", "yes": "✅ {name} ga o'tish", "no": "✖ Qolish", "later": "«Qolish» — 1 soatdan keyin yana so'rayman.", "resets": "tiklanadi", "done": "✅ <b>O'tildi</b> → {name}", "stay": "✖ <b>Qolindi</b> — {name}", "gone": "Bu savol yopilgan."},
    "en": {"title": "Switch Claude account?", "now": "Now", "to": "Offer", "s": "5 h", "w": "Week", "why": "{name} passed {n}% (limit {lim}%).", "busy": "⚠️ A session is working — it moves to the new account too.", "yes": "✅ Switch to {name}", "no": "✖ Stay", "later": "Stay — I'll ask again in an hour.", "resets": "resets", "done": "✅ <b>Switched</b> → {name}", "stay": "✖ <b>Stayed</b> on {name}", "gone": "This question is closed."},
    "ru": {"title": "Переключить аккаунт Claude?", "now": "Сейчас", "to": "Предлагаю", "s": "5 ч", "w": "Неделя", "why": "{name} превысил {n}% (порог {lim}%).", "busy": "⚠️ Сейчас работает сессия — она тоже перейдёт.", "yes": "✅ Перейти на {name}", "no": "✖ Остаться", "later": "«Остаться» — спрошу снова через час.", "resets": "сброс", "done": "✅ <b>Переключено</b> → {name}", "stay": "✖ <b>Остались</b> на {name}", "gone": "Вопрос закрыт."},
}
DAYS = {"uz": ["Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"], "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], "ru": ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]}


def _short(name):
    return name.split("@")[0] if "@" in name else name


def _pbar(p):
    p = max(0, min(100, int(p)))
    full = round(p / 10)
    return ("🟥" if p >= 95 else "🟧" if p >= 80 else "🟩") + " " + "█" * full + "░" * (10 - full)


def _when(ts, lang):
    if not ts:
        return ""
    t = time.localtime(ts)
    return time.strftime("%H:%M", t) if time.strftime("%Y%m%d", t) == time.strftime("%Y%m%d") else f"{DAYS[lang][t.tm_wday]} {time.strftime('%H:%M', t)}"


def _windows(w, lang, words):
    rows = []
    for key, name in (("five_hour", words["s"]), ("seven_day", words["w"])):
        if key in w:
            p, ts = w[key]
            rows.append(f"{name:<7}{_pbar(p)} {p:>3}%" + (f"  · {words['resets']} {_when(ts, lang)}" if ts else ""))
    return "\n".join(rows)


def proposal_text(item):
    lang = _bot_lang()
    words = PROPOSAL[lang]
    src, dst = item.get("from") or "", item.get("to") or ""
    parts = [
        f"🔀 <b>{words['title']}</b>",
        "<i>" + esc(words["why"].format(name=_short(src), n=item.get("level"), lim=item.get("switch_at") or 80)) + "</i>",
        "",
    ]
    for icon_, word, name, w in (("📍", words["now"], src, item.get("src_w")), ("➡️", words["to"], dst, item.get("dst_w"))):
        parts.append(f"{icon_} <b>{word}</b> · <code>{esc(name)}</code>")
        if w:
            parts.append(f"<pre>{esc(_windows(w, lang, words))}</pre>")
    if item.get("busy"):
        parts.append(words["busy"])
    parts.append(f"<i>{esc(words['later'])}</i>")
    return "\n".join(parts)


def send_proposal(item):
    words = PROPOSAL[_bot_lang()]
    buttons = [[{"text": words["yes"].format(name=_short(item.get("to") or "")), "callback_data": f"cacc:y:{item['pid']}"}], [{"text": words["no"], "callback_data": f"cacc:n:{item['pid']}"}]]
    msg = send(proposal_text(item), buttons, note=True)
    if msg:
        claudeaccounts.remember_message(item["pid"], msg["message_id"])
    return msg


def _proposal_decided(p, result):
    if not p.get("msg"):
        return
    words = PROPOSAL[_bot_lang()]
    head = words["done"].format(name=esc(claudeaccounts.label(p["dst"]))) if result.startswith("Switched") else words["stay"].format(name=esc(claudeaccounts.label(p["src"]))) if result.startswith("Stayed") else esc(result)
    edit(p["msg"], f"🔀 {head}\n<i>{esc(result)}</i>")


def p_label(p):
    return f"{claudeaccounts.label(p['src'])} → {claudeaccounts.label(p['dst'])}"


claudeaccounts.DECIDED.append(_proposal_decided)


def handle_callback(cq):
    msg = cq.get("message") or {}
    if not chat_id() or (msg.get("chat") or {}).get("id") != chat_id():
        return
    kind, _, rest = (cq.get("data") or "").partition(":")
    note = ""
    if kind == "mr" and rest.isdigit():
        send(*cmd_mr(int(rest)))
    elif kind == "cacc":
        answer, _, pid = rest.partition(":")
        try:
            note = claudeaccounts.decide(pid, answer == "y", "from Telegram")
        except (ValueError, OSError) as exc:
            note = str(exc)[:190]
    elif kind == "det":
        note = show_details(cq, rest)
    elif kind == "cw":
        req, _, act = rest.partition(":")
        note = _wait_decide(req, act == "a")
    elif kind == "cq":
        req, qi, oi = (rest.split(":") + ["", ""])[:3]
        try:
            note = _wait_option(req, int(qi), int(oi))
        except ValueError as exc:
            note = str(exc)[:190]
    elif kind == "fix":
        iid, _, flags = rest.partition(":")
        try:
            note = _start_fix(cq, int(iid), True, "s" in flags)
        except (ValueError, OSError) as exc:
            note = str(exc)[:190]
    try:
        call("answerCallbackQuery", callback_query_id=cq["id"], text=note or None, show_alert=bool(note))
    except TelegramError:
        pass


COMMANDS = [
    {"command": "mrs", "description": "Your open requests"},
    {"command": "mr", "description": "One request: /mr 7376"},
    {"command": "sessions", "description": "Working Claude sessions and their agents"},
    {"command": "usage", "description": "Claude plan limits and when they reset"},
    {"command": "info", "description": "Linked accounts, this Mac and the bot's settings"},
    {"command": "new", "description": "New conversation with Claude"},
    {"command": "cancel", "description": "Stop Claude's current answer"},
]


def bot_loop():
    offset, known = None, None
    while True:
        tok = cfg.secret("telegram.token")
        if not tok:
            _status.update(bot="", running=False, error="")
            known = None
            time.sleep(5)
            continue
        try:
            if tok != known:
                _status["bot"] = call("getMe")["username"]
                call("setMyCommands", commands=COMMANDS + [{"command": k, "description": v[0]} for k, v in EXTRA_COMMANDS.items()])
                known = tok
                _status.update(running=True, error="")
            updates = call("getUpdates", http_timeout=40, timeout=25, offset=offset, allowed_updates=["message", "callback_query", "widget_query"])
            _status.update(running=True, error="")
            for u in updates:
                offset = u["update_id"] + 1
                try:
                    if "message" in u:
                        handle_message(u["message"])
                    elif "callback_query" in u:
                        handle_callback(u["callback_query"])
                    elif "widget_query" in u:
                        handle_widget_query(u["widget_query"])
                except Exception:  # noqa: BLE001
                    log.exception("telegram update failed")
        except TelegramError as exc:
            _status.update(running=False, error=str(exc))
            if "Unauthorized" in str(exc) or "Not Found" in str(exc):
                known = None
            time.sleep(10)


def start():
    threading.Thread(target=bot_loop, daemon=True, name="telegram").start()
    threading.Thread(target=live_loop, daemon=True, name="telegram-live").start()
