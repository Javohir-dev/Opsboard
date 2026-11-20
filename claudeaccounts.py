import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import claudelogins as logins
import claudeusage
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
_proposal = {}
_main = {"uuid": None}
_synced = {}
_pending = {}
_snooze = {"until": 0.0}
PROPOSAL_TTL, SNOOZE = 1800, 1800
ORDER = {"first": 0, "normal": 1, "last": 2}
DECIDED = []


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


def login_email():
    with lock:
        email = ((state.get("claude_usage") or {}).get("account") or {}).get("email") or ""
    if not email:
        try:
            email = (json.loads(Path(os.environ.get("OPS_CLAUDE_JSON", Path.home() / ".claude.json")).read_text()).get("oauthAccount") or {}).get("emailAddress") or ""
        except (OSError, ValueError):
            email = ""
    return email.lower()


def set_twin(aid):
    cfg.set("claude.main_twin", aid or None, "auto", "same limit windows")
    cfg.set("claude.main_twin_login", login_email() if aid else None, "auto", "Claude Code login")


def twin():
    """The setup-token account that is the same subscription as Claude Code's login — forgotten once you log in to another account."""
    uuid = _main["uuid"] or logins.account_json().get("accountUuid")
    signed = next((a["id"] for a in accounts() if uuid and a.get("uuid") == uuid), "")
    if signed:
        return signed
    t = cfg.get("claude.main_twin") or ""
    if not t or not any(a["id"] == t for a in accounts()):
        return ""
    known, now = (cfg.get("claude.main_twin_login") or "").lower(), login_email()
    return t if known and known == now else ""


def active_id():
    try:
        token = str((_read_settings().get("env") or {}).get(ENV_KEY) or "")
    except ValueError:
        return "other"
    if not token:
        return twin() or MAIN
    return next((a["id"] for a in accounts() if cfg.secret(secret_key(a["id"])) == token), "other")


def switch(aid):
    """Claude Code reads env from its user settings for every new session — VS Code included."""
    data = _read_settings()
    env = dict(data.get("env") or {})
    if aid != MAIN and signed_in(aid):
        use_login(aid)
        env.pop(ENV_KEY, None)
    elif aid == MAIN or (aid and aid == twin()):
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
    _proposal.clear()
    log.info("claude account: switched to %s", aid)


def record(aid):
    return next((a for a in accounts() if a["id"] == aid), None)


def signed_in(aid):
    """Signed in with Claude itself (full access), not only a setup token."""
    return bool((record(aid) or {}).get("uuid"))


def _save_record(aid, **fields):
    cfg.set("claude.accounts", [dict(a, **fields) if a["id"] == aid else a for a in accounts()], "user", "Accounts page")


def _unique_label(name):
    taken = {a.get("label", "").lower() for a in accounts()}
    out, n = name, 2
    while out.lower() in taken:
        out, n = f"{name} ({n})", n + 1
    return out


def main_identity():
    """Whose sign-in Claude Code holds now: asked from Anthropic by token, else what Claude Code itself recorded."""
    token, _ = logins.access()
    ident = logins.identity(token) if token else None
    if ident:
        return ident
    if not logins.oauth().get("refreshToken"):
        return None
    aj = logins.account_json()
    return {"uuid": aj["accountUuid"], "email": aj.get("emailAddress") or "", "plan": str(aj.get("organizationType") or "").replace("_", " ").title()} if aj.get("accountUuid") else None


