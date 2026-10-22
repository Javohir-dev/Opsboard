import json
import re
import time
from urllib import error, parse, request

import config as cfg
import notify
import stackprofile as profile
from core import epoch, key_regex, lock, put, state


def web_url():
    return (cfg.get("github.url") or "https://github.com").rstrip("/")


def api_base():
    return "https://api.github.com" if web_url() == "https://github.com" else f"{web_url()}/api/v3"


def graphql_url():
    return "https://api.github.com/graphql" if web_url() == "https://github.com" else f"{web_url()}/api/graphql"


def repo():
    value = cfg.get("github.repo") or ""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value) or not cfg.secret("github.token"):
        raise ValueError("GitHub is not configured — Opsboard → Settings → Code host")
    return value


def _headers(token=None):
    return {
        "Authorization": f"Bearer {token or cfg.secret('github.token')}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "opsboard",
    }


def call(method, path, data=None, params=None, token=None, base=None):
    url = f"{base or api_base()}/{path}" + ("?" + parse.urlencode(params) if params else "")
    body = json.dumps(data).encode() if data is not None else None
    req = request.Request(url, data=body, method=method, headers=_headers(token))
    if body is not None:
        req.add_header("Content-Type", "application/json")
    with request.urlopen(req, timeout=20) as resp:
        raw = resp.read().decode()
        return json.loads(raw) if raw else {}


def get(path, params=None, token=None, base=None):
    return call("GET", path, params=params, token=token, base=base)


def graphql(query, variables):
    req = request.Request(graphql_url(), data=json.dumps({"query": query, "variables": variables}).encode(), method="POST", headers=_headers())
    req.add_header("Content-Type", "application/json")
    with request.urlopen(req, timeout=20) as resp:
        out = json.loads(resp.read().decode())
    if out.get("errors"):
        raise ValueError("GitHub: " + "; ".join(e.get("message", "") for e in out["errors"])[:300])
    return out["data"]


def login():
    return get("user")["login"]


def label_text(color):
    r, g, b = (int(color[i : i + 2], 16) for i in (0, 2, 4)) if re.fullmatch(r"[0-9a-fA-F]{6}", color or "") else (128, 128, 128)
    return "#1f2328" if (r * 299 + g * 587 + b * 114) / 1000 > 150 else "#ffffff"


THREADS_QUERY = """query($owner:String!,$name:String!,$number:Int!,$after:String){repository(owner:$owner,name:$name){pullRequest(number:$number){
reviewThreads(first:100,after:$after){pageInfo{hasNextPage endCursor} nodes{id isResolved path line originalLine
comments(first:50){nodes{author{login} body url}}}}}}}"""


def _threads_raw(number):
    owner, name = repo().split("/")
    out, after = [], None
    while True:
        data = graphql(THREADS_QUERY, {"owner": owner, "name": name, "number": int(number), "after": after})
        page = data["repository"]["pullRequest"]["reviewThreads"]
        out += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            return out
        after = page["pageInfo"]["endCursor"]


def _checks(sha):
    runs = get(f"repos/{repo()}/commits/{sha}/check-runs", {"per_page": 100}).get("check_runs", [])
    if not runs:
        return ""
    if any(r.get("conclusion") in ("failure", "timed_out", "action_required", "startup_failure") for r in runs):
        return "failed"
    if any(r.get("status") != "completed" for r in runs):
        return "running"
    if all(r.get("conclusion") in ("skipped", "neutral") for r in runs):
        return "skipped"
    return "success"


def _approvals(number):
    latest = {}
    for rv in get(f"repos/{repo()}/pulls/{number}/reviews", {"per_page": 100}):
        if rv.get("state") in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED") and rv.get("user"):
            latest[rv["user"]["login"]] = rv["state"]
    return [u for u, s in latest.items() if s == "APPROVED"]


