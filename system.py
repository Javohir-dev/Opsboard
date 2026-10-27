import json
import os
import re
import time
from pathlib import Path

import claudeusage
import config as cfg
import machine
import notify
import stackprofile as profile
from core import db_container, db_user, epoch, lock, put, run, size_bytes, state, worktree_paths
from sessions import HISTORY, SEP


def collect_mac():
    mac, net = machine.sample()
    now = time.time()
    with lock:
        prev = state.get("_net")
        state["_net"] = (now, net)
        if prev:
            dt = now - prev[0]
            mac["net_in"] = max(0, (net["in"] - prev[1]["in"]) / dt)
            mac["net_out"] = max(0, (net["out"] - prev[1]["out"]) / dt)
        mac.update(state.get("mac_static", {}))
        state["mac"] = mac
        hist = state["history"]
        for key, value in (
            ("cpu", mac.get("cpu", 0)),
            ("mem", 100 - mac.get("mem_free_pct", 0)),
            ("gpu", mac.get("gpu") or 0),
            ("net_in", mac.get("net_in", 0)),
            ("net_out", mac.get("net_out", 0)),
        ):
            hist[key].append(round(value, 2))
            del hist[key][:-HISTORY]


def collect_mac_slow():
    info = machine.static()
    put("mac_static", info)
    notify.battery(info)


def collect_docker():
    ids = run(["docker", "ps", "-aq"]).split()
    try:
        info = json.loads(run(["docker", "inspect"] + ids) or "[]") if ids else []
    except ValueError:
        info = []
    containers = []
    for c in info:
        env = dict(e.split("=", 1) for e in c["Config"].get("Env") or [] if "=" in e)
        ports = {}
        for cport, binds in (c["NetworkSettings"].get("Ports") or {}).items():
            for b in binds or []:
                if b.get("HostPort"):
                    ports[int(b["HostPort"])] = cport.split("/")[0]
        networks = (c["NetworkSettings"].get("Networks") or {}).values()
        containers.append(
            {
                "name": c["Name"].lstrip("/"),
                "image": c["Config"].get("Image", ""),
                "state": c["State"].get("Status"),
                "health": (c["State"].get("Health") or {}).get("Status"),
                "started": epoch(c["State"].get("StartedAt", "")),
                "finished": epoch(c["State"].get("FinishedAt", "")),
                "ports": [{"host": h, "container": p} for h, p in sorted(ports.items())],
                "ips": [n.get("IPAddress") for n in networks if n.get("IPAddress")],
                "db_name": env.get("DB_NAME", ""),
                "service": (c["Config"].get("Labels") or {}).get("com.docker.compose.service", ""),
                "project": (c["Config"].get("Labels") or {}).get("com.docker.compose.project", ""),
            }
        )
    put("containers", containers)


def collect_docker_stats():
    stats = {}
    for line in run(["docker", "stats", "--no-stream", "--format", "{{json .}}"], timeout=30).splitlines():
        try:
            s = json.loads(line)
        except ValueError:
            continue
        used, _, limit = s.get("MemUsage", "").partition(" / ")
        stats[s["Name"]] = {
            "cpu": float(s.get("CPUPerc", "0").rstrip("%") or 0),
            "mem": size_bytes(used.replace("i", "")),
            "mem_limit": size_bytes(limit.replace("i", "")),
        }
    put("docker_stats", stats)


def collect_docker_df():
    rows = []
    for line in run(["docker", "system", "df", "--format", "{{json .}}"], timeout=60).splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    info = run(["docker", "info", "--format", "{{.NCPU}}|{{.MemTotal}}|{{.ServerVersion}}"]).strip().split("|")
    put(
        "docker_df",
        {
            "rows": rows,
            "ncpu": info[0] if info else "",
            "mem": int(info[1]) if len(info) > 1 and info[1].isdigit() else 0,
            "version": info[2] if len(info) > 2 else "",
        },
    )


def psql(sql):
    if not db_container():
        return []
    cmd = ["docker", "exec", db_container(), "psql", "-U", db_user(), "-d", "postgres", "-AtX", "-F", SEP, "-c", sql]
    return [line.split(SEP) for line in run(cmd).splitlines() if line]


