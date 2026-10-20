import collections
import json
import os
import re
import time
from pathlib import Path

from core import PROJECTS, SESSIONS, alive, epoch, lock, project_root, put, run, state
from runs import refresh_runs

HISTORY = 150
SEP = "\x1f"

RE_DB = re.compile(r"(?:\s-d\s*|--database[= ]|--db[= ]|dbname=|\s-D\s)([A-Za-z0-9_]+)")
_known_rx = {}


def known(kind):
    with lock:
        if kind == "containers":
            names = [c["name"] for c in state.get("containers") or []]
        elif kind == "dbs":
            names = list(state.get("pg_sizes") or {})
        else:
            names = [w["name"] for w in state.get("worktrees") or []]
    key = tuple(sorted(n for n in names if len(n) >= 3))
    if _known_rx.get(kind, (None,))[0] != key:
        rx = re.compile(r"(?<![\w.-])(" + "|".join(map(re.escape, sorted(key, key=len, reverse=True))) + r")(?![\w-])") if key else None
        _known_rx[kind] = (key, rx)
    return _known_rx[kind][1]


RE_INVOKE = re.compile(r"\binvoke\s+([a-z][a-z0-9-]*)")
RE_NOTIF = re.compile(r"<task-notification>(.*?)</task-notification>", re.S)


def tag(text, name):
    m = re.search(rf"<{name}>(.*?)</{name}>", text, re.S)
    return m.group(1).strip() if m else ""


def describe(name, args):
    if name == "Bash":
        return args.get("description") or args.get("command", "")[:120]
    if name in ("Read", "Edit", "Write"):
        return Path(args.get("file_path", "")).name
    if name == "Skill":
        return args.get("skill", "")
    if name == "Agent":
        return args.get("description", "")
    if name in ("Grep", "Glob"):
        return args.get("pattern", "")
    if name.startswith("mcp__"):
        return name.split("__", 2)[-1]
    return ""