def sync_login():
    """Keep the account Claude Code is signed in to on the list, with a current copy of its sign-in in its own slot."""
    if not (accounts() or cfg.get("claude.live_usage")):
        return None
    ident = main_identity()
    if not ident:
        return None
    _main["uuid"] = ident["uuid"]
    acc = next((a for a in accounts() if a.get("uuid") == ident["uuid"]), None)
    if not acc:
        email = (ident.get("email") or "").lower()
        old = cfg.get("claude.main_twin") if (cfg.get("claude.main_twin_login") or "").lower() == email and email else ""
        aid = next((a["id"] for a in accounts() if not a.get("uuid") and (a["id"] == old or a.get("label", "").lower() == email)), None)
        if aid:
            _save_record(aid, uuid=ident["uuid"], email=ident.get("email") or "", plan=ident.get("plan") or "")
        else:
            aid = uuid.uuid4().hex[:8]
            cfg.set("claude.accounts", accounts() + [{"id": aid, "label": _unique_label(ident.get("email") or "Claude account"), "added": int(time.time()), "uuid": ident["uuid"], "email": ident.get("email") or "", "plan": ident.get("plan") or ""}], "user", "Claude Code sign-in")
        acc = record(aid)
    aid, now = acc["id"], logins.oauth()
    mark = hash(json.dumps(now, sort_keys=True))
    if now.get("refreshToken") and _synced.get(aid) != mark:
        if logins.oauth(aid) == now or logins.put_oauth(aid, now):
            _synced[aid] = mark
    aj = logins.account_json()
    if aj.get("accountUuid") == ident["uuid"]:
        logins.put_account_json(aid, aj)
    elif logins.account_json(aid).get("accountUuid") == ident["uuid"]:
        logins.put_account_json(None, logins.account_json(aid))
    return aid


def use_login(aid):
    """Put this account's sign-in into Claude Code's own entry; the one it replaces is saved to its slot first."""
    rec = record(aid)
    current = sync_login()
    if current == aid:
        return
    mine = logins.oauth(aid)
    if not mine.get("refreshToken"):
        raise ValueError("sign in to this account first")
    if logins.oauth().get("refreshToken") and not current:
        raise ValueError("could not tell which account Claude Code is signed in to — try again in a moment")
    if not logins.put_oauth(None, mine):
        raise ValueError("could not update Claude Code's sign-in")
    stored = logins.account_json(aid)
    if stored.get("accountUuid") == rec["uuid"]:
        logins.put_account_json(None, stored)
    _main["uuid"] = rec["uuid"]
    _synced[aid] = hash(json.dumps(mine, sort_keys=True))


def login_begin(email="", aid=None, terminal=True):
    """Start a sign-in for one more account in its own config folder; Claude Code opens the browser."""
    import shlex

    email = str(email or "").strip()
    if email and not re.fullmatch(r"[^@\s'\"]+@[^@\s'\"]+", email):
        raise ValueError("this does not look like an email")
    if aid and not record(aid):
        raise ValueError("unknown account")
    slot = uuid.uuid4().hex[:8]
    logins.slot_dir(slot).mkdir(parents=True, exist_ok=True)
    cmd = f"CLAUDE_CONFIG_DIR={shlex.quote(str(logins.slot_dir(slot)))} {shlex.quote(claude_bin())} auth login --claudeai" + (f" --email {shlex.quote(email)}" if email else "")
    opened = False
    if terminal and sys.platform == "darwin" and not os.environ.get("OPS_NO_OS_NOTIFY"):
        try:
            script = ["-e", "on run argv", "-e", 'tell application "Terminal" to do script (item 1 of argv)', "-e", 'tell application "Terminal" to activate', "-e", "end run"]
            opened = subprocess.run(["osascript", *script, cmd + "; exit"], capture_output=True, timeout=20).returncode == 0
        except (OSError, subprocess.SubprocessError):
            opened = False
    _pending[slot] = {"at": time.time(), "for": aid, "email": email}
    return {"pid": slot, "command": cmd, "opened": opened}


def login_poll():
    """Finish sign-ins that have arrived; forget the ones nobody completed in 15 minutes."""
    done = []
    for slot, p in list(_pending.items()):
        token, _ = logins.access(slot)
        ident = logins.identity(token) if token else None
        if not ident:
            if time.time() - p["at"] > 900:
                _pending.pop(slot, None)
                logins.forget(slot)
            continue
        _pending.pop(slot, None)
        done.append(login_finish(slot, ident, p.get("for")))
    return done


