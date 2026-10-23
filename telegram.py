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

import config as cfg
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
    return f"<b>Opsboard</b>\n/mrs — your open requests\n/mr 7376 — one request\n/sessions — Claude sessions that are working, with their agents\n/usage — Claude plan limits and when they reset\n/info — linked accounts, this Mac and the bot's settings{chat}"


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
    with lock:
        usage = dict(state.get("claude_usage") or {})
    if not (live_on and usage.get("limits")):
        usage = system.claude_usage(live=False) or {}
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
    if usage.get("source") == "live":
        lines.append("⚡ live — updated every minute")
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
    },
    "en": {"started": "▶ {name} started · {at}", "done": "✅ {name} finished", "error": "❌ {name} failed", "stopped": "⏹ {name} stopped", "busy": "A fix is already running for this request"},
    "ru": {
        "started": "▶ {name} запущен · {at}",
        "done": "✅ {name} завершён",
        "error": "❌ {name} завершился с ошибкой",
        "stopped": "⏹ {name} остановлен",
        "busy": "Для этого запроса исправление уже идёт",
    },
}
_pending, _fix_msgs, _sent_texts, _pending_lock = {}, {}, {}, threading.Lock()
THREAD_GROUP = 3


def _bot_lang():
    chosen = cfg.get("telegram.language") or "auto"
    if chosen in OPENED:
        return chosen
    ui = (cfg.get("ui.language") or "")[:2]
    return ui if ui in OPENED else "uz"


def _fix_buttons(iid):
    m = _mr(iid) or {}
    if m.get("role", "author") != "author":
        link = _url_button(f"Open in {_host()}", m.get("url"))
        return [link] if link else None
    skill = cfg.get("claude.fix_skill") or "fix"
    return [[{"text": f"▶ {skill}", "callback_data": f"fix:{iid}:"}, {"text": f"⚡ {skill} ultra", "callback_data": f"fix:{iid}:p"}]]


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
    if item.get("kind") == "merged":
        if cfg.get("telegram.notify"):
            link = _url_button(f"Open in {_host()}", item.get("url"))
            send(_merged_text(item), [link] if link else None)
        return
    if item.get("kind") == "run":
        _fix_finished(item)
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


def _thread_text(iid, group):
    one, many = OPENED[_bot_lang()]
    who = ", ".join(group["authors"]) or "?"
    line = (one if group["n"] == 1 else many).format(who=f"<b>{esc(who)}</b>", n=group["n"])
    m = _mr(iid) or {}
    title = group["title"] or m.get("title") or ""
    role = {"uz": " · sizga assign qilingan", "en": " · assigned to you", "ru": " · назначен вам"}[_bot_lang()] if m.get("role") == "assignee" else ""
    return f"💬 <b>{_ref(iid)}</b>{role} — {line}" + (f"\n<i>{esc(title[:140])}</i>" if title else "")


def _flush_threads(iid):
    with _pending_lock:
        group = _pending.pop(iid, None)
    if group:
        text = _thread_text(iid, group)
        msg = send(text, _fix_buttons(iid))
        if msg:
            with _pending_lock:
                _sent_texts[msg["message_id"]] = text
                while len(_sent_texts) > 200:
                    _sent_texts.pop(next(iter(_sent_texts)))


def _start_fix(cq, iid, push):
    msg = cq.get("message") or {}
    words = FIX_STATE[_bot_lang()]
    skill = cfg.get("claude.fix_skill") or "fix"
    name = f"{skill} ultra" if push else skill
    import runs

    if any(r.get("iid") == iid and r["status"] == "running" for r in runs.load_runs()):
        return words["busy"]
    runs.launch_fix({"iid": iid, "threads": True, "conflict": True, "skiptests": False, "push": push})
    run = next((r for r in runs.load_runs() if r.get("iid") == iid and r["status"] == "running"), None)
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
    bits = [o.get("status") or "", str(o.get("commit") or "")[:10], f"{th.get('resolved', 0)}/{th.get('resolved', 0) + th.get('open', 0)} threads" if th else ""]
    detail = " · ".join(b for b in bits if b)
    status = words[key].format(name=esc(tracked["name"])) + (f" · {esc(detail)}" if detail else "")
    edit(tracked["message_id"], f"{tracked['base']}\n\n{status}")


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


def edit(message_id, text, plain=False, chat=None):
    params = {"chat_id": chat or chat_id(), "message_id": message_id, "text": text[:4096], "disable_web_page_preview": True}
    if not plain:
        params["parse_mode"] = "HTML"
    try:
        return call("editMessageText", **params)
    except TelegramError as exc:
        if "not modified" in str(exc):
            return True
        log.warning("telegram edit failed: %s", exc)
        return None


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


