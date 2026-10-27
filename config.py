import json
import os
import threading
from pathlib import Path

import secretstore

HERE = Path(__file__).parent
CONFIG_FILE = Path(os.environ.get("OPS_CONFIG") or Path(os.environ.get("OPS_DATA_DIR", HERE)) / "config.json")
SOURCES = ("user", "agent", "auto")

DEFAULTS = {
    "ui.language": "",
    "ui.theme": "system",
    "ui.hotkeys": {},
    "server.port": 8095,
    "project.root": "",
    "project.worktrees": "",
    "project.profile": "",
    "review.host": "gitlab",
    "tasks.tracker": "",
    "github.url": "https://github.com",
    "github.repo": "",
    "github.username": "",
    "gitlab.url": "",
    "gitlab.project": "",
    "gitlab.username": "",
    "jira.site": "",
    "jira.email": "",
    "jira.name": "",
    "jira.jql": "assignee = currentUser() ORDER BY updated DESC",
    "jira.status_map": {},
    "db.container": "",
    "db.user": "",
    "jira.projects": [],
    "claude.bin": "",
    "claude.version": "",
    "claude.skills": [],
    "claude.background_runs": True,
    "claude.permission_mode": "auto",
    "claude.reply_language": "thread",
    "claude.fix_skill": "",
    "claude.live_usage": True,
    "notify.sound": True,
    "notify.battery_low": 15,
    "telegram.chat_id": "",
    "telegram.user": "",
    "telegram.notify": True,
    "telegram.claude_chat": False,
    "telegram.chat_permission": "plan",
    "telegram.language": "auto",
    "refresh.tasks_seconds": 300,
}
SECRETS = ("jira.token", "gitlab.token", "github.token", "telegram.token")
ENV = {
    "project.root": "OPS_HIS_ROOT",
    "db.container": "OPS_DB_CONTAINER",
    "db.user": "OPS_DB_USER",
    "jira.site": "OPS_JIRA_SITE",
    "gitlab.url": "OPS_GITLAB",
    "gitlab.project": "OPS_GITLAB_PROJECT",
    "server.port": "OPS_PORT",
}

_lock = threading.RLock()
_cache = {"mtime": None, "data": None}


def _empty():
    return {"version": 1, "settings": {}, "secrets": {}}


def load():
    with _lock:
        try:
            mtime = CONFIG_FILE.stat().st_mtime
        except OSError:
            return _empty()
        if _cache["mtime"] != mtime:
            try:
                data = json.loads(CONFIG_FILE.read_text())
            except (OSError, ValueError):
                data = _empty()
            data.setdefault("settings", {})
            data.setdefault("secrets", {})
            _cache.update(mtime=mtime, data=data)
        return _cache["data"]


def save(data):
    with _lock:
        tmp = CONFIG_FILE.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        os.replace(tmp, CONFIG_FILE)
        _cache.update(mtime=None, data=None)


def entry(key):
    if key in ENV and os.environ.get(ENV[key]):
        return {"value": os.environ[ENV[key]], "source": "env", "from": ENV[key]}
    stored = load()["settings"].get(key) or {}
    for src in SOURCES:
        if src in stored:
            return dict(stored[src], source=src)
    return {"value": DEFAULTS.get(key), "source": "default"}


def get(key, fallback=None):
    value = entry(key).get("value")
    return fallback if value in (None, "") else value


def set(key, value, source="user", origin="", confidence=None):
    if source not in SOURCES:
        raise ValueError(f"unknown source {source}")
    if key not in DEFAULTS:
        raise ValueError(f"unknown setting {key}")
    with _lock:
        data = load()
        slot = data["settings"].setdefault(key, {})
        if value is None:
            slot.pop(source, None)
            if not slot:
                data["settings"].pop(key)
        else:
            item = {"value": value}
            if origin:
                item["from"] = origin
            if confidence is not None:
                item["confidence"] = confidence
            if slot.get(source) == item:
                return
            slot[source] = item
        save(data)


_secrets = {}


def secret(key):
    with _lock:
        if key in _secrets:
            return _secrets[key]
        data = load()
        stored = data["secrets"].get(key, "")
        value = secretstore.read(key) if secretstore.backend() else None
        if value is None:
            value = stored
            if stored and secretstore.write(key, stored):
                data["secrets"].pop(key, None)
                save(data)
        elif stored:
            data["secrets"].pop(key, None)
            save(data)
        _secrets[key] = value
        return value


def set_secret(key, value):
    if key not in SECRETS:
        raise ValueError(f"unknown secret {key}")
    with _lock:
        _secrets.pop(key, None)
        data = load()
        if value and secretstore.write(key, value):
            data["secrets"].pop(key, None)
        elif value:
            data["secrets"][key] = value
        else:
            secretstore.delete(key)
            data["secrets"].pop(key, None)
        save(data)


def masked(value):
    return f"••••{value[-4:]}" if value else ""


def public():
    data = load()
    out = {}
    for key in DEFAULTS:
        e = entry(key)
        stored = data["settings"].get(key, {})
        e["resettable"] = "auto" in stored or "agent" in stored or DEFAULTS[key] not in ("", [], {}, None)
        out[key] = e
    out["_secrets"] = {key: masked(secret(key)) for key in SECRETS}
    out["_secret_store"] = secretstore.name()
    return out