def login_finish(slot, ident, wanted=None):
    known = next((a["id"] for a in accounts() if a.get("uuid") == ident["uuid"]), None)
    target = record(wanted) if wanted and not known else None
    if target and "@" in target.get("label", "") and target["label"].lower() != (ident.get("email") or "").lower():
        target = None
    aid = known or (target or {}).get("id")
    fields = {"uuid": ident["uuid"], "email": ident.get("email") or "", "plan": ident.get("plan") or ""}
    if aid:
        if aid != twin():
            logins.put_oauth(aid, logins.oauth(slot))
            logins.put_account_json(aid, logins.account_json(slot))
        logins.forget(slot)
        _save_record(aid, **fields)
    else:
        aid = slot
        cfg.set("claude.accounts", accounts() + [{"id": aid, "label": _unique_label(ident.get("email") or "Claude account"), "added": int(time.time()), **fields}], "user", "Accounts page")
    _usage[aid] = probe(aid)
    return aid


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
                for k in uni
                if k in ("five_hour", "seven_day") or (k.startswith("seven_day_") and "overage" not in k)
            }
            for k, w in windows.items():
                if k not in ("five_hour", "seven_day"):
                    w["label"] = k[len("seven_day_") :].replace("_", " ").title()
            if not windows and info.get("rateLimitType") in ("five_hour", "seven_day"):
                windows = {info["rateLimitType"]: {"percent": 100 if info.get("status") == "rejected" else 0, "resets_at": int(info.get("resetsAt") or 0), "status": info.get("status") or ""}}
        elif msg.get("type") == "result" and msg.get("is_error") and not windows:
            error = str(msg.get("result") or msg.get("subtype") or "the request failed")[:200]
    return windows, error


def main_token():
    if not cfg.get("claude.live_usage"):
        return None
    return claudeusage.token()[0]


def probe(aid):
    if aid != MAIN and signed_in(aid):
        return probe_login(aid)
    token = main_token() if aid == MAIN else cfg.secret(secret_key(aid))
    if not token:
        return {"error": "no token saved" if aid != MAIN else "", "at": time.time()}
    return probe_token(token)


def probe_login(aid):
    """A signed-in account: the one in Claude Code's own entry by its token, any other through its own config folder."""
    if aid == twin():
        token, why = logins.access()
        return probe_token(token) if token else {"error": why + " — open Claude Code once", "at": time.time()}
    result = run_probe({"CLAUDE_CONFIG_DIR": str(logins.slot_dir(aid))}, logins.slot_dir(aid))
    if result.get("windows"):
        token, _ = logins.access(aid)
        result["windows"].update(logins.scoped(token, aid))
    return result


def probe_token(token):
    return run_probe({ENV_KEY: token, "CLAUDE_CONFIG_DIR": str(PROBE_HOME)}, PROBE_HOME)


