import os
import re
import shlex
import subprocess
import threading
import time
from pathlib import Path

import stackprofile as profile
from core import db_container, db_user, lock, log, project_root, run, state, worktree_paths

NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")
_jobs = {}
_jobs_lock = threading.Lock()


def _find(name):
    if not NAME.match(name or ""):
        raise ValueError("not a worktree name")
    for wt in worktree_paths():
        if wt.name == name:
            return wt
    raise ValueError(f"{name} is not one of your worktrees")


def _git(path, *args, timeout=30):
    return run(["git", "-C", str(path), *args], timeout=timeout)


def _project():
    with lock:
        return next((c.get("project") or "" for c in state.get("containers") or [] if c.get("name") == db_container()), "")


def resources(name):
    slug = profile.worktree_slug(name)
    project = _project()
    container_t = profile.get("containers", {}).get("per_worktree") or ""
    containers = [container_t.format(project=project, slug=slug)] if container_t and (project or "{project}" not in container_t) else []
    databases = [t.format(slug=slug) for t in profile.get("databases", {}).get("per_worktree") or []]
    with lock:
        running = {c["name"] for c in state.get("containers") or []}
        sizes = dict(state.get("pg_sizes") or {})
    return slug, [c for c in containers if c in running], [d for d in databases if d in sizes]


def plan(name):
    wt = _find(name)
    branch = _git(wt, "rev-parse", "--abbrev-ref", "HEAD").strip()
    slug, containers, databases = resources(name)
    uncommitted = [line for line in _git(wt, "status", "--porcelain", timeout=30).splitlines() if line.strip()]
    unpushed = [line for line in _git(wt, "log", "--oneline", "HEAD", "--not", "--remotes").splitlines() if line.strip()]
    warnings = []
    if uncommitted:
        warnings.append({"kind": "uncommitted", "text": f"{len(uncommitted)} uncommitted change(s)", "items": uncommitted[:10]})
    if unpushed:
        warnings.append({"kind": "unpushed", "text": f"{len(unpushed)} commit(s) that are not pushed anywhere", "items": unpushed[:10]})
    with lock:
        mrs = [m for m in (state.get("review") or {}).get("mrs", []) if m.get("source") == branch and m.get("state") == "opened"]
        sessions = [s for s in state.get("sessions") or [] if str(s.get("cwd") or "").startswith(str(wt))]
    for m in mrs:
        warnings.append({"kind": "mr", "text": f"merge request !{m['iid']} is still open — not merged yet", "items": [m.get("title", "")], "url": m.get("url")})
    for s in sessions:
        warnings.append({"kind": "session", "text": f"a Claude session is {'working' if s.get('status') == 'busy' else 'open'} in this worktree", "items": [s.get("title") or s.get("name") or ""]})
    command = profile.get("worktrees", {}).get("remove")
    with _jobs_lock:
        job = dict(_jobs.get(name) or {})
    return {
        "name": name,
        "path": str(wt).replace(str(Path.home()), "~", 1),
        "branch": branch if branch != "HEAD" else "",
        "slug": slug,
        "containers": containers,
        "databases": databases,
        "warnings": warnings,
        "command": command.format(name=name, slug=slug) if command else "",
        "job": job,
    }


DONE_SHOWN = 3


def jobs():
    with _jobs_lock:
        for name in [k for k, v in _jobs.items() if v.get("status") == "done" and time.time() - v.get("ended", 0) > DONE_SHOWN]:
            _jobs.pop(name, None)
        return {k: {**{kk: vv for kk, vv in v.items() if kk != "log"}, "tail": v.get("log", "")[-1500:]} for k, v in _jobs.items()}


def remove(name, force=False):
    wt = _find(name)
    with _jobs_lock:
        if (_jobs.get(name) or {}).get("status") == "running":
            raise ValueError(f"{name} is already being cleaned up")
        _jobs[name] = {"status": "running", "started": time.time(), "force": bool(force), "log": ""}
    threading.Thread(target=_remove, args=(name, wt, bool(force)), daemon=True).start()


def _log(name, text):
    with _jobs_lock:
        _jobs[name]["log"] = (_jobs[name].get("log", "") + text.rstrip() + "\n")[-20000:]


def _sh(name, cmd, cwd=None, timeout=900):
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join([str(Path.home() / ".local" / "bin"), "/opt/homebrew/bin", "/usr/local/bin", env.get("PATH", "")])
    _log(name, f"$ {cmd if isinstance(cmd, str) else shlex.join(cmd)}")
    try:
        res = subprocess.run(cmd, cwd=cwd, shell=isinstance(cmd, str), capture_output=True, text=True, timeout=timeout, env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        _log(name, f"failed: {exc}")
        return False
    _log(name, (res.stdout or "") + (res.stderr or ""))
    return res.returncode == 0


def _remove(name, wt, force):
    ok = True
    try:
        slug, containers, databases = resources(name)
        command = profile.get("worktrees", {}).get("remove")
        if command:
            flag = profile.get("worktrees", {}).get("force_flag") or "--force"
            cmd = command.format(name=shlex.quote(name), slug=shlex.quote(slug)) + (f" {flag}" if force else "")
            ok = _sh(name, cmd, cwd=str(project_root() or wt.parent))
        else:
            ok = _builtin(name, wt, force, containers, databases)
    except Exception as exc:  # noqa: BLE001
        log.exception("worktree cleanup failed")
        _log(name, f"failed: {exc}")
        ok = False
    still_there = wt.exists()
    with _jobs_lock:
        _jobs[name].update(status="done" if ok and not still_there else "error", ended=time.time())
    _refresh()


def _builtin(name, wt, force, containers, databases):
    repo = Path(_git(wt, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()).parent
    branch = _git(wt, "rev-parse", "--abbrev-ref", "HEAD").strip()
    if not force and (_git(wt, "status", "--porcelain").strip() or _git(wt, "log", "--oneline", "HEAD", "--not", "--remotes").strip()):
        _log(name, "refused: the worktree holds unsaved work")
        return False
    for c in containers:
        _sh(name, ["docker", "rm", "-f", c], timeout=120)
    for db in databases:
        if not db_container():
            _log(name, f"skipped {db}: no database container is set")
            continue
        _sh(name, ["docker", "exec", db_container(), "dropdb", "--force", "--if-exists", "-U", db_user(), db], timeout=300)
    ok = _sh(name, ["git", "-C", str(repo), "worktree", "remove", *(["--force"] if force else []), str(wt)], timeout=120)
    if ok and branch and branch != "HEAD":
        _sh(name, ["git", "-C", str(repo), "branch", "-D" if force else "-d", branch], timeout=60)
    _sh(name, ["git", "-C", str(repo), "worktree", "prune"], timeout=60)
    return ok


def _refresh():
    import system

    for fn in (system.collect_worktrees, system.collect_docker, system.collect_pg_sizes):
        try:
            fn()
        except Exception:  # noqa: BLE001
            log.exception("refresh after worktree cleanup failed")


def forget(name):
    with _jobs_lock:
        if (_jobs.get(name) or {}).get("status") != "running":
            _jobs.pop(name, None)
