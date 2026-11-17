import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

from core import DATA, lock

NOTES_FILE = Path(os.environ.get("OPS_NOTES", DATA / "notes.json"))
NOTES_HISTORY = NOTES_FILE.parent / "notes-history"
notes_lock = threading.Lock()


def load_notes():
    try:
        return json.loads(NOTES_FILE.read_text())
    except (OSError, ValueError):
        return {"version": 0, "items": [], "trash": []}


NOTE_EVENTS = ("created", "text", "tag", "deleted", "restored", "imported")


def clean_note(it):
    if not isinstance(it, dict):
        raise ValueError("bad note item")
    history = []
    for h in (it.get("history") or [])[-200:]:
        if isinstance(h, dict) and h.get("type") in NOTE_EVENTS:
            history.append(
                {
                    "t": float(h.get("t") or 0),
                    "type": h["type"],
                    "from": str(h.get("from", ""))[:2000],
                    "to": str(h.get("to", ""))[:2000],
                }
            )
    return {
        "id": str(it.get("id", ""))[:40] or uuid.uuid4().hex[:10],
        "kind": "divider" if it.get("kind") == "divider" else "item",
        "text": str(it.get("text", ""))[:5000],
        "done": bool(it.get("done")),
        "tag": it.get("tag") if it.get("tag") in ("todo", "warn", "done") else "",
        "indent": max(0, min(4, int(it.get("indent") or 0))),
        "collapsed": bool(it.get("collapsed")),
        "created": float(it.get("created") or time.time()),
        "updated": float(it.get("updated") or it.get("created") or time.time()),
        "done_at": float(it.get("done_at") or 0),
        "deleted_at": float(it.get("deleted_at") or 0),
        "last_text": str(it.get("last_text", it.get("text", "")))[:5000],
        "history": history,
    }


def save_notes(body):
    items, trash = body.get("items"), body.get("trash") or []
    if not isinstance(items, list) or len(items) > 5000 or not isinstance(trash, list):
        raise ValueError("bad notes payload")
    clean = [clean_note(it) for it in items]
    clean_trash = [clean_note(it) for it in trash[-300:]]
    with notes_lock:
        current = load_notes()
        client = int(body.get("version", -1))
        if client < current.get("version", 0):
            return {"ok": False, "conflict": True, "notes": current}
        if NOTES_FILE.exists():
            NOTES_HISTORY.mkdir(exist_ok=True)
            backup = NOTES_HISTORY / f"{int(time.time() * 1000)}-v{current.get('version', 0)}.json"
            fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as fh:
                json.dump(current, fh, ensure_ascii=False)
            for old in sorted(NOTES_HISTORY.glob("*.json"))[:-50]:
                old.unlink(missing_ok=True)
        doc = {"version": max(client, current.get("version", 0)) + 1, "items": clean, "trash": clean_trash}
        tmp = NOTES_FILE.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump(doc, fh, ensure_ascii=False)
        os.replace(tmp, NOTES_FILE)
    return {"ok": True, "version": doc["version"]}


MARKS_FILE = DATA / "marks.json"
MARK_COLORS = {"red", "orange", "yellow", "green", "blue", "purple", "gray"}


def load_marks():
    try:
        return json.loads(MARKS_FILE.read_text())
    except (OSError, ValueError):
        return {}


def set_mark(key, color):
    if not re.fullmatch(r"[A-Z][A-Z0-9]{1,9}-\d+|!\d+", key or ""):
        raise ValueError("bad task key")
    if color and color not in MARK_COLORS:
        raise ValueError("bad color")
    with lock:
        marks = load_marks()
        if color:
            marks[key] = color
        else:
            marks.pop(key, None)
        MARKS_FILE.write_text(json.dumps(marks))