def collect_pg():
    conns = psql(
        "select coalesce(datname,''), coalesce(state,''), coalesce(host(client_addr),'local'), count(*), "
        "coalesce(max(extract(epoch from now()-state_change))::int,0) "
        "from pg_stat_activity where backend_type='client backend' and pid<>pg_backend_pid() group by 1,2,3"
    )
    active = psql(
        "select pid, datname, coalesce(host(client_addr),'local'), state, "
        "coalesce(wait_event_type||': '||wait_event,''), extract(epoch from now()-query_start)::int, "
        "left(regexp_replace(query,'\\s+',' ','g'),600) from pg_stat_activity "
        "where backend_type='client backend' and state<>'idle' and pid<>pg_backend_pid() "
        "order by query_start limit 40"
    )
    meta = psql("select current_setting('max_connections'), (select count(*) from pg_locks where not granted), version()")
    put(
        "pg",
        {
            "ok": bool(meta),
            "max_connections": int(meta[0][0]) if meta else 0,
            "waiting_locks": int(meta[0][1]) if meta else 0,
            "version": meta[0][2].split(" (")[0] if meta else "",
            "conns": [{"db": r[0], "state": r[1], "addr": r[2], "count": int(r[3]), "for": int(r[4])} for r in conns if len(r) == 5],
            "active": [
                {
                    "pid": int(r[0]),
                    "db": r[1],
                    "addr": r[2],
                    "state": r[3],
                    "wait": r[4],
                    "secs": int(r[5] or 0),
                    "query": r[6],
                }
                for r in active
                if len(r) == 7
            ],
        },
    )


def collect_pg_sizes():
    rows = psql("select datname, pg_database_size(datname) from pg_database where not datistemplate")
    put("pg_sizes", {r[0]: int(r[1]) for r in rows if len(r) == 2})


def collect_worktrees():
    out = []
    for wt in worktree_paths():
        branch = run(["git", "-C", str(wt), "rev-parse", "--abbrev-ref", "HEAD"]).strip()
        last = run(["git", "-C", str(wt), "log", "-1", "--format=%ct|%s"]).strip().split("|", 1)
        out.append(
            {
                "name": wt.name,
                "path": str(wt),
                "slug": profile.worktree_slug(wt.name),
                "branch": branch,
                "dirty": len(run(["git", "-C", str(wt), "status", "--porcelain"], timeout=20).splitlines()),
                "last_commit_ts": int(last[0]) if last[0].isdigit() else 0,
                "last_commit": last[1][:140] if len(last) > 1 else "",
                "mtime": wt.stat().st_mtime,
            }
        )
    put("worktrees", out)


def _version_tuple(text):
    m = re.match(r"v?(\d+)\.(\d+)\.(\d+)$", text.strip())
    return tuple(int(x) for x in m.groups()) if m else None


def collect_version():
    here = Path(__file__).parent
    current = (here / "VERSION").read_text().strip() if (here / "VERSION").exists() else "0.0.0"
    out = {"current": current, "latest": "", "checked": time.time()}
    if (here / ".git").exists():
        listing = run(["git", "-C", str(here), "ls-remote", "--tags", "--refs", "origin", "v*"], timeout=20)
        tags = [t for t in (_version_tuple(line.rsplit("/", 1)[-1]) for line in listing.splitlines()) if t]
        if tags:
            latest = max(tags)
            out["latest"] = ".".join(map(str, latest))
            out["update"] = latest > (_version_tuple(current) or (0, 0, 0))
    put("version", out)


CLAUDE_STATE = Path(os.environ.get("OPS_CLAUDE_JSON", Path.home() / ".claude.json"))
USAGE_LABELS = {"session": "Session (5hr)", "weekly_all": "Weekly (7 day)"}


def claude_usage(live=True):
    """Plan limits from Claude Code's cache, or asked from Anthropic when live; None without a Claude Code sign-in file."""
    try:
        raw = json.loads(CLAUDE_STATE.read_text())
    except (OSError, ValueError):
        return None
    cached = raw.get("cachedUsageUtilization") or {}
    acct = raw.get("oauthAccount") or {}
    plan = str(acct.get("organizationType") or "").replace("_", " ").title()
    utilization, fetched, source, live_error = cached.get("utilization") or {}, (cached.get("fetchedAtMs") or 0) / 1000, "cache", ""
    if live:
        data, live_error = claudeusage.fetch()
        if data:
            utilization, fetched, source = data, claudeusage.last_fetched(), "live"
    limits = []
    for item in utilization.get("limits") or []:
        model = (((item.get("scope") or {}).get("model") or {}).get("display_name")) or ""
        label = USAGE_LABELS.get(item.get("kind")) or (f"Weekly {model}" if model else str(item.get("kind", "")).replace("_", " ").capitalize())
        limits.append(
            {"label": label, "percent": item.get("percent") or 0, "severity": item.get("severity") or "normal", "resets_at": epoch(item.get("resets_at") or ""), "active": bool(item.get("is_active"))}
        )
    account = {"email": acct.get("emailAddress") or "", "org": acct.get("organizationName") or "", "plan": plan}
    return {"limits": limits, "fetched": fetched, "account": account, "source": source, "live_error": live_error}


def collect_claude_usage():
    if not cfg.get("claude.live_usage"):
        claudeusage.reset()
        put("claude_usage", {})
        return
    put("claude_usage", claude_usage(live=True) or {})