def collect():
    if not (cfg.secret("github.token") and cfg.get("github.repo")):
        put("review", {"host": "github", "configured": False})
        return
    try:
        name = repo()
        me = login()
        if cfg.get("github.username") != me:
            cfg.set("github.username", me, "auto", "GitHub /user")
        items, page = [], 1
        while page <= 3:
            batch = get("search/issues", {"q": f"repo:{name} is:pr author:{me}", "sort": "updated", "order": "desc", "per_page": 100, "page": page}).get("items", [])
            items += batch
            if len(batch) < 100:
                break
            page += 1
        keys_rx = key_regex()
        title_rx = re.compile(profile.get("tasks.mr_title")) if profile.get("tasks.mr_title") else None
        labels, out = {}, []
        for it in items:
            for lb in it.get("labels") or []:
                labels[lb["name"]] = {"color": "#" + (lb.get("color") or "888888"), "text": label_text(lb.get("color"))}
            merged_at = (it.get("pull_request") or {}).get("merged_at")
            st = "opened" if it["state"] == "open" else ("merged" if merged_at else "closed")
            mod = title_rx.search(it["title"]) if title_rx else None
            rec = {
                "iid": it["number"],
                "title": it["title"],
                "url": it["html_url"],
                "state": st,
                "draft": bool(it.get("draft")),
                "conflicts": False,
                "merge_status": "",
                "source": "",
                "target": "",
                "created": epoch(it.get("created_at") or ""),
                "updated": epoch(it.get("updated_at") or ""),
                "merged": epoch(merged_at or ""),
                "closed": epoch(it.get("closed_at") or ""),
                "keys": sorted(set(keys_rx.findall(f"{it['title']} {(it.get('body') or '')[:400]}"))),
                "module": mod.group("module") if mod and "module" in title_rx.groupindex else "",
                "plan": int(mod.group("plan")) if mod and "plan" in title_rx.groupindex and mod.group("plan") else None,
                "threads": None,
                "threads_total": None,
                "pipeline": "",
                "approved": False,
                "approved_by": [],
                "labels": [lb["name"] for lb in it.get("labels") or []],
                "author": (it.get("user") or {}).get("login", ""),
                "reviewers": [],
            }
            if st == "opened":
                pr = get(f"repos/{name}/pulls/{it['number']}")
                rec.update(
                    draft=bool(pr.get("draft")),
                    conflicts=pr.get("mergeable_state") == "dirty",
                    merge_status=pr.get("mergeable_state") or "",
                    source=pr["head"]["ref"],
                    target=pr["base"]["ref"],
                    reviewers=[u["login"] for u in pr.get("requested_reviewers") or []],
                )
                try:
                    threads = _threads_raw(it["number"])
                    rec["_threads"] = [
                        {
                            "id": t["id"],
                            "author": ((t["comments"]["nodes"][0].get("author") or {}).get("login", "")),
                            "username": ((t["comments"]["nodes"][0].get("author") or {}).get("login", "")),
                            "body": t["comments"]["nodes"][0].get("body", ""),
                            "path": t.get("path") or "",
                            "line": t.get("line") or t.get("originalLine"),
                        }
                        for t in threads
                        if (t.get("comments") or {}).get("nodes")
                    ]
                    rec["threads_total"] = len(threads)
                    rec["threads"] = sum(1 for t in threads if not t["isResolved"])
                    rec["pipeline"] = _checks(pr["head"]["sha"])
                    approved_by = _approvals(it["number"])
                    rec.update(approved=bool(approved_by), approved_by=approved_by, reviewers=sorted(set(rec["reviewers"]) | set(approved_by)))
                except (error.URLError, ValueError, KeyError, OSError):
                    pass
            out.append(rec)
    except (error.URLError, ValueError, KeyError, OSError) as exc:
        with lock:
            prev = state.get("review") or {}
        put("review", dict(prev, host="github", configured=True, error=str(exc)[:300]))
        return
    notify.merged(out)
    notify.new_threads(out, me)
    put("review", {"host": "github", "configured": True, "mrs": out, "fetched": time.time(), "user": me, "labels": labels})


def whoami():
    return {"host": "github", "user": login(), "project": repo(), "server": web_url()}


def _own(number):
    pr = get(f"repos/{repo()}/pulls/{int(number)}")
    me = login()
    if (pr.get("user") or {}).get("login") != me:
        raise PermissionError(f"#{number} was opened by {(pr.get('user') or {}).get('login')}, not by {me} — only your own pull requests")
    return pr


def info(number):
    pr = _own(number)
    return {
        "number": pr["number"],
        "title": pr["title"],
        "url": pr["html_url"],
        "state": "opened" if pr["state"] == "open" else ("merged" if pr.get("merged_at") else "closed"),
        "draft": bool(pr.get("draft")),
        "source": pr["head"]["ref"],
        "target": pr["base"]["ref"],
        "sha": pr["head"]["sha"],
        "conflicts": pr.get("mergeable_state") == "dirty",
        "merge_status": pr.get("mergeable_state") or "",
        "behind": None,
        "description": pr.get("body") or "",
    }


