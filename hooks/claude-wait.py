#!/usr/bin/env python3
"""Claude Code hook (Notification, PreToolUse AskUserQuestion): tells Opsboard a session is waiting for the user. Never blocks Claude."""

import json
import os
import sys
from pathlib import Path
from urllib import request

HERE = Path(__file__).resolve().parent.parent


def main():
    ev = json.load(sys.stdin)
    if ev.get("hook_event_name") == "PreToolUse":
        if ev.get("tool_name") != "AskUserQuestion":
            return
        qs = (ev.get("tool_input") or {}).get("questions") or []
        kind, message = "question", " / ".join(str(q.get("question") or "") for q in qs if isinstance(q, dict))
    else:
        kind, message = ev.get("notification_type") or "", ev.get("message") or ""
    data = Path(os.environ.get("OPS_DATA_DIR") or HERE)
    token = Path(os.environ.get("OPS_TOKEN_FILE") or data / ".page-token").read_text().strip()
    try:
        saved = json.loads((data / "config.json").read_text()).get("server.port")
        port = os.environ.get("OPS_PORT") or (saved.get("value") if isinstance(saved, dict) else saved) or 8095
    except (OSError, ValueError):
        port = 8095
    body = {"session_id": ev.get("session_id"), "cwd": ev.get("cwd"), "transcript_path": ev.get("transcript_path"), "type": kind, "message": message}
    req = request.Request(
        f"http://127.0.0.1:{port}/api/claude-wait",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "X-Ops-Token": token},
    )
    request.urlopen(req, timeout=2).read()


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001
        pass
    sys.exit(0)
