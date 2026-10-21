import html
import json
import os
import re
import secrets
import threading
import time
from urllib import error, request

import config as cfg
import runs
from core import lock, log, state

API = os.environ.get("OPS_TELEGRAM_API", "https://api.telegram.org").rstrip("/")
PAIR_TTL = 15 * 60
PROGRESS_EVERY = 6
PHASE_ICON = {"done": "✅", "running": "⏳", "pending": "▫️", "skipped": "➖", "failed": "❌", "stopped": "⏹"}
STATUS_ICON = {"running": "⏳", "done": "✅", "error": "❌", "stopped": "⏹"}
PIPE_ICON = {"success": "🟢", "failed": "🔴", "running": "🔵", "pending": "🟡", "canceled": "⚪", "skipped": "⚪", "manual": "🟡", "created": "🟡"}
FLAGS = {"p": "push", "s": "skip-tests", "c": "conflict-only"}

_status = {"bot": "", "error": "", "running": False}
_pair = {"code": "", "until": 0.0}
_progress = {}
_seen_runs = set()
_lock = threading.Lock()
_boot = time.time()
esc = html.escape


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


def chat_id():
    value = cfg.get("telegram.chat_id")
    return int(value) if str(value or "").lstrip("-").isdigit() else None


def pair_code():
    if not _pair["code"] or time.time() > _pair["until"]:
        _pair.update(code=secrets.token_hex(4), until=time.time() + PAIR_TTL)
    return _pair["code"]


def public():
    configured = bool(cfg.secret("telegram.token"))
    out = {"configured": configured, "bot": _status["bot"], "running": _status["running"], "error": _status["error"], "linked": bool(chat_id()), "user": cfg.get("telegram.user") or ""}
    if configured and not out["linked"] and _status["bot"]:
        out["code"] = pair_code()
        out["link"] = f"https://t.me/{_status['bot']}?start={out['code']}"
    return out


def send(text, buttons=None, chat=None, edit=None):
    target = chat or chat_id()
    if not target:
        return None
    markup = {"inline_keyboard": buttons} if buttons else None
    try:
        if edit:
            return call("editMessageText", chat_id=target, message_id=edit, text=text[:4000], parse_mode="HTML", disable_web_page_preview=True, reply_markup=markup)
        return call("sendMessage", chat_id=target, text=text[:4000], parse_mode="HTML", disable_web_page_preview=True, reply_markup=markup)
    except TelegramError as exc:
        if "message is not modified" not in str(exc):
            log.warning("telegram send failed: %s", exc)
        return None


def _mrs():
    with lock:
        return [m for m in (state.get("review") or {}).get("mrs", []) if m.get("state") == "opened"]


def _mr(iid):
    with lock:
        return next((m for m in (state.get("review") or {}).get("mrs", []) if m["iid"] == iid), None)


def _skill():
    return cfg.get("claude.fix_skill") or "fix"


def _ref(iid):
    return ("#" if cfg.get("review.host") == "github" else "!") + str(iid)


def _url_button(text, url):
    return [{"text": text, "url": url}] if url and url.startswith("https://") else []


HELP = """<b>Opsboard</b>
/status — sessions, runs, requests, Claude limits
/mrs — your open requests
/mr 7376 — one request
/runs — fix runs
/fix 7376 push skip-tests — start the fix skill
/stop — stop a running fix"""


def cmd_status():
    with lock:
        sessions = state.get("sessions") or []
        usage = (state.get("claude_usage") or {}).get("limits") or []
        containers = state.get("containers") or []
    running = [r for r in runs.load_runs() if r["status"] == "running"]
    lines = [
        "<b>Opsboard</b>",
        f"🧠 {len(sessions)} Claude session(s), {sum(1 for s in sessions if s.get('status') == 'busy')} working",
        f"🔧 {len(running)} fix run(s) running",
        f"🔀 {len(_mrs())} open request(s)",
        f"🐳 {sum(1 for c in containers if c.get('state') == 'running')} container(s) running",
    ]
    for lim in usage:
        if lim.get("resets_at") and lim["resets_at"] < time.time():
            continue
        lines.append(f"📊 {esc(lim['label'])}: {lim['percent']}%")
    return "\n".join(lines), None