class Transcript:
    def __init__(self, path):
        self.path = path
        self.offset = 0
        self.title = ""
        self.last_prompt = ""
        self.last_prompt_ts = 0
        self.model = ""
        self.cwd = ""
        self.branch = ""
        self.last_ts = 0
        self.last_tool = ""
        self.tools = collections.Counter()
        self.skills = {}
        self.mcp = {}
        self.entities = {"containers": {}, "dbs": {}, "worktrees": {}, "invoke": {}}
        self.agents = {}
        self.agent_by_tool = {}
        self.jobs = {}
        self.job_by_tool = {}
        self.pending = {}
        self.tool_meta = {}
        self.prompts = []
        self.bash = collections.deque(maxlen=12)
        self.activity = collections.deque(maxlen=12)
        self.usage = collections.Counter()
        self.msg_id = None
        self.msg_usage = {}

    def tokens(self):
        total = collections.Counter(self.usage)
        total.update(self.msg_usage)
        return dict(total)

    def update(self):
        try:
            size = self.path.stat().st_size
        except OSError:
            return self
        if size < self.offset:
            self.__init__(self.path)
        if size == self.offset:
            return self
        with open(self.path, "rb") as fh:
            fh.seek(self.offset)
            chunk = fh.read()
        end = chunk.rfind(b"\n")
        if end < 0:
            return self
        self.offset += end + 1
        for line in chunk[: end + 1].splitlines():
            try:
                self.record(json.loads(line))
            except (ValueError, TypeError, AttributeError, KeyError):
                continue
        return self

    def seen(self, bucket, key, ts):
        entry = bucket.setdefault(key, [0, 0])
        entry[0] += 1
        entry[1] = max(entry[1], ts)

    def record(self, rec):
        kind = rec.get("type")
        if kind in ("queue-operation", "attachment"):
            self.queued(rec)
            return
        if kind == "ai-title":
            self.title = rec.get("aiTitle") or self.title
            return
        if kind == "last-prompt" and not self.last_prompt:
            self.last_prompt = str(rec.get("lastPrompt") or "")[:400]
            return
        self.cwd = rec.get("cwd") or self.cwd
        self.branch = rec.get("gitBranch") or self.branch
        ts = epoch(rec.get("timestamp", ""))
        if kind == "user":
            self.user(rec, ts)
        elif kind == "assistant":
            self.assistant(rec, ts)

    def user(self, rec, ts):
        content = rec.get("message", {}).get("content")
        result = rec.get("toolUseResult")
        blocks = content if isinstance(content, list) else []
        for b in blocks:
            if isinstance(b, dict) and b.get("type") == "tool_result":
                tid = b.get("tool_use_id")
                self.pending.pop(tid, None)
                if isinstance(result, dict):
                    self.result(tid, result, ts, b.get("is_error"))
        if isinstance(content, str):
            text = content
        else:
            text = " ".join(b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text")
        for body in RE_NOTIF.findall(text or ""):
            self.notification(body, ts)
        if result is not None:
            self.touch(ts)
            return
        origin = rec.get("turnOrigin")
        clean = (text or "").strip()
        images = sum(1 for b in blocks if isinstance(b, dict) and b.get("type") == "image")
        human = origin == "human" if origin is not None else not rec.get("isMeta") and clean and not clean.startswith("<")
        if human and (clean or images):
            m = re.search(r"<command-name>(.*?)</command-name>.*?<command-args>(.*?)</command-args>", clean, re.S)
            self.add_prompt(f"{m.group(1)} {m.group(2)}".strip() if m else clean, images, ts)

    def add_prompt(self, text, images, ts, queued=False):
        if text.startswith("[Request interrupted"):
            if self.prompts:
                self.prompts[-1]["interrupted"] = True
            return
        self.prompts.append({"ts": ts, "text": text[:2000], "images": images, "end": ts, "tools": 0, "agents": 0, "queued": queued})
        del self.prompts[:-300]
        self.last_prompt = text[:400]
        self.last_prompt_ts = ts

    def touch(self, ts):
        if self.prompts and ts:
            self.prompts[-1]["end"] = max(self.prompts[-1]["end"], ts)

    def queued(self, rec):
        att = rec.get("attachment") if isinstance(rec.get("attachment"), dict) else {}
        origin = att.get("origin") if isinstance(att.get("origin"), dict) else {}
        if att.get("type") == "queued_command" and origin.get("kind") == "human":
            body = att.get("prompt")
            blocks = body if isinstance(body, list) else [{"type": "text", "text": body or ""}]
            text = " ".join(b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text").strip()
            images = sum(1 for b in blocks if isinstance(b, dict) and b.get("type") == "image")
            if text or images:
                self.add_prompt(text, images, epoch(att.get("timestamp") or rec.get("timestamp", "")), queued=True)
            return
        body = att.get("prompt") if att.get("type") == "queued_command" else rec.get("content")
        if isinstance(body, list):
            body = " ".join(b.get("text", "") for b in body if isinstance(b, dict))
        if not isinstance(body, str) or "<task-notification>" not in body:
            return
        ts = epoch(att.get("timestamp") or rec.get("timestamp", ""))
        for part in RE_NOTIF.findall(body):
            self.notification(part, ts, att.get("usage"))

    def result(self, tid, result, ts, is_error):
        if tid in self.agent_by_tool:
            agent = self.agents[self.agent_by_tool[tid]]
            if result.get("agentId") and result["agentId"] != agent["id"]:
                self.agents[result["agentId"]] = self.agents.pop(agent["id"])
                agent["id"] = result["agentId"]
                self.agent_by_tool[tid] = agent["id"]
            if result.get("status") != "async_launched":
                agent["status"] = "failed" if is_error else "completed"
                agent["ended"] = ts
        name, what, started, args = self.tool_meta.pop(tid, (None, "", ts, {}))
        if name == "TaskStop":
            target = self.agents.get(result.get("task_id", "")) or self.jobs.get(result.get("task_id", ""))
            if target and target["status"] == "running":
                target["status"], target["ended"] = "stopped", ts
            return
        bg = result.get("backgroundTaskId") or (name == "Monitor" and result.get("taskId"))
        if bg and tid not in self.job_by_tool:
            how = (
                "monitor"
                if name == "Monitor"
                else "you moved it"
                if result.get("backgroundedByUser")
                else (f"timed out after {int(result['timedOutAfterMs'] / 60000)}m" if result.get("timedOutAfterMs") else "background")
            )
            self.jobs[bg] = {
                "id": bg,
                "description": what or str(args.get("command", ""))[:80],
                "started": started,
                "status": "running",
                "ended": 0,
                "summary": "",
                "how": how,
            }
            self.job_by_tool[tid] = bg
            return
        if tid in self.job_by_tool:
            if result.get("backgroundTaskId"):
                job = self.jobs.pop(self.job_by_tool[tid])
                job["id"] = result["backgroundTaskId"]
                self.jobs[job["id"]] = job
                self.job_by_tool[tid] = job["id"]
            else:
                job = self.jobs[self.job_by_tool[tid]]
                job["status"], job["ended"] = "completed", ts

    def notification(self, body, ts, usage=None):
        tid, status, summary = tag(body, "task-id"), tag(body, "status"), tag(body, "summary")
        target = self.agents.get(tid) or self.jobs.get(tid)
        if not target:
            target = self.agents.get(self.agent_by_tool.get(tag(body, "tool-use-id"), ""))
        if target and ts >= target.get("ended", 0):
            target["status"] = status or "completed"
            target["ended"] = ts
            target["summary"] = summary[:200]
            if isinstance(usage, dict):
                target["usage"] = usage

    def assistant(self, rec, ts):
        msg = rec.get("message", {})
        self.touch(ts)
        self.model = msg.get("model") or self.model
        self.last_ts = ts or self.last_ts
        usage = msg.get("usage") or {}
        if msg.get("id") != self.msg_id:
            self.usage.update(self.msg_usage)
            self.msg_id = msg.get("id")
        self.msg_usage = {k: usage.get(k) or 0 for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")}
        for block in msg.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                self.tool(block.get("id"), block.get("name", ""), block.get("input") or {}, ts)

    def tool(self, tid, name, args, ts):
        self.tools[name] += 1
        self.last_tool = name
        if self.prompts:
            self.prompts[-1]["tools"] += 1
            self.prompts[-1]["agents"] += name == "Agent"
        what = describe(name, args)
        self.pending[tid] = {"tool": name, "what": what[:160], "ts": ts}
        if name in ("Bash", "Monitor", "TaskStop"):
            self.tool_meta[tid] = (name, args.get("description") or what, ts, args)
        self.activity.append({"tool": name, "what": what[:160], "ts": ts})
        if name == "Skill":
            self.seen(self.skills, args.get("skill", "?"), ts)
        elif name == "Agent":
            self.agents[tid] = {
                "id": tid,
                "description": args.get("description", ""),
                "type": args.get("subagent_type") or "general-purpose",
                "model": args.get("model", ""),
                "background": bool(args.get("run_in_background", True)),
                "started": ts,
                "status": "running",
                "ended": 0,
                "summary": "",
            }
            self.agent_by_tool[tid] = tid
        elif name.startswith("mcp__"):
            self.seen(self.mcp, name.split("__")[1].replace("claude_ai_", ""), ts)
        if name == "Bash":
            cmd = args.get("command", "")
            self.bash.append({"ts": ts, "cmd": cmd[:500], "desc": args.get("description", "")})
            if args.get("run_in_background"):
                self.jobs[tid] = {
                    "id": tid,
                    "description": args.get("description") or cmd[:80],
                    "started": ts,
                    "status": "running",
                    "ended": 0,
                    "summary": "",
                    "how": "background",
                }
                self.job_by_tool[tid] = tid
            self.scan(cmd, ts)
        elif name != "Agent":
            self.scan(json.dumps(args)[:3000], ts)

    def scan(self, text, ts):
        e = self.entities
        for kind, bucket in (("containers", "containers"), ("worktrees", "worktrees"), ("dbs", "dbs")):
            rx = known(kind)
            for n in rx.findall(text) if rx else []:
                self.seen(e[bucket], n, ts)
        for n in RE_DB.findall(text):
            self.seen(e["dbs"], n, ts)
        for n in RE_INVOKE.findall(text):
            self.seen(e["invoke"], n, ts)


transcripts = {}


def transcript(path):
    if path not in transcripts:
        transcripts[path] = Transcript(path)
    return transcripts[path].update()


def processes():
    procs = {}
    for line in run(["ps", "-A", "-o", "pid=,ppid=,pcpu=,rss=,etime=,args="]).splitlines():
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue
        pid, ppid, cpu, rss, etime, args = parts
        procs[int(pid)] = {
            "pid": int(pid),
            "ppid": int(ppid),
            "cpu": float(cpu),
            "rss": int(rss) * 1024,
            "etime": etime,
            "args": args,
            "name": os.path.basename(args.split()[0]),
        }
    return procs


def descendants(procs, root):
    kids = collections.defaultdict(list)
    for p in procs.values():
        kids[p["ppid"]].append(p["pid"])
    out, stack = [], list(kids.get(root, []))
    while stack:
        pid = stack.pop()
        out.append(procs[pid])
        stack.extend(kids.get(pid, []))
    return out


def find_transcript(cwd, sid):
    path = PROJECTS / re.sub(r"[^A-Za-z0-9]", "-", cwd) / f"{sid}.jsonl"
    return path if path.exists() else next(PROJECTS.glob(f"*/{sid}.jsonl"), None)


def merge_seen(target, source):
    for k, (n, ts) in source.items():
        entry = target.setdefault(k, [0, 0])
        entry[0] += n
        entry[1] = max(entry[1], ts)


def as_list(bucket, limit=40):
    ordered = sorted(bucket.items(), key=lambda kv: -kv[1][1])[:limit]
    return [{"name": k, "count": n, "last": ts} for k, (n, ts) in ordered]


def workflow_journal(path):
    """Agent states of one Workflow run, from its journal: running until a result or an error arrives."""
    out = {}
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        aid, kind = ev.get("agentId"), ev.get("type")
        if not aid:
            continue
        if kind == "started":
            out.setdefault(aid, {"status": "running", "summary": ""})
        elif kind == "result":
            text = ev.get("result") if isinstance(ev.get("result"), str) else json.dumps(ev.get("result"), ensure_ascii=False)
            out[aid] = {"status": "completed", "summary": (text or "").strip().split("\n")[0][:300]}
        else:
            out[aid] = {"status": "failed", "summary": str(ev.get("error") or ev.get("message") or kind)[:300]}
    return out


def session_agents(main, path):
    now = time.time()
    agents = {a["id"]: dict(a) for a in main.agents.values()}
    subs = []
    root = path.with_suffix("") / "subagents"
    flows = {wf.name: workflow_journal(wf / "journal.jsonl") for wf in root.glob("workflows/*") if wf.is_dir()}
    for meta_path in [*root.glob("*.meta.json"), *root.glob("workflows/*/*.meta.json")]:
        log = meta_path.with_name(meta_path.name.replace(".meta.json", ".jsonl"))
        try:
            meta = json.loads(meta_path.read_text())
            st = log.stat()
        except (OSError, ValueError):
            continue
        aid = log.stem.replace("agent-", "")
        t = transcript(log)
        subs.append(t)
        key = aid if aid in agents else main.agent_by_tool.get(meta.get("toolUseId"), aid)
        flow = flows.get(meta_path.parent.name, {}).get(aid) if meta_path.parent.parent.name == "workflows" else None
        a = agents.pop(key, None) or {
            "description": meta.get("description", ""),
            "type": f"workflow · {meta['workflowPhase']}" if flow is not None and meta.get("workflowPhase") else meta.get("agentType", ""),
            "model": meta.get("model", ""),
            "started": getattr(st, "st_birthtime", st.st_mtime),
            "status": "unknown",
            "ended": 0,
            "summary": "",
            "background": True,
        }
        if flow:
            a["status"] = flow["status"]
            a["summary"] = a.get("summary") or flow["summary"]
            if flow["status"] != "running":
                a["ended"] = a.get("ended") or st.st_mtime
        a["id"] = aid
        a["model"] = a.get("model") or meta.get("model", "")
        a["depth"] = meta.get("spawnDepth", 1)
        a["last_write"] = st.st_mtime
        a["tools"] = sum(t.tools.values())
        current = list(t.pending.values())[-1:] or list(t.activity)[-1:]
        a["doing"] = current[0] if current else None
        if a["status"] != "running" and a["ended"] and st.st_mtime > a["ended"] + 5:
            a["status"] = "running"
        if a["status"] in ("running", "unknown") and t.last_tool == "SubagentHandback" and not t.pending:
            a["status"], a["ended"] = "completed", a.get("ended") or st.st_mtime
        if a["status"] in ("running", "unknown") and now - st.st_mtime > 900:
            a["status"] = "quiet"
        agents[aid] = a
    for a in agents.values():
        a.setdefault("tools", 0)
        a.setdefault("doing", None)
        a.setdefault("last_write", a.get("started", 0))
    order = {"running": 0, "quiet": 1, "unknown": 2}
    out = sorted(
        agents.values(),
        key=lambda a: (order.get(a["status"], 3), -(a.get("ended") or a.get("started") or 0)),
    )
    return out, subs


def collect_sessions():
    procs = processes()
    sessions = []
    metas = []
    for f in SESSIONS.glob("*.json"):
        try:
            metas.append(json.loads(f.read_text()))
        except (OSError, ValueError):
            continue
    runs = refresh_runs()
    known = {m.get("sessionId") for m in metas}
    for r in runs:
        if r["status"] == "running" and r.get("session_id") and r["session_id"] not in known:
            metas.append(
                {
                    "pid": r["pid"],
                    "sessionId": r["session_id"],
                    "name": r["name"],
                    "nameSource": "user",
                    "status": "busy",
                    "cwd": str(project_root() or ""),
                    "startedAt": r["started"] * 1000,
                    "statusUpdatedAt": r["started"] * 1000,
                    "entrypoint": "background",
                    "runId": r["id"],
                }
            )
    put("runs", [{k: v for k, v in r.items() if k != "log"} for r in runs[:20]])
    for meta in metas:
        pid = meta.get("pid")
        if not pid or not alive(pid):
            continue
        path = find_transcript(meta.get("cwd", ""), meta.get("sessionId", ""))
        t = transcript(path) if path else Transcript(Path("/nonexistent"))
        agents, subs = session_agents(t, path) if path else ([], [])
        ents = {k: {} for k in t.entities}
        skills, mcp, tools = {}, {}, collections.Counter()
        for src in [t] + subs:
            for k in ents:
                merge_seen(ents[k], src.entities[k])
            merge_seen(skills, src.skills)
            merge_seen(mcp, src.mcp)
            tools.update(src.tools)
        tree = descendants(procs, pid)
        own = procs.get(pid, {})
        doing = list(t.pending.values())[-1:]
        children = [
            dict({k: p[k] for k in ("pid", "name", "cpu", "rss", "etime")}, args=p["args"][:300]) for p in sorted(tree, key=lambda p: -p["cpu"]) if p["name"] not in ("zsh", "bash", "sh", "caffeinate")
        ][:20]
        sessions.append(
            {
                "pid": pid,
                "id": meta.get("sessionId"),
                "name": meta.get("name") or meta.get("sessionId", "")[:8],
                "name_source": meta.get("nameSource", ""),
                "run_id": meta.get("runId"),
                "status": meta.get("status", "?"),
                "entrypoint": meta.get("entrypoint"),
                "version": meta.get("version"),
                "started": (meta.get("startedAt") or 0) / 1000,
                "status_since": (meta.get("statusUpdatedAt") or 0) / 1000,
                "cwd": t.cwd or meta.get("cwd"),
                "branch": t.branch,
                "title": t.title,
                "last_prompt": t.last_prompt,
                "last_prompt_ts": t.last_prompt_ts,
                "prompts": t.prompts[::-1][:200],
                "last_ts": t.last_ts,
                "doing": doing[0] if doing else None,
                "activity": list(t.activity)[::-1],
                "model": t.model,
                "tokens": t.tokens(),
                "cpu": round(own.get("cpu", 0) + sum(p["cpu"] for p in tree), 1),
                "rss": own.get("rss", 0) + sum(p["rss"] for p in tree),
                "children": children,
                "bash": list(t.bash)[::-1],
                "agents": agents[:60],
                "jobs": sorted(t.jobs.values(), key=lambda j: (j["status"] != "running", -j["started"]))[:20],
                "skills": as_list(skills),
                "mcp": as_list(mcp),
                "tools": tools.most_common(20),
                **{k: as_list(v) for k, v in ents.items()},
            }
        )
    sessions.sort(key=lambda s: (s["status"] != "busy", -s["started"]))
    trim = lambda ps: [{k: p[k] for k in ("pid", "name", "cpu", "rss", "args")} for p in ps]  # noqa: E731
    put("sessions", sessions)
    put(
        "procs",
        {
            "cpu": trim(sorted(procs.values(), key=lambda p: -p["cpu"])[:15]),
            "mem": trim(sorted(procs.values(), key=lambda p: -p["rss"])[:15]),
            "count": len(procs),
        },
    )
