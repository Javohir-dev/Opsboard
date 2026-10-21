import collections
import json
import re
import time
from urllib import error, parse

import config as cfg
import stackprofile as profile
from core import MODULE_CACHE, epoch, gitlab_project, gitlab_url, http_json, key_regex, lock, put, state


def gitlab_get(path, params=None, token=None, base=None):
    tok = token or cfg.secret("gitlab.token")
    url = f"{(base or gitlab_url()).rstrip('/')}/api/v4/{path}" + ("?" + parse.urlencode(params) if params else "")
    return http_json(url, {"PRIVATE-TOKEN": tok})


def collect():
    if not cfg.secret("gitlab.token"):
        put("review", {"host": "gitlab", "configured": False})
        return
    try:
        pid = parse.quote(gitlab_project(), safe="")
        user = gitlab_get("user")["username"]
        if cfg.get("gitlab.username") != user:
            cfg.set("gitlab.username", user, "auto", "GitLab /user")
        mrs, page = [], 1
        while True:
            batch = gitlab_get(
                f"projects/{pid}/merge_requests",
                {"author_username": user, "state": "all", "per_page": 100, "page": page, "order_by": "updated_at"},
            )
            mrs += batch
            if len(batch) < 100:
                break
            page += 1
        try:
            cache = json.loads(MODULE_CACHE.read_text())
        except (OSError, ValueError):
            cache = {}
        out = []
        keys_rx = key_regex()
        title_rx = re.compile(profile.get("tasks.mr_title")) if profile.get("tasks.mr_title") else None
        for m in mrs:
            text = f"{m['title']} {m['source_branch']} {(m.get('description') or '')[:400]}"
            mod = title_rx.search(m["title"]) if title_rx else None
            module = mod.group("module") if mod and "module" in title_rx.groupindex else cache.get(str(m["iid"]), "")
            if not module and str(m["iid"]) not in cache and profile.get("tasks.area_from_diff"):
                diffs = gitlab_get(f"projects/{pid}/merge_requests/{m['iid']}/diffs", {"per_page": 100})
                tops = collections.Counter(d["new_path"].split("/")[0] for d in diffs if "/" in d["new_path"])
                module = tops.most_common(1)[0][0] if tops else ""
                if m["state"] != "opened":
                    cache[str(m["iid"])] = module
            threads, threads_total, pipeline, approved, approved_by = None, None, "", False, []
            if m["state"] == "opened":
                disc = gitlab_get(f"projects/{pid}/merge_requests/{m['iid']}/discussions", {"per_page": 100})
                notes = [n for d in disc for n in d.get("notes", [])[:1] if n.get("resolvable")]
                threads = sum(1 for n in notes if not n.get("resolved"))
                threads_total = len(notes)
                try:
                    detail = gitlab_get(f"projects/{pid}/merge_requests/{m['iid']}")
                    pipeline = ((detail.get("head_pipeline") or detail.get("pipeline") or {}).get("status")) or ""
                    appr = gitlab_get(f"projects/{pid}/merge_requests/{m['iid']}/approvals")
                    approved = bool(appr.get("approved")) and bool(appr.get("approved_by"))
                    approved_by = [a["user"]["name"] for a in appr.get("approved_by") or [] if a.get("user")]
                except (error.URLError, ValueError, KeyError, OSError):
                    pass
            out.append(
                {
                    "iid": m["iid"],
                    "title": m["title"],
                    "url": m["web_url"],
                    "state": m["state"],
                    "draft": m.get("draft", False),
                    "conflicts": m.get("has_conflicts", False),
                    "merge_status": m.get("detailed_merge_status", ""),
                    "source": m["source_branch"],
                    "target": m["target_branch"],
                    "created": epoch(m.get("created_at", "")),
                    "updated": epoch(m.get("updated_at", "")),
                    "merged": epoch(m.get("merged_at") or ""),
                    "keys": sorted(set(keys_rx.findall(text))),
                    "module": module,
                    "plan": int(mod.group("plan")) if mod and "plan" in title_rx.groupindex and mod.group("plan") else None,
                    "threads": threads,
                    "threads_total": threads_total,
                    "pipeline": pipeline,
                    "approved": approved,
                    "approved_by": approved_by,
                    "labels": m.get("labels") or [],
                    "author": (m.get("author") or {}).get("name", ""),
                    "reviewers": [r.get("name", "") for r in m.get("reviewers") or []],
                    "closed": epoch(m.get("closed_at") or ""),
                }
            )
        MODULE_CACHE.write_text(json.dumps(cache))
    except (error.URLError, ValueError, KeyError, OSError) as exc:
        with lock:
            prev = state.get("review") or {}
        put("review", dict(prev, host="gitlab", configured=True, error=str(exc)[:300]))
        return
    put("review", {"host": "gitlab", "configured": True, "mrs": out, "fetched": time.time(), "user": user, "labels": project_labels(pid)})