WAIT = {
    "en": [
        "🤔 One moment, let me think…",
        "🧠 Gathering my thoughts…",
        "☕ One sip of coffee and I'm on it…",
        "🧩 It's starting to come together…",
        "🐢 Slow and careful — nearly there…",
        "✨ Polishing the answer…",
        "🧭 Finding the right way to put it…",
        "📝 Preparing the answer…",
        "⏳ Just a moment…",
        "💡 Good question — thinking it through…",
    ],
    "uz": [
        "🤔 Kutib turing, o'ylab olay…",
        "🧠 Fikrlarni jamlayapman…",
        "☕ Bir qultum choy — va davom etaman…",
        "🧩 Rasm aniqlashib qoldi…",
        "🐢 Shoshmasdan, puxta — oz qoldi…",
        "✨ Javobni sayqallayapman…",
        "🧭 To'g'ri yo'lni topyapman…",
        "📝 Javobni tayyorlayapman…",
        "⏳ Bir zum…",
        "💡 Yaxshi savol, o'ylab ko'ryapman…",
    ],
    "ru": [
        "🤔 Секунду, подумаю…",
        "🧠 Собираюсь с мыслями…",
        "☕ Глоток кофе — и продолжаю…",
        "🧩 Картина складывается…",
        "🐢 Медленно, но верно — почти готово…",
        "✨ Шлифую ответ…",
        "🧭 Ищу, как лучше сказать…",
        "📝 Готовлю ответ…",
        "⏳ Минутку…",
        "💡 Хороший вопрос, обдумываю…",
    ],
}
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
    if chosen in WAIT:
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
    return ui if ui in WAIT else "uz"


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
        self.lock = threading.Lock()

    @property
    def busy(self):
        return bool(self.turns)

    def _start(self):
        mode = cfg.get("telegram.chat_permission") or "plan"
        root = project_root()
        sid = _load_chat().get("session_id")
        cmd = [claude_bin(), "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose", "--permission-mode", mode] + (["--resume", sid] if sid else [])
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

    def ask(self, text, message_id=None):
        lang = lang_of(text)
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
            msg = send(_waiting_text(QUEUED[lang] if queued else random.choice(WAIT[lang]), time.time(), ""))
            self.turns.append({"placeholder": (msg or {}).get("message_id"), "started": time.time(), "lang": lang, "phrases": random.sample(WAIT[lang], len(WAIT[lang]))})
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
            if ev.get("session_id") and ev.get("type") in ("system", "result") and _load_chat().get("session_id") != ev["session_id"]:
                _save_chat({"session_id": ev["session_id"], "at": time.time()})
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
                if ev.get("is_error") or not answer:
                    note = "⚠️ " + esc((answer or "Claude did not answer").strip()[-800:])
                    if not (turn and turn["placeholder"] and edit(turn["placeholder"], note)):
                        send(note)
                elif turn:
                    deliver(answer, turn["placeholder"])
                else:
                    send(f"<i>{esc(EXTRA[self.lang])}</i>")
                    deliver(answer)
        err = (proc.stderr.read() or "").strip() if proc.stderr else ""
        with self.lock:
            left, self.turns = self.turns, []
            if self.proc is proc:
                self.proc = None
        for turn in left:
            text = CANCELLED[turn["lang"]] if proc.returncode and proc.returncode < 0 else "⚠️ " + esc((err or "Claude stopped")[-500:])
            if not (turn["placeholder"] and edit(turn["placeholder"], text)):
                send(text)

    def _tick(self, proc):
        n = 0
        while proc.poll() is None:
            time.sleep(1)
            n += 1
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
            if n % 5 == 0 and turn["placeholder"]:
                phrase = turn["phrases"][(n // 5) % len(turn["phrases"])]
                edit(turn["placeholder"], _waiting_text(phrase, turn["started"], self.doing))

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
        _save_chat({})


CHAT = ClaudeChat()


def _waiting_text(phrase, started, doing):
    return f"{esc(phrase)}\n\n<i>⏱ {_dur(time.time() - started)}{' · ' + esc(doing) if doing else ''}</i>"


def reply_for(text, message_id=None):
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
    if cmd == "/info":
        return cmd_info()
    if cmd == "/usage":
        return cmd_usage()
    if cmd == "/new":
        CHAT.reset()
        return "🆕 New conversation with Claude.", None
    if cmd == "/cancel":
        return (None, None) if CHAT.cancel() else ("Nothing to cancel.", None)
    if cmd:
        return "Unknown command.\n\n" + help_text(), None
    if not cfg.get("telegram.claude_chat"):
        return "Claude chat is off — Opsboard → Settings → Telegram → <i>Claude chat</i>.\n\n" + help_text(), None
    threading.Thread(target=CHAT.ask, args=(text.strip(), message_id), daemon=True).start()
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
    text_out, buttons = reply_for(text, msg.get("message_id"))
    if text_out:
        send(text_out, buttons)


def handle_callback(cq):
    msg = cq.get("message") or {}
    if not chat_id() or (msg.get("chat") or {}).get("id") != chat_id():
        return
    kind, _, rest = (cq.get("data") or "").partition(":")
    note = ""
    if kind == "mr" and rest.isdigit():
        send(*cmd_mr(int(rest)))
    elif kind == "fix":
        iid, _, flags = rest.partition(":")
        try:
            note = _start_fix(cq, int(iid), "p" in flags)
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
