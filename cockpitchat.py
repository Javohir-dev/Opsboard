"""Claude Code sessions that Cockpit starts and you write to from the browser. Each is one long-lived
`claude -p` process with stream-json input. Its permission prompts and questions come over stdio
(`--permission-prompt-tool stdio`, as the VS Code extension does) and wait on the Waiting page,
in the chat and in Telegram until you answer."""

import json
import os
import re
import signal
import subprocess
import threading
import time
import uuid
from pathlib import Path

import claudewait
import safety
from core import DATA, claude_bin, log, project_root

KEEP = 20
SAVED = DATA / "cockpit-sessions.json"
MODES = ("default", "acceptEdits", "plan", "auto")
ASSIST_ROLE = (
    "You are the Opsboard assistant: a small chat panel in the corner of Opsboard, the dashboard Javohir runs on his Mac "
    "(sessions, Jira, GitLab, Docker, Postgres, worktrees, Claude accounts). Each of his messages starts with an "
    "<ops-context> block: the Opsboard page he has open and the text visible on it. Use it; 'this', 'here' and "
    "'that one' refer to it. You may read, edit and run what his request needs on this Mac. "
    "When he asks to pass work to another Claude Code session (or to 'tell that session ...'), load ListAgents and "
    "SendMessage with ToolSearch (select:ListAgents,SendMessage), find the session by name, send it the full "
    "instruction in plain words, and tell him which session got it. Never delete user data, push, or spend a Claude "
    "limit reset unless he says so in this chat. Answer short: the result first, in his language."
)
_sessions, _lock = {}, threading.Lock()


class CockpitSession:
    def __init__(self, cwd, resume="", fork=False, title="", assistant=False, mode="default"):
        self.key = uuid.uuid4().hex[:10]
        self.cwd = str(cwd)
        self.sid = ""
        self.title = title
        self.busy = False
        self.error = ""
        self.assistant = assistant
        self.parent = resume
        self.first = ""
        self.mode = "auto" if assistant else (mode if mode in MODES else "default")
        self.started = self.last = time.time()
        cmd = [claude_bin(), "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose", "--permission-mode", self.mode, "--permission-prompt-tool", "stdio"]
        if assistant:
            cmd += ["--append-system-prompt", ASSIST_ROLE]
        if resume:
            cmd += ["--resume", resume] + (["--fork-session"] if fork else [])
        env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_CODE_")}
        env["OPS_COCKPIT"] = "1"
        self.proc = subprocess.Popen(cmd, cwd=self.cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1, start_new_session=True)
        threading.Thread(target=self._read, daemon=True).start()

    def alive(self):
        return self.proc.poll() is None

    def send(self, text):
        if not self.alive():
            raise ValueError("this session has ended — start a new one")
        self.proc.stdin.write(json.dumps({"type": "user", "message": {"role": "user", "content": text}}) + "\n")
        self.proc.stdin.flush()
        self.busy, self.last = True, time.time()
        if not self.first:
            self.first = re.sub(r"<ops-context>[\s\S]*?</ops-context>", "", text).strip()[:300]
        if not self.title:
            self.title = re.sub(r"\s+", " ", re.sub(r"<ops-context>[\s\S]*?</ops-context>", "", text)).strip()[:60]

    def _read(self):
        for line in self.proc.stdout:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("session_id") and ev.get("type") in ("system", "result") and ev["session_id"] != self.parent and ev["session_id"] != self.sid:
                self.sid = ev["session_id"]
                _save()
            if ev.get("type") == "control_request":
                self._control(ev)
                continue
            if ev.get("type") == "result":
                self.busy, self.last = False, time.time()
                if ev.get("is_error"):
                    self.error = str(ev.get("result") or ev.get("subtype") or "Claude stopped with an error")[:300]
        err = (self.proc.stderr.read() or "").strip() if self.proc.stderr else ""
        self.busy = False
        if self.proc.returncode and not self.error:
            self.error = (err or f"Claude exited ({self.proc.returncode})")[-300:]

    def _respond(self, request_id, response):
        try:
            self.proc.stdin.write(json.dumps({"type": "control_response", "response": {"subtype": "success", "request_id": request_id, "response": response}}) + "\n")
            self.proc.stdin.flush()
        except (OSError, ValueError):
            pass

    def _control(self, ev):
        handle_control(ev, self.sid or self.key, self.cwd, self._respond, self.alive)

    def set_mode(self, mode):
        if mode not in MODES:
            raise ValueError("unknown mode")
        if not self.alive():
            raise ValueError("this session has ended")
        self.proc.stdin.write(json.dumps({"type": "control_request", "request_id": uuid.uuid4().hex, "request": {"subtype": "set_permission_mode", "mode": mode}}) + "\n")
        self.proc.stdin.flush()
        self.mode = mode

    def interrupt(self):
        if self.alive():
            try:
                os.killpg(self.proc.pid, signal.SIGINT)
            except (ProcessLookupError, PermissionError):
                pass

    def close(self):
        if self.alive():
            try:
                self.proc.stdin.close()
            except OSError:
                pass

    def public(self):
        return {"key": self.key, "sid": self.sid, "cwd": self.cwd.replace(str(Path.home()), "~", 1), "title": self.title, "busy": self.busy, "assistant": self.assistant, "parent": self.parent, "first": self.first, "mode": self.mode,
                "alive": self.alive(), "error": self.error, "started": self.started, "last": self.last}