_labels_cache = {"at": 0, "pid": None, "labels": {}}


def project_labels(pid):
    if _labels_cache["pid"] == pid and time.time() - _labels_cache["at"] < 3600:
        return _labels_cache["labels"]
    labels, page = {}, 1
    try:
        while page <= 10:
            batch = gitlab_get(f"projects/{pid}/labels", {"per_page": 100, "page": page, "include_ancestor_groups": "true"})
            for lb in batch:
                labels[lb["name"]] = {"color": lb.get("color", "#6699cc"), "text": lb.get("text_color", "#ffffff")}
            if len(batch) < 100:
                break
            page += 1
    except (error.URLError, ValueError, KeyError, OSError):
        return _labels_cache["labels"]
    _labels_cache.update(at=time.time(), pid=pid, labels=labels)
    return labels


def gitlab_call(method, path, data=None):
    url = f"{gitlab_url()}/api/v4/{path}"
    return http_json(url, {"PRIVATE-TOKEN": cfg.secret("gitlab.token")}, data if data is not None else {}, method=method)


def _pid():
    project = gitlab_project()
    if not (gitlab_url() and project and cfg.secret("gitlab.token")):
        raise ValueError("GitLab is not configured — Opsboard → Settings → GitLab")
    return parse.quote(project, safe="")


def whoami():
    user = gitlab_get("user")
    return {"host": "gitlab", "user": user["username"], "name": user.get("name", ""), "project": gitlab_project(), "server": gitlab_url()}


def _own(iid, query=""):
    m = gitlab_get(f"projects/{_pid()}/merge_requests/{int(iid)}{query}")
    me = gitlab_get("user")["username"]
    if (m.get("author") or {}).get("username") != me:
        raise PermissionError(f"!{iid} was opened by {(m.get('author') or {}).get('username')}, not by {me} — only your own merge requests")
    return m


def info(iid):
    m = _own(iid, "?include_diverged_commits_count=true")
    return {
        "number": m["iid"],
        "title": m["title"],
        "url": m["web_url"],
        "state": m["state"],
        "draft": m.get("draft", False),
        "source": m["source_branch"],
        "target": m["target_branch"],
        "sha": m.get("sha"),
        "conflicts": m.get("has_conflicts", False),
        "merge_status": m.get("detailed_merge_status", ""),
        "behind": m.get("diverged_commits_count"),
        "description": m.get("description") or "",
    }


def mine(conflicts_only=False):
    me = gitlab_get("user")["username"]
    rows = gitlab_get(f"projects/{_pid()}/merge_requests", {"state": "opened", "author_username": me, "per_page": 100})
    return [
        {"number": m["iid"], "title": m["title"], "draft": m.get("draft", False), "source": m["source_branch"], "target": m["target_branch"], "conflicts": m.get("has_conflicts", False)}
        for m in rows
        if not conflicts_only or m.get("has_conflicts")
    ]


def threads(iid, include_resolved=False):
    m = _own(iid)
    me = gitlab_get("user")["username"]
    out, page = [], 1
    while True:
        batch = gitlab_get(f"projects/{_pid()}/merge_requests/{int(iid)}/discussions", {"per_page": 100, "page": page})
        for d in batch:
            first = d["notes"][0]
            if first.get("system") or first["author"]["username"] == me:
                continue
            resolvable = [n for n in d["notes"] if n.get("resolvable")]
            resolved = bool(resolvable) and all(n.get("resolved") for n in resolvable)
            if not include_resolved and (not resolvable or resolved):
                continue
            pos = first.get("position") or {}
            out.append(
                {
                    "id": d["id"],
                    "author": first["author"]["username"],
                    "bot": bool(first["author"].get("bot")) or "bot" in first["author"]["username"],
                    "where": f"{pos.get('new_path')}:{pos.get('new_line') or pos.get('old_line')}" if pos else None,
                    "url": f"{m['web_url']}#note_{first['id']}",
                    "body": first["body"],
                    "replies": [{"author": n["author"]["username"], "body": n["body"]} for n in d["notes"][1:]],
                    "resolved": resolved,
                }
            )
        if len(batch) < 100:
            break
        page += 1
    return out