def mine(conflicts_only=False):
    me = login()
    items = get("search/issues", {"q": f"repo:{repo()} is:pr is:open author:{me}", "per_page": 100}).get("items", [])
    out = []
    for it in items:
        pr = get(f"repos/{repo()}/pulls/{it['number']}")
        row = {
            "number": pr["number"],
            "title": pr["title"],
            "draft": bool(pr.get("draft")),
            "source": pr["head"]["ref"],
            "target": pr["base"]["ref"],
            "conflicts": pr.get("mergeable_state") == "dirty",
        }
        if not conflicts_only or row["conflicts"]:
            out.append(row)
    return out


def threads(number, include_resolved=False):
    _own(number)
    me = login()
    out = []
    for t in _threads_raw(number):
        comments = (t.get("comments") or {}).get("nodes") or []
        if not comments or (t["isResolved"] and not include_resolved):
            continue
        first = comments[0]
        author = (first.get("author") or {}).get("login", "")
        if author == me:
            continue
        out.append(
            {
                "id": t["id"],
                "author": author,
                "bot": author.endswith("[bot]"),
                "where": f"{t.get('path')}:{t.get('line') or t.get('originalLine')}" if t.get("path") else None,
                "url": first.get("url"),
                "body": first.get("body", ""),
                "replies": [{"author": (c.get("author") or {}).get("login", ""), "body": c.get("body", "")} for c in comments[1:]],
                "resolved": t["isResolved"],
            }
        )
    return out


def reply(number, thread, body, resolve=False):
    _own(number)
    graphql("mutation($id:ID!,$body:String!){addPullRequestReviewThreadReply(input:{pullRequestReviewThreadId:$id,body:$body}){comment{id}}}", {"id": thread, "body": body})
    if resolve:
        resolve_thread(number, thread)
    return {"replied": thread, "resolved": resolve}


def resolve_thread(number, thread):
    _own(number)
    graphql("mutation($id:ID!){resolveReviewThread(input:{threadId:$id}){thread{id isResolved}}}", {"id": thread})
    return {"resolved": thread}


def describe(number, body):
    old = _own(number).get("body") or ""
    call("PATCH", f"repos/{repo()}/pulls/{int(number)}", {"body": body})
    return old


def upload(path):
    raise ValueError("GitHub has no API for attaching files — put the log into the reply or a gist")


DETAIL_THREADS = """query($owner:String!,$name:String!,$number:Int!,$after:String){repository(owner:$owner,name:$name){pullRequest(number:$number){
reviewThreads(first:100,after:$after){pageInfo{hasNextPage endCursor} nodes{id isResolved resolvedBy{login} path line originalLine diffSide
comments(first:100){nodes{author{login} body url createdAt}}}}}}}"""