def handle_control(ev, sid, cwd, respond, alive, on_allow=None):
    """A headless Claude asks permission over --permission-prompt-tool stdio: hold it in claudewait (the Cockpit and
    Telegram ask him) and answer with his decision."""
    rid, req = ev.get("request_id"), ev.get("request") or {}
    if req.get("subtype") != "can_use_tool":
        respond(rid, {})
        return
    name, args = req.get("tool_name") or "", req.get("input") or {}
    questions = [q for q in args.get("questions") or [] if isinstance(q, dict)] if name == "AskUserQuestion" else []
    held = claudewait.report({
        "session_id": sid, "cwd": cwd, "transcript_path": None, "cockpit": True,
        "type": "question_request" if questions else "permission_request",
        "message": " / ".join(str(q.get("question") or "") for q in questions) if questions else summary(name, args, req.get("description") or ""),
        "questions": questions,
    })
    if not isinstance(held, str):
        respond(rid, {"behavior": "deny", "message": "Opsboard could not ask the user (Claude waiting alerts are off)."})
        return
    threading.Thread(target=_await, args=(rid, held, name, args, respond, alive, on_allow), daemon=True).start()


def _await(rid, held, name, args, respond, alive, on_allow):
    while alive():
        out = claudewait.poll(held)
        if out.get("decision") == "allow":
            respond(rid, {"behavior": "allow", "updatedInput": dict(args, answers=out["answers"]) if out.get("answers") else args})
            if on_allow:
                on_allow(name)
            return
        if out.get("decision") == "deny":
            note = out.get("message") or ""
            respond(rid, {"behavior": "deny", "message": f"The user denied this and said: {note}" if note else "The user denied this."})
            return
        if not out.get("open"):
            respond(rid, {"behavior": "deny", "message": "The request expired without an answer."})
            return
        time.sleep(0.5)


def summary(name, args, description=""):
    for key in ("command", "file_path", "url", "pattern", "plan"):
        if args.get(key):
            return f"{name}: {str(args[key])[:400]}" + (f" — {description}" if description and key == "command" else "")
    return f"{name}: {description}" if description else name


class Ended:
    """A Cockpit session from before a restart: shown in the list, and resumed with its history when he writes to it."""

    def __init__(self, row):
        self.key, self.sid, self.cwd = row["key"], row["sid"], row["cwd"]
        self.title, self.parent, self.first = row.get("title") or "", row.get("parent") or "", row.get("first") or ""
        self.mode, self.assistant = row.get("mode") or "default", bool(row.get("assistant"))
        self.started = self.last = row.get("last") or time.time()
        self.busy, self.error = False, ""

    def alive(self):
        return False

    def set_mode(self, mode):
        if mode not in MODES:
            raise ValueError("unknown mode")
        self.mode = mode

    def interrupt(self):
        pass

    close = interrupt

    def public(self):
        return {"key": self.key, "sid": self.sid, "cwd": self.cwd.replace(str(Path.home()), "~", 1), "title": self.title, "busy": False, "assistant": self.assistant,
                "parent": self.parent, "first": self.first, "mode": self.mode, "alive": False, "resumable": True, "error": "", "started": self.started, "last": self.last}


def _save():
    with _lock:
        rows = [{"key": s.key, "sid": s.sid, "cwd": s.cwd, "title": s.title, "parent": s.parent, "first": s.first, "mode": s.mode, "assistant": s.assistant, "last": s.last}
                for s in _sessions.values() if s.sid]
    try:
        safety.allow_write(SAVED)
        tmp = SAVED.with_suffix(".tmp")
        tmp.write_text(json.dumps(rows[-KEEP:]))
        os.chmod(tmp, 0o600)
        tmp.replace(SAVED)
    except (OSError, RuntimeError) as exc:
        log.warning("cockpit: could not save sessions: %s", exc)


def _load():
    try:
        rows = json.loads(SAVED.read_text())
    except (OSError, ValueError):
        return
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and row.get("sid") and row.get("key"):
            _sessions[row["key"]] = Ended(row)


def start(text, cwd="", resume="", fork=False, assistant=False, mode="default"):
    text = (text or "").strip()
    if not text:
        raise ValueError("write the first message")
    folder = Path(os.path.expanduser(cwd)) if cwd else project_root() or (Path.home() if assistant else None)
    if not folder or not Path(folder).is_dir():
        raise ValueError("choose an existing folder")
    if resume and not re.fullmatch(r"[0-9a-f-]{8,64}", resume):
        raise ValueError("not a session id")
    s = CockpitSession(folder, resume, fork, "", assistant, mode)
    s.send(text)
    with _lock:
        _sessions[s.key] = s
        dead = [k for k, x in _sessions.items() if not x.alive()]
        for k in dead[: max(0, len(_sessions) - KEEP)]:
            _sessions.pop(k, None)
    log.info("cockpit: started a session in %s", s.cwd)
    return s.public()


def find(ref):
    with _lock:
        return _sessions.get(ref) or next((s for s in _sessions.values() if s.sid and s.sid == ref), None)


def send(ref, text):
    s = find(ref)
    if not s:
        raise ValueError("this session is not one Cockpit started")
    text = (text or "").strip()
    if not text:
        raise ValueError("write a message first")
    if not s.alive():
        fresh = CockpitSession(s.cwd, s.sid, False, s.title, s.assistant, s.mode)
        fresh.key, fresh.sid, fresh.parent, fresh.first = s.key, s.sid, s.parent, s.first
        fresh.resumed = s.sid
        with _lock:
            _sessions[s.key] = fresh
        s = fresh
        log.info("cockpit: resumed %s", s.sid[:8])
    s.send(text)
    return s.public()


def set_mode(ref, mode):
    s = find(ref)
    if not s:
        raise ValueError("unknown session")
    s.set_mode(mode)
    return s.public()


def stop(ref, close=False):
    s = find(ref)
    if not s:
        raise ValueError("unknown session")
    s.close() if close else s.interrupt()
    return s.public()


_load()


def public():
    with _lock:
        return [s.public() for s in sorted(_sessions.values(), key=lambda x: -x.last)]
