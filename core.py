import json
import logging
import logging.handlers
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib import request

import config as cfg
import stackprofile as profile

HERE = Path(__file__).parent
CLAUDE = Path.home() / ".claude"
SESSIONS = CLAUDE / "sessions"
PROJECTS = CLAUDE / "projects"
if "unittest" in sys.modules and not os.environ.get("OPS_DATA_DIR"):
    raise SystemExit("Run the tests with: python3 -m unittest discover -s tests -t .  (tests/__init__.py keeps them away from your real data)")
DATA = Path(os.environ.get("OPS_DATA_DIR", HERE))
log = logging.getLogger("opsboard")


def setup_logging():
    handler = logging.handlers.RotatingFileHandler(DATA / "opsboard.log", maxBytes=1_000_000, backupCount=3)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)


MODULE_CACHE = DATA / "mr-modules.json"
RUNS_FILE = DATA / "runs.json"
RUNS_DIR = DATA / "runs"


def project_root():
    root = cfg.get("project.root")
    return Path(root).expanduser() if root else None


def worktree_paths():
    configured = cfg.get("project.worktrees")
    if configured:
        folder = Path(configured).expanduser()
        return sorted(p for p in folder.iterdir() if (p / ".git").exists()) if folder.is_dir() else []
    root = project_root()
    if not root:
        return []
    repo = root / profile.get("worktrees.repo", ".")
    listing = run(["git", "-C", str(repo), "worktree", "list", "--porcelain"]) if repo.exists() else ""
    paths = [Path(line[9:]) for line in listing.splitlines() if line.startswith("worktree ")]
    return [p for p in paths[1:] if p.exists()]


def db_container():
    return cfg.get("db.container") or ""


def db_user():
    return cfg.get("db.user") or profile.get("defaults", {}).get("db.user") or "postgres"


def jira_site():
    return (cfg.get("jira.site") or "").rstrip("/")


def gitlab_url():
    return (cfg.get("gitlab.url") or "").rstrip("/")


def gitlab_project():
    return cfg.get("gitlab.project") or ""


def claude_bin():
    return cfg.get("claude.bin") or shutil.which("claude") or str(Path.home() / ".local" / "bin" / "claude")


runs_lock = threading.Lock()
popen = {}


def key_regex():
    projects = [p for p in (cfg.get("jira.projects") or []) if re.fullmatch(r"[A-Z][A-Z0-9]{1,9}", p)]
    return re.compile(r"\b((?:" + "|".join(projects) + r")-\d+)\b" if projects else r"\b([A-Z][A-Z0-9]{1,9}-\d+)\b")


state = {"history": {"cpu": [], "mem": [], "gpu": [], "net_in": [], "net_out": []}}
lock = threading.Lock()


def run(cmd, timeout=15):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def put(key, value):
    with lock:
        state[key] = value


def loop(interval, fn):
    def worker():
        while True:
            try:
                fn()
                with lock:
                    state.pop(f"error_{fn.__name__}", None)
            except Exception as exc:  # noqa: BLE001
                with lock:
                    first = state.get(f"error_{fn.__name__}") != repr(exc)
                    state[f"error_{fn.__name__}"] = repr(exc)
                if first:
                    log.exception("collector %s failed", fn.__name__)
            time.sleep(interval)

    threading.Thread(target=worker, daemon=True).start()


def size_bytes(text):
    m = re.match(r"([\d.]+)\s*([KMGT]?)", text.strip())
    return float(m.group(1)) * 1024 ** "_KMGT".index(m.group(2) or "_") if m else 0


def epoch(ts):
    try:
        ts = re.sub(r"(\.\d{6})\d+", r"\1", ts.replace("Z", "+00:00"))
        ts = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", ts)
        return datetime.fromisoformat(ts).timestamp() if not ts.startswith("0001") else 0
    except (AttributeError, ValueError):
        return 0


def http_json(url, headers, data=None, timeout=20, method=None):
    req = request.Request(url, data=json.dumps(data).encode() if data is not None else None, headers=headers, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