def detail(number):
    pr = get(f"repos/{repo()}/pulls/{int(number)}")
    files, page = [], 1
    while page <= 30:
        batch = get(f"repos/{repo()}/pulls/{int(number)}/files", {"per_page": 100, "page": page})
        files += batch
        if len(batch) < 100:
            break
        page += 1
    status = {"added": "added", "removed": "deleted", "renamed": "renamed"}
    owner, name = repo().split("/")
    threads, after = [], None
    while True:
        data = graphql(DETAIL_THREADS, {"owner": owner, "name": name, "number": int(number), "after": after})["repository"]["pullRequest"]["reviewThreads"]
        for t in data["nodes"]:
            comments = (t.get("comments") or {}).get("nodes") or []
            if not comments:
                continue
            left = t.get("diffSide") == "LEFT"
            line = t.get("line") or t.get("originalLine")
            threads.append(
                {
                    "id": t["id"],
                    "resolvable": True,
                    "resolved": t["isResolved"],
                    "resolved_at": 0,
                    "resolved_by": (t.get("resolvedBy") or {}).get("login", ""),
                    "path": t.get("path") or "",
                    "new_line": None if left else line,
                    "old_line": line if left else None,
                    "url": comments[0].get("url"),
                    "notes": [
                        {
                            "author": (c.get("author") or {}).get("login", ""),
                            "username": (c.get("author") or {}).get("login", ""),
                            "body": c.get("body", ""),
                            "created": epoch(c.get("createdAt") or ""),
                        }
                        for c in comments
                    ],
                }
            )
        if not data["pageInfo"]["hasNextPage"]:
            break
        after = data["pageInfo"]["endCursor"]
    for c in get(f"repos/{repo()}/issues/{int(number)}/comments", {"per_page": 100}):
        who = (c.get("user") or {}).get("login", "")
        threads.append(
            {
                "id": str(c["id"]),
                "resolvable": False,
                "resolved": False,
                "resolved_by": "",
                "path": "",
                "new_line": None,
                "old_line": None,
                "url": c.get("html_url"),
                "notes": [{"author": who, "username": who, "body": c.get("body") or "", "created": epoch(c.get("created_at") or "")}],
            }
        )
    commits = [
        {
            "sha": c["sha"],
            "short": c["sha"][:7],
            "title": (c["commit"].get("message") or "").split("\n")[0],
            "message": c["commit"].get("message") or "",
            "author": ((c["commit"].get("author") or {}).get("name")) or "",
            "at": epoch(((c["commit"].get("author") or {}).get("date")) or ""),
            "url": c.get("html_url") or "",
        }
        for c in get(f"repos/{repo()}/pulls/{int(number)}/commits", {"per_page": 100})
    ]
    runs = get(f"repos/{repo()}/actions/runs", {"head_sha": pr["head"]["sha"], "per_page": 50}).get("workflow_runs", [])
    conclusion = {"success": "success", "failure": "failed", "timed_out": "failed", "cancelled": "canceled", "skipped": "skipped", "action_required": "manual"}
    pipelines = [
        {
            "id": r["id"],
            "status": conclusion.get(r.get("conclusion") or "") or ("running" if r.get("status") == "in_progress" else "pending"),
            "ref": r.get("name") or r.get("head_branch") or "",
            "sha": (r.get("head_sha") or "")[:7],
            "source": r.get("event") or "",
            "at": epoch(r.get("created_at") or ""),
            "url": r.get("html_url") or "",
        }
        for r in runs
    ]
    person = lambda u: {"name": u.get("login", ""), "username": u.get("login", ""), "avatar": u.get("avatar_url") or ""}  # noqa: E731
    reviews = get(f"repos/{repo()}/pulls/{int(number)}/reviews", {"per_page": 100})
    verdict = {}
    for r in reviews:
        who = (r.get("user") or {}).get("login")
        if who and r.get("state") in ("APPROVED", "CHANGES_REQUESTED", "COMMENTED"):
            verdict[who] = {"APPROVED": "approved", "CHANGES_REQUESTED": "requested_changes", "COMMENTED": "reviewed"}[r["state"]]
    reviewers = {u["login"]: person(u) for u in pr.get("requested_reviewers") or []}
    reviewers.update({(r.get("user") or {}).get("login"): person(r["user"]) for r in reviews if r.get("user")})
    seen, participants = set(), []
    for u in [pr.get("user") or {}] + [r.get("user") or {} for r in reviews]:
        if u.get("login") and u["login"] not in seen:
            seen.add(u["login"])
            participants.append(person(u))
    sidebar = {
        "assignees": [person(u) for u in pr.get("assignees") or []],
        "reviewers": [dict(p, state=verdict.get(k, "")) for k, p in reviewers.items() if k],
        "milestone": (pr.get("milestone") or {}).get("title") or "",
        "estimate": "",
        "spent": "",
        "participants": participants,
    }
    return {
        "sidebar": sidebar,
        "author_username": (pr.get("user") or {}).get("login", ""),
        "created": epoch(pr.get("created_at") or ""),
        "commits": commits,
        "pipelines": pipelines,
        "notes": sum(len(t["notes"]) for t in threads),
        "number": pr["number"],
        "title": pr["title"],
        "url": pr["html_url"],
        "author": (pr.get("user") or {}).get("login", ""),
        "description": pr.get("body") or "",
        "files": [
            {"path": f["filename"], "old_path": f.get("previous_filename") or f["filename"], "status": status.get(f["status"], "modified"), "diff": f.get("patch") or "", "too_large": "patch" not in f}
            for f in files
        ],
        "threads": threads,
    }
