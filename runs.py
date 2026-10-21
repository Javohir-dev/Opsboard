import json
import os
import re
import signal
import subprocess
import time
import uuid
from pathlib import Path

import config as cfg
import notify
from core import RUNS_DIR, RUNS_FILE, alive, claude_bin, epoch, lock, popen, project_root, runs_lock, state

RE_RESULT = re.compile(r"^OPS_RESULT\s+(\{.*\})\s*$", re.M)


def fix_skill():
    name = cfg.get("claude.fix_skill") or ""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", name):
        raise ValueError("no fix skill chosen — Settings → Claude → Fix skill")
    return name


def fix_prompt(iid, opts):
    words = [f"/{fix_skill()} {int(iid)}"]
    if opts.get("push"):
        words.append("push")
    if opts.get("skiptests"):
        words.append("skip-tests")
    if not opts.get("threads"):
        words.append("conflict-only")
    return " ".join(words)


def launch_fix(body):
    iid = int(body.get("iid"))
    opts = {k: bool(body.get(k)) for k in ("threads", "conflict", "skiptests", "push")}
    if not (opts["threads"] or opts["conflict"]):
        raise ValueError("turn on review threads or merge conflict")
    with lock:
        mrs = {m["iid"]: m for m in (state.get("review") or {}).get("mrs", [])}
    if iid not in mrs or mrs[iid]["state"] != "opened":
        raise ValueError(f"!{iid} is not one of your open merge requests")
    if not cfg.get("claude.background_runs"):
        raise ValueError("background runs are turned off in Settings")
    root = project_root()
    if not root or not root.is_dir():
        raise ValueError("project folder is not set in Settings")
    prompt = fix_prompt(iid, opts)
    name = f"{fix_skill()} !{iid} " + " ".join(prompt.split(" ")[2:])
    mr = mrs[iid]
    env = dict(
        os.environ,
        OPS_REVIEW_HOST=cfg.get("review.host") or "gitlab",
        OPS_PROJECT=(cfg.get("github.repo") if cfg.get("review.host") == "github" else cfg.get("gitlab.project")) or "",
        OPS_NUMBER=str(iid),
        OPS_URL=mr.get("url", ""),
        OPS_SOURCE=mr.get("source", ""),
        OPS_TARGET=mr.get("target", ""),
        OPS_REPLY_LANGUAGE=cfg.get("claude.reply_language") or "thread",
        OPS_PROJECT_ROOT=str(root),
        OPS_PUSH="1" if opts["push"] else "0",
    )
    with runs_lock:
        if any(r["iid"] == iid and r["status"] == "running" for r in load_runs()):
            raise ValueError(f"a fix is already running for !{iid}")
        RUNS_DIR.mkdir(exist_ok=True)
        rid = uuid.uuid4().hex[:12]
        log = RUNS_DIR / f"{rid}.jsonl"
        mode = cfg.get("claude.permission_mode", "auto")
        cmd = [claude_bin(), "-p", prompt, "--permission-mode", mode, "-n", name, "--output-format", "stream-json", "--verbose"]
        with open(log, "wb") as out, open(RUNS_DIR / f"{rid}.err", "wb") as err:
            proc = subprocess.Popen(cmd, cwd=str(root), env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=err, start_new_session=True)
        popen[proc.pid] = proc
        runs = load_runs()
        runs.insert(0, {"id": rid, "iid": iid, "name": name, "prompt": prompt, "pid": proc.pid, "started": time.time(), "status": "running", "log": str(log)})
        save_runs(runs[:50])
    return prompt


def parse_outcome(text):
    found = RE_RESULT.findall(text or "")
    if not found:
        return None
    try:
        out = json.loads(found[-1])
    except ValueError:
        return None
    return out if isinstance(out, dict) else None


def load_runs():
    try:
        return json.loads(RUNS_FILE.read_text())
    except (OSError, ValueError):
        return []


def save_runs(runs):
    RUNS_FILE.write_text(json.dumps(runs))


