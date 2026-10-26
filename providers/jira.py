import base64
import collections
import time
from urllib import error

import config as cfg
import detect
from core import epoch, http_json, jira_site, lock, put, state


def jira_configured():
    return bool(cfg.get("jira.email") and cfg.secret("jira.token"))


def jira_headers(email=None, token=None):
    email, token = email or cfg.get("jira.email"), token or cfg.secret("jira.token")
    auth = base64.b64encode(f"{email}:{token}".encode()).decode()
    return {"Authorization": f"Basic {auth}", "Accept": "application/json"}


def jira_whoami(email, token, site=None):
    return http_json(f"{(site or jira_site()).rstrip('/')}/rest/api/3/myself", jira_headers(email, token))


def save_jira_account(email, token, site=None):
    me = jira_whoami(email, token, site)
    if site:
        cfg.set("jira.site", site.rstrip("/"), "user")
    cfg.set("jira.email", email, "user")
    cfg.set_secret("jira.token", token)
    cfg.set("jira.name", me.get("displayName", ""), "auto", "Jira /myself")
    return me


def jira_account():
    if not jira_configured():
        return {"connected": False}
    return {"connected": True, "email": cfg.get("jira.email", ""), "name": cfg.get("jira.name", "")}


_sprint_field = {"site": None, "id": None}


def sprint_field(headers):
    """The id of Jira's Sprint field (it differs per site), looked up once."""
    if _sprint_field["site"] != jira_site():
        fid = None
        try:
            fid = next((f["id"] for f in http_json(f"{jira_site()}/rest/api/3/field", headers) if (f.get("schema") or {}).get("custom") == "com.pyxis.greenhopper.jira:gh-sprint"), None)
        except (error.URLError, ValueError, KeyError, OSError):
            return None
        _sprint_field.update(site=jira_site(), id=fid)
    return _sprint_field["id"]


SPRINT_ORDER = {"active": 0, "future": 1, "closed": 2}


def pick_sprint(values):
    """The sprint an issue belongs to now: the active one, else the next future one, else the last closed one."""
    sprints = [
        {"id": s.get("id"), "name": s.get("name", ""), "state": s.get("state", ""), "start": epoch(s.get("startDate") or ""), "end": epoch(s.get("endDate") or ""), "goal": s.get("goal") or ""}
        for s in values or []
        if isinstance(s, dict)
    ]
    if not sprints:
        return None
    sprints.sort(key=lambda s: (SPRINT_ORDER.get(s["state"], 3), s["start"] if s["state"] != "closed" else -s["end"]))
    return sprints[0]