def cmd_mrs():
    mrs = _mrs()
    if not mrs:
        return "No open requests.", None
    lines, buttons = ["<b>Open requests</b>"], []
    for m in mrs[:15]:
        th = f" · 💬 {m['threads_total'] - (m['threads'] or 0)}/{m['threads_total']}" if m.get("threads_total") else ""
        lines.append(
            f"{PIPE_ICON.get(m.get('pipeline'), '⚪')} <b>{_ref(m['iid'])}</b> {esc(m['title'][:90])}{th}{' · ✅' if m.get('approved') else ''}{' · ⚠️ conflict' if m.get('conflicts') else ''}"
        )
        buttons.append({"text": _ref(m["iid"]), "callback_data": f"mr:{m['iid']}"})
    return "\n".join(lines), [buttons[i : i + 4] for i in range(0, len(buttons), 4)]


def cmd_mr(iid):
    m = _mr(iid)
    if not m:
        return f"{_ref(iid)} is not one of your requests.", None
    run = next((r for r in runs.load_runs() if r.get("iid") == iid and r["status"] == "running"), None)
    lines = [
        f"<b>{_ref(iid)}</b> {esc(m['title'])}",
        f"<code>{esc(m.get('source', ''))}</code> → <code>{esc(m.get('target', ''))}</code>",
        f"{PIPE_ICON.get(m.get('pipeline'), '⚪')} pipeline {esc(m.get('pipeline') or 'none')}",
        f"{'✅ approved by ' + esc(', '.join(m['approved_by'])) if m.get('approved') else '⏳ not approved yet'}",
    ]
    if m.get("threads_total"):
        lines.append(f"💬 {m['threads'] or 0} open of {m['threads_total']} threads")
    if m.get("conflicts"):
        lines.append("⚠️ merge conflict")
    if run:
        lines.append(f"⏳ {esc(_skill())} is running ({_dur(time.time() - run['started'])})")
    buttons = []
    if m.get("state") == "opened" and not run and cfg.get("telegram.allow_runs"):
        buttons.append([{"text": f"▶ Run {_skill()}", "callback_data": f"fixmenu:{iid}"}])
    if run:
        buttons.append([{"text": "⏹ Stop", "callback_data": f"stop:{run['id']}"}])
    buttons.append(_url_button("Open in GitLab" if cfg.get("review.host") != "github" else "Open in GitHub", m.get("url")))
    return "\n".join(lines), [b for b in buttons if b]


def cmd_runs():
    rs = runs.load_runs()[:8]
    if not rs:
        return "No fix runs yet.", None
    lines, buttons = ["<b>Fix runs</b>"], []
    for r in rs:
        took = _dur((time.time() if r["status"] == "running" else r.get("ended") or r["started"]) - r["started"])
        o = r.get("outcome") or {}
        lines.append(f"{STATUS_ICON.get(r['status'], '•')} <b>{_ref(r.get('iid'))}</b> {esc(r.get('name', ''))} · {took}{' · ' + esc(o['status']) if o.get('status') else ''}")
        if r["status"] == "running":
            buttons.append([{"text": f"⏹ Stop {_ref(r.get('iid'))}", "callback_data": f"stop:{r['id']}"}])
    return "\n".join(lines), buttons or None


def fix_menu(iid):
    if not cfg.get("telegram.allow_runs"):
        return "Starting fixes from Telegram is off — Opsboard → Settings → Telegram → <i>Allow fix runs</i>.", None
    m = _mr(iid)
    if not m or m.get("state") != "opened":
        return f"{_ref(iid)} is not one of your open requests.", None
    opts = [("Fix + push", "p"), ("Fix, no push", ""), ("Skip tests + push", "ps"), ("Conflict only + push", "pc")]
    return f"<b>{esc(_skill())} {_ref(iid)}</b>\n{esc(m['title'][:120])}\n\nHow should it run?", [[{"text": label, "callback_data": f"ask:{iid}:{flags}"}] for label, flags in opts] + [
        [{"text": "Cancel", "callback_data": "cancel"}]
    ]


def _prompt_words(flags):
    return " ".join(FLAGS[f] for f in flags if f in FLAGS)


def ask(iid, flags):
    words = _prompt_words(flags)
    return f"Run <code>/{esc(_skill())} {iid}{(' ' + words) if words else ''}</code>?\nIt works in your project folder and{' pushes, replies and resolves' if 'p' in flags else ' commits only'}.", [
        [{"text": "▶ Run", "callback_data": f"run:{iid}:{flags}"}, {"text": "Cancel", "callback_data": "cancel"}]
    ]