def _same_process(r):
    """True while the run's own claude process is alive (guards against a reused pid)."""
    proc = popen.get(r["pid"])
    if proc:
        return proc.poll() is None
    if not alive(r["pid"]):
        return False
    try:
        cmd = subprocess.run(["ps", "-o", "command=", "-p", str(r["pid"])], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return True
    return r.get("prompt", "") in cmd


def refresh_runs():
    with runs_lock:
        runs = load_runs()
        changed = False
        finished = []
        for r in runs:
            recent = time.time() - r.get("started", 0) < 86400
            if r["status"] in ("done", "error") and recent and not r.get("exited") and _same_process(r):
                r.update(status="running", ended=0)
                changed = True
            if r["status"] != "running":
                continue
            try:
                lines = Path(r["log"]).read_text(errors="replace").splitlines()
            except OSError:
                lines = []
            last = None
            for line in lines:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if ev.get("session_id") and not r.get("session_id"):
                    r["session_id"], changed = ev["session_id"], True
                if ev.get("type") == "result":
                    last = ev
            if last is not None:
                text = str(last.get("result") or "")
                update = {"result": text[:4000], "cost": last.get("total_cost_usd"), "outcome": parse_outcome(text), "is_error": bool(last.get("is_error"))}
                if any(r.get(k) != v for k, v in update.items()):
                    r.update(update)
                    changed = True
            if not _same_process(r):
                if last is not None:
                    status = "error" if last.get("is_error") else "done"
                else:
                    err = Path(r["log"]).with_suffix(".err")
                    tail = err.read_text(errors="replace")[-600:].strip() if err.exists() else ""
                    r["result"] = tail or "process exited without a result"
                    status = "error"
                r.update(status="stopped" if r.get("stop_requested") else status, ended=time.time(), exited=True)
                popen.pop(r["pid"], None)
                changed = True
                if r["status"] != "stopped":
                    finished.append(r)
        if changed:
            save_runs(runs)
    if finished:
        with lock:
            titles = {m["iid"]: m.get("title", "") for m in (state.get("review") or {}).get("mrs", [])}
        for r in finished:
            notify.run_finished(r, titles.get(r.get("iid"), ""))
    return runs


def stop_run(rid):
    with runs_lock:
        runs = load_runs()
        r = next((x for x in runs if x["id"] == rid), None)
        if not r or r["status"] != "running":
            raise ValueError("run is not running")
        r["stop_requested"] = True
        save_runs(runs)
    try:
        os.killpg(r["pid"], signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass


PHASES = [
    ("merge", "Merge target"),
    ("threads", "Threads"),
    ("fix", "Fix"),
    ("checks", "Checks"),
    ("commit", "Commit"),
    ("push", "Push & reply"),
]
RE_STEP = re.compile(r"^OPS_STEP\s+(\{.*\})\s*$", re.M)
PHASE_RULES = [
    ("push", re.compile(r"\bgit push\b|/discussions/[^/\s]+/notes|resolved=true|opsboard review (reply|describe)|\bglab mr (note|update)|mr_threads\.py[\s\S]*\b(reply|resolve|describe)\b")),
    ("commit", re.compile(r"\bgit (-c \S+ )*commit\b")),
    ("fix", re.compile(r"\bsed -i\b|\bperl -0?pi\b|\.write_text\(|open\([^)]*,\s*['\"]w|\.write\(s\)|\bpatch -p\d|\bgit apply\b")),
    (
        "checks",
        re.compile(r"\binvoke (test|lint)|test-warm|test-changed|\bpytest\b|\bruff\b|\bmsgfmt\b|node --check|python3? -m (py_compile|unittest)|--test-enable|static_gate|\bnpm (test|run lint)"),
    ),
    ("merge", re.compile(r"\bgit (-c \S+ )*(fetch|merge|pull|rebase)\b|merge-tree")),
    ("threads", re.compile(r"/discussions|opsboard review (threads|info)|\bglab mr view|mr_threads\.py[\s\S]*\b(info|list)\b")),
]


def _phases_of(cmd):
    return [name for name, rx in PHASE_RULES if rx.search(cmd)]


RE_REPLIED = re.compile(r"/discussions/([0-9a-f]{8,})|\b(?:reply|resolve) \d+ ([0-9a-f]{8,})")


def run_timeline(rid):
    """Phases, a live feed and reply activity of one fix run, read from its stream-json log."""
    run = next((r for r in load_runs() if r["id"] == rid), None)
    if not run:
        raise ValueError("unknown run")
    try:
        lines = Path(run["log"]).read_text(errors="replace").splitlines()
    except OSError:
        lines = []
    events, pending, touched, steps = [], {}, {}, {}
    replied = set()

    def mark(phase, at):
        first, _ = touched.get(phase, (at, at))
        touched[phase] = (first, at)

    for line in lines:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        at = epoch(ev.get("timestamp") or "") or None
        kind = ev.get("type")
        if kind == "assistant" and not ev.get("parent_tool_use_id"):
            for b in ev["message"].get("content", []):
                if b.get("type") == "text" and b.get("text", "").strip():
                    for m in RE_STEP.finditer(b["text"]):
                        try:
                            step = json.loads(m.group(1))
                        except ValueError:
                            continue
                        if step.get("step") in dict(PHASES):
                            steps[step["step"]] = step
                            mark(step["step"], at)
                    text = RE_RESULT.sub("", RE_STEP.sub("", b["text"])).strip()
                    if text:
                        events.append({"kind": "say", "text": text[:1500], "at": at})
                elif b.get("type") == "tool_use":
                    name, inp = b.get("name", ""), b.get("input") or {}
                    item = {"kind": "tool", "tool": name, "at": at, "id": b.get("id"), "status": "running"}
                    if name == "Bash":
                        cmd = str(inp.get("command") or "")
                        item.update(text=inp.get("description") or cmd.splitlines()[0][:200] if cmd else "", cmd=cmd[:2000], bg=bool(inp.get("run_in_background")))
                        found = _phases_of(cmd)
                        for phase in found:
                            mark(phase, at)
                        if found:
                            item["phase"] = found[0]
                        if "push" in found:
                            replied.update(x for pair in RE_REPLIED.findall(cmd) for x in pair if x)
                    elif name in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
                        item.update(text=str(inp.get("file_path") or ""), phase="fix")
                        mark("fix", at)
                    elif name in ("Read", "Grep", "Glob"):
                        item.update(text=str(inp.get("file_path") or inp.get("pattern") or ""))
                    elif name in ("Agent", "Task"):
                        item.update(text=str(inp.get("description") or ""))
                    else:
                        item.update(text=name)
                    events.append(item)
                    pending[b.get("id")] = item
        elif kind == "user":
            for b in (ev.get("message") or {}).get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id") in pending:
                    item = pending.pop(b["tool_use_id"])
                    item["status"] = "failed" if b.get("is_error") else ("background" if item.get("bg") else "done")
        elif kind == "system" and ev.get("subtype") == "task_notification":
            events.append({"kind": "note", "text": str(ev.get("summary") or ev.get("status") or "background job finished")[:300], "at": at})
        elif kind == "result":
            events.append({"kind": "result", "text": "", "at": at, "error": bool(ev.get("is_error"))})
    finished = run["status"] != "running"
    order = [p for p, _ in PHASES]
    reached = max((order.index(p) for p in touched), default=-1)
    phases = []
    for i, (key, label) in enumerate(PHASES):
        first, last = touched.get(key, (None, None))
        if key in touched and (finished or i < reached):
            st = "done"
        elif key in touched:
            st = "running"
        elif i < reached:
            st = "skipped"
        else:
            st = "skipped" if finished else "pending"
        if finished and run["status"] in ("error", "stopped") and i == reached:
            st = "failed" if run["status"] == "error" else "stopped"
        explicit = steps.get(key) or {}
        if explicit.get("status") in ("done", "running", "skipped", "failed"):
            st = explicit["status"]
        phases.append({"key": key, "label": label, "status": st, "start": first, "end": last, "note": str(explicit.get("note") or "")[:200]})
    public = {k: v for k, v in run.items() if k not in ("log", "pid")}
    return {"run": public, "phases": phases, "events": events[-400:], "replied": sorted(replied)}
