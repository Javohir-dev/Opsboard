#!/usr/bin/env python3
"""Claude Code hook: tells Opsboard a session is waiting for the user (Notification, PreToolUse AskUserQuestion).
On PermissionRequest in a VS Code session it also waits for an Allow/Deny from Telegram; the dialog on the Mac stays
open meanwhile and whichever answer comes first wins. Never fails and never blocks a terminal session."""

import json
import os
import sys
import time
from pathlib import Path
from urllib import request

HERE = Path(__file__).resolve().parent.parent
HOLD = 29 * 60
COCKPIT = os.environ.get("OPS_COCKPIT") == "1"


def _post(data, port, token, body):
    req = request.Request(
        f"http://127.0.0.1:{port}/api/claude-wait",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "X-Ops-Token": token},
    )
    return json.loads(request.urlopen(req, timeout=3).read() or b"{}")


def _entrypoint(sid):
    folder = Path(os.environ.get("OPS_CLAUDE_SESSIONS") or Path.home() / ".claude" / "sessions")
    for f in folder.glob("*.json"):
        try:
            meta = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if meta.get("sessionId") == sid:
            return meta.get("entrypoint") or ""
    return ""


def _summary(name, args):
    args = args or {}
    for key in ("command", "file_path", "url", "pattern", "description"):
        if args.get(key):
            return f"{name}: {str(args[key])[:400]}"
    return name


def _later():
    """In VS Code the PermissionRequest hook carries the question with buttons; this copy reports 3 s later in the
    background only as a fallback (Opsboard ignores it when the held request already arrived), so Claude never waits."""
    if os.fork():
        return False
    os.setsid()
    fd = os.open(os.devnull, os.O_RDWR)
    for n in (0, 1, 2):
        os.dup2(fd, n)
    time.sleep(3)
    return True


def main():
    ev = json.load(sys.stdin)
    event = ev.get("hook_event_name")
    if COCKPIT and event in ("PermissionRequest", "PreToolUse"):
        return
    questions = [q for q in ((ev.get("tool_input") or {}).get("questions") or []) if isinstance(q, dict)]
    if event == "PreToolUse":
        if ev.get("tool_name") != "AskUserQuestion":
            return
        if (_entrypoint(ev.get("session_id")) == "claude-vscode" or COCKPIT) and not _later():
            return
        kind, message = "question", " / ".join(str(q.get("question") or "") for q in questions)
    elif event == "PermissionRequest":
        if ev.get("tool_name") == "ExitPlanMode" or (_entrypoint(ev.get("session_id")) != "claude-vscode" and not COCKPIT):
            return
        if ev.get("tool_name") == "AskUserQuestion":
            kind, message = "question_request", " / ".join(str(q.get("question") or "") for q in questions)
        else:
            kind, message = "permission_request", _summary(ev.get("tool_name") or "", ev.get("tool_input"))
    else:
        kind, message = ev.get("notification_type") or "", ev.get("message") or ""
    data = Path(os.environ.get("OPS_DATA_DIR") or HERE)
    token = Path(os.environ.get("OPS_TOKEN_FILE") or data / ".page-token").read_text().strip()
    try:
        saved = json.loads((data / "config.json").read_text()).get("server.port")
        port = os.environ.get("OPS_PORT") or (saved.get("value") if isinstance(saved, dict) else saved) or 8095
    except (OSError, ValueError):
        port = 8095
    body = {"session_id": ev.get("session_id"), "cwd": ev.get("cwd"), "transcript_path": ev.get("transcript_path"), "type": kind, "message": message, "questions": questions, "cockpit": COCKPIT}
    req = _post(data, port, token, body).get("ok")
    if kind not in ("permission_request", "question_request") or not isinstance(req, str):
        return
    end = time.time() + HOLD
    while time.time() < end:
        time.sleep(2)
        out = _post(data, port, token, {"poll": req})
        if out.get("decision") in ("allow", "deny"):
            decision = {"behavior": out["decision"]}
            if out["decision"] == "deny":
                decision["message"] = f"The user denied this and said: {out['message']}" if out.get("message") else "Denied from Telegram."
            elif out.get("answers"):
                decision["updatedInput"] = dict(ev.get("tool_input") or {}, answers=out["answers"])
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": decision}}))
            return
        if not out.get("open"):
            return


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001
        pass
    sys.exit(0)
