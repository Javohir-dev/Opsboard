import json
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid

import config as cfg
from core import DATA, log

FILE = DATA / "notifications.json"
SEEN_FILE = DATA / "threads-seen.json"
STATES_FILE = DATA / "mr-states.json"
KEEP = 100
PAGE_GONE = 75
_lock = threading.Lock()
_last_alerting_page = 0.0
HOOKS = []


def load():
    try:
        items = json.loads(FILE.read_text())
        return items if isinstance(items, list) else []
    except (OSError, ValueError):
        return []


def _save(items):
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(items[:KEEP], ensure_ascii=False))
    os.replace(tmp, FILE)


def page_seen(alerts):
    global _last_alerting_page
    if alerts:
        _last_alerting_page = time.time()


def run_finished(r, mr_title=""):
    item = {
        "id": uuid.uuid4().hex[:12],
        "kind": "run",
        "run_id": r["id"],
        "iid": r.get("iid"),
        "name": r.get("name", ""),
        "status": r["status"],
        "outcome": r.get("outcome"),
        "error": ((r.get("result") or "").strip().splitlines() or [""])[-1][:300] if r["status"] == "error" else "",
        "mr_title": mr_title,
        "at": time.time(),
        "read": False,
    }
    return _publish(item, "run_id", item["status"] == "error" or (item.get("outcome") or {}).get("status") == "stopped")


def _publish(item, same, bad=False):
    with _lock:
        items = [x for x in load() if not (x.get("kind") == item["kind"] and x.get(same) == item[same])]
        _save([item] + items)
    if time.time() - _last_alerting_page > PAGE_GONE:
        os_notify(*text(item))
    if cfg.get("notify.sound"):
        play_sound(bad)
    for hook in HOOKS:
        threading.Thread(target=hook, args=(item,), daemon=True).start()
    return item


def new_threads(mrs, me):
    """Announce review threads opened on your requests since the last look; the first look at a request only remembers them."""
    try:
        seen = json.loads(SEEN_FILE.read_text())
    except (OSError, ValueError):
        seen = None
    first_run = seen is None
    seen = seen or {}
    fresh = []
    for m in mrs:
        heads = m.pop("_threads", None)
        if heads is None or m.get("state") != "opened":
            continue
        key = str(m["iid"])
        known = set(seen.get(key, []))
        if not first_run and key in seen:
            fresh += [(m, t) for t in heads if t["id"] not in known and t.get("username") != me]
        seen[key] = sorted(known | {t["id"] for t in heads})
    opened = {str(m["iid"]) for m in mrs if m.get("state") == "opened"}
    seen = {k: v for k, v in seen.items() if k in opened}
    tmp = SEEN_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(seen))
    os.replace(tmp, SEEN_FILE)
    for m, t in fresh:
        _publish(
            {
                "id": uuid.uuid4().hex[:12],
                "kind": "thread",
                "thread_id": t["id"],
                "iid": m["iid"],
                "mr_title": m.get("title", ""),
                "author": t.get("author", ""),
                "body": " ".join(str(t.get("body") or "").split())[:300],
                "path": t.get("path") or "",
                "line": t.get("line"),
                "status": "thread",
                "at": time.time(),
                "read": False,
            },
            "thread_id",
        )
    return [t for _, t in fresh]


def merged(mrs):
    """Announce requests that went from open to merged since the last look; the first look only remembers states."""
    try:
        before = json.loads(STATES_FILE.read_text())
    except (OSError, ValueError):
        before = None
    now = {str(m["iid"]): m.get("state") for m in mrs}
    tmp = STATES_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(now))
    os.replace(tmp, STATES_FILE)
    if before is None:
        return []
    done = [m for m in mrs if m.get("state") == "merged" and before.get(str(m["iid"])) == "opened"]
    for m in done:
        _publish(
            {
                "id": uuid.uuid4().hex[:12],
                "kind": "merged",
                "iid": m["iid"],
                "mr_title": m.get("title", ""),
                "url": m.get("url", ""),
                "source": m.get("source", ""),
                "target": m.get("target", ""),
                "merged_by": m.get("merged_by", ""),
                "created": m.get("created") or 0,
                "merged_at": m.get("merged") or time.time(),
                "threads_total": m.get("threads_total") or 0,
                "approved_by": m.get("approved_by") or [],
                "status": "merged",
                "at": time.time(),
                "read": False,
            },
            "iid",
        )
    return done


def text(item):
    o = item.get("outcome") or {}
    ref = f"!{item['iid']}" if item.get("iid") else item.get("name", "")
    if item.get("kind") == "merged":
        return f"Merged · {ref}", (item.get("mr_title") or "") + (f" — by {item['merged_by']}" if item.get("merged_by") else "")
    if item.get("kind") == "thread":
        where = f" · {item['path'].split('/')[-1]}:{item['line']}" if item.get("path") and item.get("line") else ""
        return f"New thread · {ref}{where}", f"{item.get('author', '')}: {item.get('body', '')}"
    if item["status"] == "error":
        head, body = f"Fix failed · {ref}", item.get("error") or "the run ended with an error"
    elif o.get("status") == "stopped":
        head, body = f"Fix stopped · {ref}", o.get("note") or "it could not finish"
    else:
        head = f"Fix {o.get('status') or 'finished'} · {ref}"
        th = o.get("threads") or {}
        parts = [str(o["commit"])[:10] if o.get("commit") else "", f"threads {th.get('resolved', 0)} resolved · {th.get('open', 0)} open" if th else "", o.get("checks") or "", o.get("note") or ""]
        body = " · ".join(p for p in parts if p) or item.get("mr_title") or "done"
    return head, body


def mark_read(ids=None):
    with _lock:
        items = load()
        for x in items:
            if ids is None or x["id"] in ids:
                x["read"] = True
        _save(items)


def clear():
    with _lock:
        _save([])


def os_notify(title, body):
    if os.environ.get("OPS_NO_OS_NOTIFY"):
        return
    try:
        if sys.platform == "darwin":
            script = ["-e", "on run argv", "-e", 'display notification (item 2 of argv) with title "Opsboard" subtitle (item 1 of argv)', "-e", "end run"]
            subprocess.Popen(["osascript", *script, title, body], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif shutil.which("notify-send"):
            subprocess.Popen(["notify-send", "-a", "Opsboard", title, body], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        log.warning("desktop notification failed: %s", exc)


MAC_SOUNDS = {False: "/System/Library/Sounds/Glass.aiff", True: "/System/Library/Sounds/Basso.aiff"}
LINUX_SOUNDS = {False: "/usr/share/sounds/freedesktop/stereo/complete.oga", True: "/usr/share/sounds/freedesktop/stereo/dialog-warning.oga"}


def play_sound(bad=False):
    if os.environ.get("OPS_NO_OS_NOTIFY"):
        return False
    if sys.platform == "darwin":
        cmd = ["afplay", MAC_SOUNDS[bad]]
    else:
        player = shutil.which("paplay") or shutil.which("pw-play")
        if not player or not os.path.exists(LINUX_SOUNDS[bad]):
            return False
        cmd = [player, LINUX_SOUNDS[bad]]
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError as exc:
        log.warning("notification sound failed: %s", exc)
        return False