def start_fix(iid, flags):
    if not cfg.get("telegram.allow_runs"):
        raise ValueError("starting fixes from Telegram is off in Settings")
    prompt = runs.launch_fix({"iid": iid, "threads": "c" not in flags, "conflict": True, "skiptests": "s" in flags, "push": "p" in flags})
    return prompt


def _dur(s):
    s = max(0, int(s))
    return f"{s}s" if s < 60 else f"{s // 60}m" if s < 3600 else f"{s / 3600:.1f}h"


def progress_text(run, tl):
    m = _mr(run.get("iid")) or {}
    lines = [f"🔧 <b>{esc(run.get('name') or run.get('prompt', ''))}</b>"]
    if m.get("title"):
        lines.append(f"<i>{esc(m['title'][:120])}</i>")
    lines.append("")
    for p in tl["phases"]:
        took = _dur((time.time() if p["status"] == "running" else p["end"] or p["start"]) - p["start"]) if p.get("start") else ""
        extra = esc(p["note"]) if p.get("note") else took
        lines.append(f"{PHASE_ICON.get(p['status'], '▫️')} {esc(p['label'])}{' · ' + extra if extra else ''}")
    lines.append("")
    took = _dur((time.time() if run["status"] == "running" else run.get("ended") or run["started"]) - run["started"])
    if run["status"] == "running":
        say = next((e["text"] for e in reversed(tl["events"]) if e["kind"] == "say"), "")
        lines.append(f"⏳ running · {took}")
        if say:
            lines.append(f"💬 {esc(re.sub(r'[*`#>]', '', say).strip()[:300])}")
    else:
        o = run.get("outcome") or {}
        th = o.get("threads") or {}
        bits = [
            o.get("status") or run["status"],
            str(o.get("commit") or "")[:10],
            f"threads {th.get('resolved', 0)} resolved · {th.get('open', 0)} open" if th else "",
            o.get("checks") or "",
            o.get("note") or "",
        ]
        lines.append(f"{STATUS_ICON.get(run['status'], '•')} {esc(' · '.join(b for b in bits if b))} · {took}")
    return "\n".join(lines)


def progress_buttons(run):
    m = _mr(run.get("iid")) or {}
    rows = []
    if run["status"] == "running":
        rows.append([{"text": "⏹ Stop", "callback_data": f"stop:{run['id']}"}])
    link = _url_button("Open in GitLab" if cfg.get("review.host") != "github" else "Open in GitHub", m.get("url"))
    if link:
        rows.append(link)
    return rows or None


def track(run_id, chat=None):
    run = next((r for r in runs.load_runs() if r["id"] == run_id), None)
    if not run:
        return
    with _lock:
        _seen_runs.add(run_id)
    msg = send(progress_text(run, runs.run_timeline(run_id)), progress_buttons(run), chat=chat)
    if msg:
        with _lock:
            _progress[run_id] = {"chat": msg["chat"]["id"], "id": msg["message_id"], "text": ""}


def progress_tick():
    if not chat_id() or not cfg.get("telegram.notify"):
        return
    for r in runs.load_runs()[:20]:
        if r["status"] == "running" and r["id"] not in _seen_runs and r.get("started", 0) >= _boot - 5:
            track(r["id"])
    with _lock:
        items = list(_progress.items())
    for run_id, msg in items:
        run = next((r for r in runs.load_runs() if r["id"] == run_id), None)
        if not run:
            with _lock:
                _progress.pop(run_id, None)
            continue
        text = progress_text(run, runs.run_timeline(run_id))
        if text != msg["text"]:
            send(text, progress_buttons(run), chat=msg["chat"], edit=msg["id"])
            msg["text"] = text
        if run["status"] != "running":
            with _lock:
                _progress.pop(run_id, None)


def tracked(run_id):
    with _lock:
        return run_id in _seen_runs


def on_notify(item):
    if not chat_id() or not cfg.get("telegram.notify"):
        return
    if item.get("kind") == "run" and tracked(item.get("run_id")):
        return
    import notify

    head, body = notify.text(item)
    m = _mr(item.get("iid")) or {}
    icon = "💬" if item.get("kind") == "thread" else "✅" if item.get("status") == "done" else "❌"
    buttons = [b for b in [_url_button("Open in GitLab" if cfg.get("review.host") != "github" else "Open in GitHub", m.get("url"))] if b]
    if item.get("iid"):
        buttons.append([{"text": f"{_ref(item['iid'])} details", "callback_data": f"mr:{item['iid']}"}])
    send(f"{icon} <b>{esc(head)}</b>\n{esc(item.get('mr_title') or '')}\n\n{esc(body)[:1500]}", buttons or None)