def run_probe(extra, home):
    home.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ANTHROPIC_", "CLAUDE_CODE_", "CLAUDE_CONFIG_DIR"))}
    env.update(extra)
    cmd = [claude_bin(), "-p", "Reply with: ok", "--model", "haiku", "--output-format", "stream-json", "--verbose", "--max-turns", "1", "--tools", "", "--strict-mcp-config", "--no-session-persistence"]
    try:
        r = subprocess.run(cmd, cwd=home, env=env, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
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
        name = str(lim.get("label") or "")
        if not k and lim.get("kind") == "weekly_scoped" and name.startswith("Weekly "):
            k = "seven_day_" + name[len("Weekly ") :].lower().replace(" ", "_")
        if k:
            windows[k] = {"percent": int(lim.get("percent") or 0), "resets_at": int(lim.get("resets_at") or 0), "status": lim.get("severity") or ""}
            if k.startswith("seven_day_"):
                windows[k]["label"] = name[len("Weekly ") :]
    if not windows:
        return {"error": cu.get("live_error") or ("" if cfg.get("claude.live_usage") else "Live Claude usage is off"), "at": 0}
    return {"windows": windows, "at": cu.get("fetched") or 0}


def usage(aid):
    if aid == MAIN:
        own = _usage.get(MAIN) or {}
        return own if own.get("windows") else main_usage()
    return _usage.get(aid) or {}


def same(a, b):
    """One subscription behind two tokens: both limit windows reset at the same second and are used alike."""
    wa, wb = (a or {}).get("windows") or {}, (b or {}).get("windows") or {}
    shared = [k for k in ("five_hour", "seven_day") if k in wa and k in wb]
    if not shared or any(not wa[k].get("resets_at") for k in shared):
        return False
    return all(wa[k]["resets_at"] == wb[k]["resets_at"] and abs(wa[k]["percent"] - wb[k]["percent"]) <= 1 for k in shared)


def pool():
    return ([] if twin() else [MAIN]) + [a["id"] for a in accounts()]


def duplicate_of(result, skip=()):
    """The account that turns out to be the same subscription, probed again now so the numbers are taken together."""
    for aid in pool():
        if aid in skip:
            continue
        if aid == MAIN and not main_token():
            continue
        _usage[aid] = probe(aid)
        if same(result, _usage[aid]):
            return aid
    return None


def dedupe():
    """Never deletes anything: when a setup-token account turns out to be the login's subscription, the login is hidden behind it."""
    if twin() or not main_token():
        return None
    for a in accounts():
        if not same(usage(MAIN), usage(a["id"])):
            continue
        _usage[MAIN], _usage[a["id"]] = probe(MAIN), probe(a["id"])
        if same(_usage[MAIN], _usage[a["id"]]):
            set_twin(a["id"])
            notify.claude_account({"kind": "claude_duplicate", "from": "Claude Code login", "to": label(a["id"])})
            return a["id"]
    return None


def watched(key):
    watch = cfg.get("claude.watch") or ["five_hour", "seven_day"]
    return key in watch or ("fable" in watch and key.startswith("seven_day_"))


def level(u, now=None):
    now = now or time.time()
    vals = [w["percent"] for k, w in (u.get("windows") or {}).items() if watched(k) and not (w.get("resets_at") and w["resets_at"] < now)]
    return max(vals) if vals else (0 if u.get("windows") else None)


def busy():
    with lock:
        sessions = list(state.get("sessions") or [])
        runs = list(state.get("runs") or [])
    return any(s.get("status") == "busy" for s in sessions) or any(r.get("status") == "running" for r in runs)


def order_of(aid):
    return next((a.get("order") or "normal" for a in accounts() if a["id"] == aid), "normal")


def pick(current, now=None, below=None):
    """Among accounts in auto-switch with fresh numbers under the target: Use first, then Normal, then Last resort; most room first."""
    now = now or time.time()
    below = int(cfg.get("claude.switch_to") or 60) if below is None else below
    cands = []
    for aid in pool():
        u = usage(aid)
        lv = level(u, now)
        if aid != current and enabled(aid) and lv is not None and lv < below and now - (u.get("at") or 0) < FRESH:
            cands.append((ORDER.get(order_of(aid), 1), lv, aid))
    return min(cands)[2] if cands else None


def label(aid):
    return "Claude Code login" if aid == MAIN else next((a.get("label") or aid for a in accounts() if a["id"] == aid), aid)


def measured(aid, now=None):
    """Numbers Opsboard took itself through Claude Code in the last 30 minutes — never Claude Code's cache."""
    u = _usage.get(aid) or {}
    return u if u.get("windows") and (now or time.time()) - (u.get("at") or 0) < FRESH else None


def auto_switch():
    """Asks before switching: a proposal in the dashboard and in Telegram, carried out only on a yes."""
    now = time.time()
    if _proposal and now - _proposal["at"] > PROPOSAL_TTL:
        _proposal.clear()
    if not cfg.get("claude.auto_switch") or not accounts():
        return None
    current = active_id()
    u = measured(current, now) if current != "other" else None
    if not u:
        return None
    lv = level(u, now)
    if lv < int(cfg.get("claude.switch_at") or 80):
        _full["warned"] = False
        if _proposal:
            _proposal.clear()
        return None
    if _proposal or now < _snooze["until"]:
        return None
    target = pick(current, now)
    if target:
        _usage[target] = probe(target)
        fresh = level(_usage[target])
        if fresh is None or fresh >= int(cfg.get("claude.switch_to") or 60):
            target = pick(current)
    if not target and cfg.get("claude.when_none") == "suggest":
        target = pick(current, now, below=lv)
    if not target:
        if not _full["warned"]:
            _full["warned"] = True
            notify.claude_account({"kind": "claude_full", "from": label(current), "level": lv})
        return None
    _proposal.update(pid=uuid.uuid4().hex[:10], src=current, dst=target, level=lv, to_level=level(usage(target)), at=now, msg=None)
    if cfg.get("claude.switch_mode") == "auto":
        decide(_proposal["pid"], True, "automatically")
        return target
    item = notify.claude_account(proposal_item())
    if "desktop" in (cfg.get("claude.ask_in") or []):
        notify.os_notify(*notify.text(item))
    return _proposal["pid"]


def _brief(aid):
    w = usage(aid).get("windows") or {}
    return {k: [w[k]["percent"], w[k].get("resets_at") or 0] for k in ("five_hour", "seven_day") if k in w}


def proposal_item():
    """Everything the bell and Telegram show for the open proposal: both accounts with both windows."""
    p = _proposal
    return {"kind": "claude_propose", "pid": p["pid"], "from": label(p["src"]), "to": label(p["dst"]), "level": p["level"], "to_level": p["to_level"], "busy": busy(), "src_w": _brief(p["src"]), "dst_w": _brief(p["dst"]), "switch_at": int(cfg.get("claude.switch_at") or 80)}


def decide(pid, yes, where="Opsboard"):
    """The answer to a switch proposal, from the dashboard or Telegram. Returns what happened, in one line."""
    if not _proposal or _proposal.get("pid") != pid:
        return "This question is no longer open."
    p = dict(_proposal)
    _proposal.clear()
    if not yes:
        _snooze["until"] = time.time() + SNOOZE
        result = f"Stayed on {label(p['src'])} — asks again in 30 minutes if it is still above the limit."
    elif p["dst"] != MAIN and not any(a["id"] == p["dst"] for a in accounts()):
        result = "That account was removed meanwhile — nothing changed."
    else:
        switch(p["dst"])
        _full["warned"] = False
        notify.claude_account({"kind": "claude_switch", "from": label(p["src"]), "to": label(p["dst"]), "level": p["level"], "to_level": p["to_level"], "how": where, "src_id": p["src"]})
        result = f"Switched to {label(p['dst'])} ({where})."
    for hook in DECIDED:
        threading.Thread(target=hook, args=(p, result), daemon=True).start()
    put("claude_accounts", public())
    return result


def save_rules(body):
    mode, when = body.get("mode"), body.get("when_none")
    watch = [w for w in body.get("watch") or [] if w in ("five_hour", "seven_day", "fable")]
    ask = [w for w in body.get("ask_in") or [] if w in ("sidebar", "telegram", "desktop")]
    at, to = int(body.get("switch_at")), int(body.get("switch_to"))
    if mode not in ("ask", "auto") or when not in ("suggest", "stay"):
        raise ValueError("unknown rule")
    if not watch:
        raise ValueError("watch at least one limit")
    if not (10 <= to < at <= 100):
        raise ValueError("the target must be below the trigger, both between 10 and 100")
    for key, value in (("claude.switch_mode", mode), ("claude.watch", watch), ("claude.ask_in", ask), ("claude.when_none", when), ("claude.switch_at", at), ("claude.switch_to", to)):
        cfg.set(key, value, "user", "Accounts page")
    if "auto_switch" in body:
        cfg.set("claude.auto_switch", bool(body["auto_switch"]), "user", "Accounts page")


def remember_message(pid, message_id):
    if _proposal.get("pid") == pid:
        _proposal["msg"] = message_id


def public():
    current = active_id()
    now = time.time()
    rows = []
    login = main_usage()
    with lock:
        plan = ((state.get("claude_usage") or {}).get("account") or {}).get("plan") or ""
    for aid in pool():
        u = usage(aid)
        windows = dict(u.get("windows") or {})
        if aid in (MAIN, twin()):
            windows.update({k: w for k, w in (login.get("windows") or {}).items() if k.startswith("seven_day_") and k not in windows})
        rows.append({"id": aid, "label": label(aid), "active": aid == current, "enabled": enabled(aid), "windows": windows, "plan": (record(aid) or {}).get("plan") or (plan if aid in (MAIN, twin()) else ""), "kind": "main" if aid == MAIN else "login" if signed_in(aid) else "token", "email": (record(aid) or {}).get("email") or "", "at": u.get("at") or 0, "error": u.get("error") or "", "level": level(u, now), "masked": cfg.masked(cfg.secret(secret_key(aid))) if aid != MAIN and cfg.secret(secret_key(aid)) else "", "login": aid == twin(), "added": next((x.get("added") or 0 for x in accounts() if x["id"] == aid), 0), "order": order_of(aid) if aid != MAIN else "normal", "resets": resets(aid)})
    prop = {k: _proposal[k] for k in ("pid", "level", "to_level", "at")} if _proposal else None
    if prop:
        prop.update(src=label(_proposal["src"]), dst=label(_proposal["dst"]))
    nxt = pick(current, now)
    for r in rows:
        r["next"] = r["id"] == nxt
    return {"active": current, "mode": cfg.get("claude.switch_mode") or "ask", "ask_in": cfg.get("claude.ask_in") or [], "watch": cfg.get("claude.watch") or [], "when_none": cfg.get("claude.when_none") or "stay", "confirm_manual": bool(cfg.get("claude.confirm_manual")), "proposal": prop, "pending": list(_pending), "accounts": rows, "busy": busy(), "refreshing": _refreshing["on"], "settings": str(SETTINGS).replace(str(Path.home()), "~", 1)}


def collect():
    try:
        sync_login()
    except (OSError, ValueError) as exc:
        log.warning("claude account: sign-in sync failed: %s", exc)
    current = active_id()
    now = time.time()
    if _probe_lock.acquire(blocking=False):
        try:
            login_poll()
            for aid in pool() if accounts() else []:
                due = ACTIVE_EVERY if aid == current else IDLE_EVERY
                if now - (_usage.get(aid) or {}).get("at", 0) >= due:
                    _usage[aid] = probe(aid)
            dedupe()
        finally:
            _probe_lock.release()
    try:
        auto_switch()
    except (OSError, ValueError) as exc:
        log.warning("claude account: auto switch failed: %s", exc)
    put("claude_accounts", public())


def check(token):
    """A token tried without saving it: its limits, or why Claude refused it."""
    token = str(token or "").strip()
    if not TOKEN_RE.fullmatch(token):
        raise ValueError("this does not look like a token from claude setup-token")
    if any(cfg.secret(secret_key(a["id"])) == token for a in accounts()):
        raise ValueError("this token is already added")
    result = probe_token(token)
    if not result.get("windows"):
        raise ValueError(f"Claude did not accept this token: {result.get('error')}")
    return result


def add(name, token, include=True, switch_now=False):
    name, token = str(name or "").strip()[:40], str(token or "").strip()
    if not name:
        name = f"Account {cfg.masked(token)}"
    if not TOKEN_RE.fullmatch(token):
        raise ValueError("this does not look like a token from claude setup-token")
    if any(cfg.secret(secret_key(a["id"])) == token for a in accounts()):
        raise ValueError("this token is already added")
    if any(a.get("label", "").lower() == name.lower() for a in accounts()):
        raise ValueError(f"an account named «{name}» is already added")
    result = probe_token(token)
    if not result.get("windows"):
        raise ValueError(f"Claude did not accept this token: {result.get('error')}")
    with _probe_lock:
        dup = duplicate_of(result)
    if dup and dup != MAIN:
        raise ValueError(f"This account is already added as «{label(dup)}»")
    aid = uuid.uuid4().hex[:8]
    cfg.set_secret(secret_key(aid), token)
    _usage[aid] = result
    if dup == MAIN:
        set_twin(aid)
    cfg.set("claude.accounts", accounts() + [{"id": aid, "label": name, "added": int(time.time())}], "user", "Accounts page")
    if not include:
        set_enabled(aid, False)
    if switch_now:
        switch(aid)
    put("claude_accounts", public())
    return aid


def update(aid, name=None, order=None, token=None):
    """The Edit dialog: name, order when several have room, a new token for the same account."""
    if not any(a["id"] == aid for a in accounts()):
        raise ValueError("unknown account")
    if name is not None:
        rename(aid, name)
    if order is not None:
        if order not in ORDER:
            raise ValueError("unknown order")
        cfg.set("claude.accounts", [dict(a, order=order) if a["id"] == aid else a for a in accounts()], "user", "Accounts page")
    if token:
        result = check(token)
        if not same(result, usage(aid)) and (usage(aid).get("windows")):
            raise ValueError("this token belongs to another account — add it as a new one")
        in_use = active_id() == aid and twin() != aid
        cfg.set_secret(secret_key(aid), str(token).strip())
        _usage[aid] = result
        if in_use:
            switch(aid)


def rename(aid, name):
    name = str(name or "").strip()[:40]
    if not name:
        raise ValueError("give the account a name")
    if not any(a["id"] == aid for a in accounts()):
        raise ValueError("unknown account")
    if any(a["id"] != aid and a.get("label", "").lower() == name.lower() for a in accounts()):
        raise ValueError(f"an account named «{name}» is already added")
    cfg.set("claude.accounts", [dict(a, label=name) if a["id"] == aid else a for a in accounts()], "user", "Accounts page")


def remove(aid):
    if not any(a["id"] == aid for a in accounts()):
        raise ValueError("unknown account")
    if signed_in(aid) and aid == twin():
        raise ValueError("Claude Code is signed in to this account — switch to another one first")
    if active_id() == aid:
        switch(MAIN)
    if signed_in(aid):
        logins.forget(aid)
        _synced.pop(aid, None)
    if cfg.get("claude.main_twin") == aid:
        set_twin("")
    set_enabled(aid, True)
    cfg.set("claude.accounts", [a for a in accounts() if a["id"] != aid] or None, "user", "Settings page")
    cfg.set_secret(secret_key(aid), "")
    _usage.pop(aid, None)
    put("claude_accounts", public())


def resets(aid):
    """Limit resets Anthropic has granted this account; only a signed-in account can see or use them."""
    if aid in (MAIN, twin()):
        return claudeusage.resets()
    return logins.resets(aid) if signed_in(aid) else []


def use_reset(aid, grant):
    """Spend one reset of this account. Runs only on the person's own confirmed click, never by itself."""
    found = next((r for r in resets(aid) if r["id"] == grant), None)
    if not found:
        raise ValueError("This reset is no longer offered — refresh and look again")
    if not found["usable"]:
        raise ValueError("This reset cannot be used right now")
    token, why = logins.access(None if aid in (MAIN, twin()) else aid)
    if not token:
        raise ValueError(f"{label(aid)}: {why}")
    org = (logins.identity(token) or {}).get("org_uuid")
    if not org:
        raise ValueError("Could not tell which organization this account belongs to — nothing was used")
    ok, result, data = logins.claim_reset(token, org, grant)
    log.info("claude account: reset %s on %s -> %s", grant, aid, result)
    claudeusage.expire()
    (logins._usage.get(aid) or {})["next"] = 0.0
    _usage.pop(aid, None)
    if not ok:
        texts = {"already_used": "This reset was already used", "not_limited": "This reset can only be used at a limit", "cooldown": "A reset was used recently — wait and try again", "ineligible": "This account cannot use the reset", "unavailable": "Anthropic could not reset the limits right now — nothing was used"}
        raise ValueError(texts.get(result) or f"The reset did not go through ({result}) — check the limits before trying again")
    left = data.get("resets_left")
    return f"Limits reset for {label(aid)}" + (f" · {left} left" if isinstance(left, int) else "")


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
                for aid in pool():
                    _usage[aid] = probe(aid)
                dedupe()
        finally:
            _refreshing["on"] = False
            put("claude_accounts", public())

    threading.Thread(target=run, daemon=True, name="claude-accounts-refresh").start()