def reply(iid, thread, body, resolve=False):
    _own(iid)
    gitlab_call("POST", f"projects/{_pid()}/merge_requests/{int(iid)}/discussions/{thread}/notes", {"body": body})
    if resolve:
        gitlab_call("PUT", f"projects/{_pid()}/merge_requests/{int(iid)}/discussions/{thread}?resolved=true")
    return {"replied": thread, "resolved": resolve}


def resolve_thread(iid, thread):
    _own(iid)
    gitlab_call("PUT", f"projects/{_pid()}/merge_requests/{int(iid)}/discussions/{thread}?resolved=true")
    return {"resolved": thread}


def describe(iid, body):
    old = _own(iid).get("description") or ""
    gitlab_call("PUT", f"projects/{_pid()}/merge_requests/{int(iid)}", {"description": body})
    return old


def upload(path):
    import uuid
    from pathlib import Path
    from urllib import request

    path = Path(path)
    boundary = uuid.uuid4().hex
    head = f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\nContent-Type: application/octet-stream\r\n\r\n'
    body = head.encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = request.Request(
        f"{gitlab_url()}/api/v4/projects/{_pid()}/uploads",
        data=body,
        method="POST",
        headers={"PRIVATE-TOKEN": cfg.secret("gitlab.token"), "Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with request.urlopen(req, timeout=60) as resp:
        return {"markdown": json.loads(resp.read().decode())["markdown"]}


def _paged(path, params=None):
    out, page = [], 1
    while True:
        batch = gitlab_get(path, {**(params or {}), "per_page": 100, "page": page})
        out += batch
        if len(batch) < 100 or page >= 30:
            return out
        page += 1


def _file_status(f):
    return "added" if f.get("new_file") else "deleted" if f.get("deleted_file") else "renamed" if f.get("renamed_file") else "modified"


def detail(iid):
    base = f"projects/{_pid()}/merge_requests/{int(iid)}"
    m = gitlab_get(base)
    try:
        raw = _paged(f"{base}/diffs")
    except error.HTTPError as exc:
        if exc.code != 404:
            raise
        raw = gitlab_get(f"{base}/changes").get("changes", [])
    files = [{"path": f["new_path"], "old_path": f["old_path"], "status": _file_status(f), "diff": f.get("diff") or "", "too_large": bool(f.get("too_large") or f.get("collapsed"))} for f in raw]
    threads = []
    for d in _paged(f"{base}/discussions"):
        notes = [n for n in d.get("notes", []) if not n.get("system")]
        if not notes:
            continue
        first = notes[0]
        resolvable = [n for n in notes if n.get("resolvable")]
        pos = first.get("position") or {}
        threads.append(
            {
                "id": d["id"],
                "resolvable": bool(resolvable),
                "resolved": bool(resolvable) and all(n.get("resolved") for n in resolvable),
                "resolved_by": next(((n["resolved_by"].get("name") or n["resolved_by"].get("username", "")) for n in reversed(resolvable) if n.get("resolved_by")), ""),
                "path": pos.get("new_path") or pos.get("old_path") or "",
                "new_line": pos.get("new_line"),
                "old_line": pos.get("old_line"),
                "url": f"{m['web_url']}#note_{first['id']}",
                "notes": [
                    {"author": n["author"].get("name") or n["author"]["username"], "username": n["author"]["username"], "body": n.get("body") or "", "created": epoch(n.get("created_at") or "")}
                    for n in notes
                ],
            }
        )
    return {
        "number": m["iid"],
        "title": m["title"],
        "url": m["web_url"],
        "author": (m.get("author") or {}).get("name", ""),
        "description": m.get("description") or "",
        "files": files,
        "threads": threads,
    }