def reply_for(text):
    words = text.strip().split()
    cmd = words[0].split("@")[0].lower() if words else ""
    args = words[1:]
    num = next((int(a.lstrip("!#")) for a in args if a.lstrip("!#").isdigit()), None)
    if cmd in ("/start", "/help"):
        return HELP, None
    if cmd == "/status":
        return cmd_status()
    if cmd == "/mrs":
        return cmd_mrs()
    if cmd == "/mr":
        return cmd_mr(num) if num else ("Usage: /mr 7376", None)
    if cmd == "/runs":
        return cmd_runs()
    if cmd == "/stop":
        return cmd_runs()
    if cmd == "/fix":
        if not num:
            return "Usage: /fix 7376 [push] [skip-tests] [conflict-only]", None
        if not cfg.get("telegram.allow_runs"):
            return fix_menu(num)
        flags = "".join(k for k, v in FLAGS.items() if v in [a.lower() for a in args])
        return ask(num, flags)
    return "Unknown command.\n\n" + HELP, None


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
            send("✅ Linked to this Opsboard.\n\n" + HELP, chat=chat["id"])
        elif parts[:1] == ["/start"]:
            send("This Opsboard is not linked yet. Open Opsboard → Settings → Telegram and use the link shown there.", chat=chat["id"])
        return
    if chat["id"] != linked:
        return
    text_out, buttons = reply_for(text)
    send(text_out, buttons)


def handle_callback(cq):
    msg = cq.get("message") or {}
    chat = (msg.get("chat") or {}).get("id")
    if not chat or chat != chat_id():
        return
    data = cq.get("data") or ""
    note = ""
    try:
        kind, _, rest = data.partition(":")
        if kind == "mr":
            send(*cmd_mr(int(rest)))
        elif kind == "fixmenu":
            text, buttons = fix_menu(int(rest))
            send(text, buttons, edit=msg.get("message_id"))
        elif kind == "ask":
            iid, _, flags = rest.partition(":")
            text, buttons = ask(int(iid), flags)
            send(text, buttons, edit=msg.get("message_id"))
        elif kind == "run":
            iid, _, flags = rest.partition(":")
            start_fix(int(iid), flags)
            send(f"▶ Started {esc(_skill())} {_ref(int(iid))}.", edit=msg.get("message_id"))
            newest = next((r for r in runs.load_runs() if r.get("iid") == int(iid) and r["status"] == "running"), None)
            if newest:
                track(newest["id"])
        elif kind == "stop":
            runs.stop_run(rest)
            note = "Stopping…"
        elif kind == "cancel":
            send("Cancelled.", edit=msg.get("message_id"))
    except (ValueError, TypeError) as exc:
        note = str(exc)[:190]
    try:
        call("answerCallbackQuery", callback_query_id=cq["id"], text=note or None)
    except TelegramError:
        pass


COMMANDS = [
    {"command": "status", "description": "Sessions, runs, requests, Claude limits"},
    {"command": "mrs", "description": "Your open requests"},
    {"command": "mr", "description": "One request: /mr 7376"},
    {"command": "runs", "description": "Fix runs"},
    {"command": "fix", "description": "Start the fix skill: /fix 7376 push"},
    {"command": "stop", "description": "Stop a running fix"},
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
                call("setMyCommands", commands=COMMANDS)
                known = tok
                _status.update(running=True, error="")
            updates = call("getUpdates", http_timeout=40, timeout=25, offset=offset, allowed_updates=["message", "callback_query"])
            _status.update(running=True, error="")
            for u in updates:
                offset = u["update_id"] + 1
                try:
                    if "message" in u:
                        handle_message(u["message"])
                    elif "callback_query" in u:
                        handle_callback(u["callback_query"])
                except Exception:  # noqa: BLE001
                    log.exception("telegram update failed")
        except TelegramError as exc:
            _status.update(running=False, error=str(exc))
            if "Unauthorized" in str(exc) or "Not Found" in str(exc):
                known = None
            time.sleep(10)


def progress_loop():
    while True:
        try:
            progress_tick()
        except Exception:  # noqa: BLE001
            log.exception("telegram progress failed")
        time.sleep(PROGRESS_EVERY)


def start():
    threading.Thread(target=bot_loop, daemon=True, name="telegram").start()
    threading.Thread(target=progress_loop, daemon=True, name="telegram-progress").start()