def collect():
    if not jira_configured():
        put("jira", {"configured": False, "site": jira_site()})
        return
    issues, token = [], None
    fields = ["summary", "status", "priority", "issuetype", "created", "updated", "duedate", "resolutiondate", "assignee", "reporter", "labels", "parent"]
    try:
        headers = jira_headers()
        sprint_id = sprint_field(headers)
        if sprint_id:
            fields = fields + [sprint_id]
        while True:
            body = {"jql": cfg.get("jira.jql"), "fields": fields, "maxResults": 100}
            if token:
                body["nextPageToken"] = token
            page = http_json(f"{jira_site()}/rest/api/3/search/jql", headers, body)
            for it in page.get("issues", []):
                f = it["fields"]
                issues.append(
                    {
                        "key": it["key"],
                        "summary": f.get("summary", ""),
                        "status": (f.get("status") or {}).get("name", ""),
                        "category": ((f.get("status") or {}).get("statusCategory") or {}).get("key", ""),
                        "priority": (f.get("priority") or {}).get("name", ""),
                        "type": (f.get("issuetype") or {}).get("name", ""),
                        "created": epoch(f.get("created", "")),
                        "updated": epoch(f.get("updated", "")),
                        "resolved": epoch(f.get("resolutiondate") or ""),
                        "due": f.get("duedate"),
                        "assignee": (f.get("assignee") or {}).get("displayName", ""),
                        "reporter": (f.get("reporter") or {}).get("displayName", ""),
                        "labels": f.get("labels") or [],
                        "parent": {"key": (f.get("parent") or {}).get("key", ""), "summary": (((f.get("parent") or {}).get("fields") or {}).get("summary", ""))} if f.get("parent") else None,
                        "sprint": pick_sprint(f.get(sprint_id)) if sprint_id else None,
                    }
                )
            token = page.get("nextPageToken")
            if page.get("isLast", True) or not token:
                break
    except (error.URLError, ValueError, KeyError, OSError) as exc:
        with lock:
            prev = state.get("jira") or {}
        put("jira", dict(prev, configured=True, error=str(exc)[:300]))
        return
    put("jira", {"configured": True, "issues": issues, "fetched": time.time(), "site": jira_site(), "account": jira_account()})
    prefixes = collections.Counter(i["key"].split("-")[0] for i in issues)
    known = cfg.get("jira.projects") or []
    projects = list(dict.fromkeys(known + [p for p, _ in prefixes.most_common()]))
    if projects != known:
        cfg.set("jira.projects", projects, "auto", "your Jira issues and merge request titles", 1.0)
    status_map = dict(cfg.load()["settings"].get("jira.status_map", {}).get("auto", {}).get("value") or {})
    status_map.update(detect.detect_status_map(issues))
    if status_map:
        cfg.set("jira.status_map", status_map, "auto", "your Jira statuses", 0.8)


ISSUE_FIELDS = "summary,status,priority,issuetype,assignee,reporter,created,updated,duedate,resolutiondate,labels,parent,description,comment,subtasks,issuelinks"


def issue(key):
    """One issue with its description and comments rendered to HTML by Jira."""
    import re as _re

    if not _re.fullmatch(r"[A-Z][A-Z0-9_]{0,19}-\d{1,7}", key or ""):
        raise ValueError("not an issue key")
    it = http_json(f"{jira_site()}/rest/api/3/issue/{key}?fields={ISSUE_FIELDS}&expand=renderedFields", jira_headers())
    f, r = it.get("fields") or {}, it.get("renderedFields") or {}
    person = lambda u: {"name": (u or {}).get("displayName", ""), "avatar": ((u or {}).get("avatarUrls") or {}).get("48x48", "")}  # noqa: E731
    comments = (f.get("comment") or {}).get("comments") or []
    rendered = (r.get("comment") or {}).get("comments") or []
    return {
        "key": it["key"],
        "url": f"{jira_site()}/browse/{it['key']}",
        "summary": f.get("summary", ""),
        "status": (f.get("status") or {}).get("name", ""),
        "category": ((f.get("status") or {}).get("statusCategory") or {}).get("key", ""),
        "type": (f.get("issuetype") or {}).get("name", ""),
        "priority": (f.get("priority") or {}).get("name", ""),
        "assignee": person(f.get("assignee")),
        "reporter": person(f.get("reporter")),
        "labels": f.get("labels") or [],
        "parent": {"key": f["parent"]["key"], "summary": (f["parent"].get("fields") or {}).get("summary", "")} if f.get("parent") else None,
        "created": epoch(f.get("created") or ""),
        "updated": epoch(f.get("updated") or ""),
        "due": f.get("duedate"),
        "resolved": epoch(f.get("resolutiondate") or ""),
        "description": r.get("description") or "",
        "subtasks": [
            {"key": s["key"], "summary": (s.get("fields") or {}).get("summary", ""), "status": ((s.get("fields") or {}).get("status") or {}).get("name", "")} for s in f.get("subtasks") or []
        ],
        "comments": [
            {"author": person(c.get("author")), "created": epoch(c.get("created") or ""), "body": (rendered[i].get("body") if i < len(rendered) else "") or ""} for i, c in enumerate(comments)
        ],
    }
