import html
import json
import os
import re
import secrets
import signal
import subprocess
import threading
import time
from pathlib import Path
from urllib import error, request

import config as cfg
from core import DATA, claude_bin, lock, log, project_root, state

API = os.environ.get("OPS_TELEGRAM_API", "https://api.telegram.org").rstrip("/")
PAIR_TTL = 15 * 60
CHAT_TIMEOUT = 20 * 60
CHAT_FILE = DATA / "telegram-chat.json"
PIPE_ICON = {"success": "🟢", "failed": "🔴", "running": "🔵", "pending": "🟡", "canceled": "⚪", "skipped": "⚪", "manual": "🟡", "created": "🟡"}

_status = {"bot": "", "error": "", "running": False}
_pair = {"code": "", "until": 0.0}
_chat = {"proc": None, "busy": False}
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
    out = {
        "configured": configured,
        "bot": _status["bot"],
        "running": _status["running"],
        "error": _status["error"],
        "linked": bool(chat_id()),
        "user": cfg.get("telegram.user") or "",
        "chat_busy": _chat["busy"],
    }
    if configured and not out["linked"] and _status["bot"]:
        out["code"] = pair_code()
        out["link"] = f"https://t.me/{_status['bot']}?start={out['code']}"
    return out


def send(text, buttons=None, chat=None, plain=False):
    target = chat or chat_id()
    if not target:
        return None
    params = {"chat_id": target, "text": text[:4096], "disable_web_page_preview": True, "reply_markup": {"inline_keyboard": buttons} if buttons else None}
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


def help_text():
    chat = "\n\nAny other message goes to Claude on your Mac. /new starts a fresh conversation, /cancel stops the current answer." if cfg.get("telegram.claude_chat") else ""
    return f"<b>Opsboard</b>\n/mrs — your open requests\n/mr 7376 — one request\n/sessions — Claude sessions that are working, with their agents{chat}"


def cmd_mrs():
    mrs = _mrs()
    if not mrs:
        return "No open requests.", None
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


def on_notify(item):
    if item.get("kind") != "thread" or not chat_id() or not cfg.get("telegram.notify"):
        return
    m = _mr(item.get("iid")) or {}
    where = f" · <code>{esc(item['path'].split('/')[-1])}:{item['line']}</code>" if item.get("path") and item.get("line") else ""
    text = f"💬 <b>New thread · {_ref(item['iid'])}</b>{where}\n{esc(item.get('mr_title') or m.get('title') or '')}\n\n<b>{esc(item.get('author') or '')}</b>: {esc(item.get('body') or '')[:1500]}"
    link = _url_button(f"Open in {_host()}", m.get("url"))
    send(text, [link] if link else None)


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
        out.append(s)
    return "".join(out).strip()


def send_long(text):
    formatted = md_to_html(text)
    if len(formatted) <= 4000 and send(formatted):
        return
    chunk = ""
    for line in (text or "").splitlines(keepends=True):
        if len(chunk) + len(line) > 3800:
            send(chunk, plain=True)
            chunk = ""
        chunk += line
    if chunk.strip():
        send(chunk, plain=True)


def _load_chat():
    try:
        return json.loads(CHAT_FILE.read_text())
    except (OSError, ValueError):
        return {}


def _save_chat(data):
    CHAT_FILE.write_text(json.dumps(data))


def ask_claude(text):
    if _chat["busy"]:
        send("Still answering the previous message — /cancel stops it.")
        return
    _chat["busy"] = True
    threading.Thread(target=_run_claude, args=(text,), daemon=True).start()


def _kill(proc):
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass


def _run_claude(text):
    mode = cfg.get("telegram.chat_permission") or "plan"
    root = project_root()
    cwd = str(root) if root and root.is_dir() else str(Path.home())
    sid = _load_chat().get("session_id")
    cmd = [claude_bin(), "-p", text, "--output-format", "json", "--permission-mode", mode] + (["--resume", sid] if sid else [])
    try:
        proc = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    except OSError as exc:
        _chat["busy"] = False
        send(f"Could not start Claude: {esc(str(exc))}")
        return
    _chat["proc"] = proc
    out, err, started = "", "", time.time()
    while True:
        try:
            call("sendChatAction", chat_id=chat_id(), action="typing")
        except TelegramError:
            pass
        try:
            out, err = proc.communicate(timeout=4.5)
            break
        except subprocess.TimeoutExpired:
            if time.time() - started > CHAT_TIMEOUT:
                _kill(proc)
                send(f"Stopped: no answer after {CHAT_TIMEOUT // 60} minutes.")
    _chat.update(proc=None, busy=False)
    if proc.returncode and proc.returncode < 0:
        send("Cancelled.")
        return
    try:
        res = json.loads(out.strip().splitlines()[-1]) if out.strip() else {}
    except ValueError:
        res = {}
    if res.get("session_id"):
        _save_chat({"session_id": res["session_id"], "at": time.time()})
    answer = str(res.get("result") or "").strip()
    if res.get("is_error") or not answer:
        if sid and not res:
            _save_chat({})
        send("⚠️ " + esc((answer or err or "Claude did not answer").strip()[-800:]))
        return
    send_long(answer)


def reply_for(text):
    words = text.strip().split()
    cmd = words[0].split("@")[0].lower() if words and words[0].startswith("/") else ""
    num = next((int(a.lstrip("!#")) for a in words[1:] if a.lstrip("!#").isdigit()), None)
    if cmd in ("/start", "/help"):
        return help_text(), None
    if cmd == "/mrs":
        return cmd_mrs()
    if cmd == "/mr":
        return cmd_mr(num) if num else ("Usage: /mr 7376", None)
    if cmd == "/sessions":
        return cmd_sessions()
    if cmd == "/new":
        _save_chat({})
        return "🆕 New conversation with Claude.", None
    if cmd == "/cancel":
        if not _chat["proc"]:
            return "Nothing to cancel.", None
        _kill(_chat["proc"])
        return None, None
    if cmd:
        return "Unknown command.\n\n" + help_text(), None
    if not cfg.get("telegram.claude_chat"):
        return "Claude chat is off — Opsboard → Settings → Telegram → <i>Claude chat</i>.\n\n" + help_text(), None
    ask_claude(text.strip())
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
    text_out, buttons = reply_for(text)
    if text_out:
        send(text_out, buttons)


def handle_callback(cq):
    msg = cq.get("message") or {}
    if not chat_id() or (msg.get("chat") or {}).get("id") != chat_id():
        return
    kind, _, rest = (cq.get("data") or "").partition(":")
    if kind == "mr" and rest.isdigit():
        send(*cmd_mr(int(rest)))
    try:
        call("answerCallbackQuery", callback_query_id=cq["id"])
    except TelegramError:
        pass


COMMANDS = [
    {"command": "mrs", "description": "Your open requests"},
    {"command": "mr", "description": "One request: /mr 7376"},
    {"command": "sessions", "description": "Working Claude sessions and their agents"},
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


def start():
    threading.Thread(target=bot_loop, daemon=True, name="telegram").start()
