import math
import random
import time

GB = 1024**3
MB = 1024**2


def _history(now, base, spread, n=120):
    rnd = random.Random(int(now) // 2)
    return [max(0.0, base + spread * math.sin(i / 7) + rnd.uniform(-spread / 3, spread / 3)) for i in range(n)]


def _session(now, sid, title, name, status, branch, prompts, activity, agents=(), jobs=(), uses=None, skills=(), model="claude-opus-5-5"):
    uses = uses or {}
    return {
        "pid": 40000 + hash(sid) % 20000,
        "id": sid,
        "name": name,
        "name_source": "derived",
        "run_id": None,
        "status": status,
        "entrypoint": "cli",
        "version": "2.1.300",
        "started": now - 3 * 3600,
        "status_since": now - (40 if status == "busy" else 1800),
        "cwd": "/home/dev/acme-shop",
        "branch": branch,
        "title": title,
        "last_prompt": prompts[-1][1],
        "last_prompt_ts": now - prompts[-1][0],
        "prompts": [{"ts": now - ago, "text": text, "images": 0, "end": now - ago + took, "tools": tools, "agents": 0, "queued": False} for ago, text, took, tools in prompts],
        "last_ts": now - activity[0][2],
        "doing": {"tool": activity[0][0], "what": activity[0][1], "ts": now - activity[0][2]} if status == "busy" else None,
        "activity": [{"tool": tool, "what": what, "ts": now - ago} for tool, what, ago in activity],
        "model": model,
        "tokens": {"input_tokens": 84000, "output_tokens": 61000, "cache_read_input_tokens": 9_800_000, "cache_creation_input_tokens": 420000},
        "cpu": 1.2 if status == "busy" else 0.1,
        "rss": 310 * MB,
        "children": [],
        "bash": [{"ts": now - ago, "cmd": what, "desc": what} for tool, what, ago in activity if tool == "Bash"],
        "agents": list(agents),
        "jobs": list(jobs),
        "skills": [{"name": s, "count": 1, "last": now - 900} for s in skills],
        "mcp": [],
        "tools": [["Bash", 64], ["Edit", 31], ["Read", 48]],
        "containers": [{"name": n, "count": 3, "last": now - 600} for n in uses.get("containers", [])],
        "dbs": [{"name": n, "count": 2, "last": now - 700} for n in uses.get("dbs", [])],
        "worktrees": [{"name": n, "count": 5, "last": now - 300} for n in uses.get("worktrees", [])],
        "invoke": [],
    }


def _pr(now, number, title, state, created_ago, updated_ago, keys, source, threads=None, total=None, pipeline="", approved_by=(), labels=(), conflicts=False, draft=False):
    return {
        "iid": number,
        "title": title,
        "url": f"https://github.com/acme/shop/pull/{number}",
        "state": state,
        "draft": draft,
        "conflicts": conflicts,
        "merge_status": "dirty" if conflicts else "clean",
        "source": source,
        "target": "main",
        "created": now - created_ago,
        "updated": now - updated_ago,
        "merged": now - updated_ago if state == "merged" else 0,
        "closed": now - updated_ago if state == "closed" else 0,
        "keys": keys,
        "module": "",
        "plan": None,
        "threads": threads,
        "threads_total": total,
        "pipeline": pipeline,
        "approved": bool(approved_by),
        "approved_by": list(approved_by),
        "labels": list(labels),
        "author": "dev",
        "reviewers": ["maria", "li"] if state == "opened" else [],
    }


def build(now):
    h = 3600
    d = 86400
    containers = [
        ("shop-db-1", "postgres:16", 5432, "5432"),
        ("shop-web-1", "acme/shop:dev", 8000, "8000"),
        ("shop-redis-1", "redis:7-alpine", None, None),
        ("shop-qa-checkout-fix", "acme/shop:dev", 55101, "8000"),
        ("shop-qa-search-filters", "acme/shop:dev", 55102, "8000"),
    ]
    issues = [
        ("SHOP-142", "Checkout: keep the cart when the payment page times out", "In Progress", "indeterminate", 2 * h),
        ("SHOP-139", "Search: filter by brand and price range", "In Review", "indeterminate", 5 * h),
        ("SHOP-151", "Invoices: PDF shows the wrong VAT for EU customers", "To Do", "new", 1 * d),
        ("SHOP-133", "Admin: bulk edit product prices", "Done", "done", 2 * d),
        ("SHOP-155", "Mobile: product images load twice", "To Do", "new", 3 * h),
        ("SHOP-128", "Orders: export to CSV", "Done", "done", 4 * d),
        ("SHOP-160", "Login: rate limit password resets", "In Review", "indeterminate", 6 * h),
    ]
    prs = [
        _pr(now, 412, "SHOP-142: keep the cart when payment times out", "opened", 9 * h, 40 * 60, ["SHOP-142"], "fix/checkout-timeout", 2, 5, "running", ["maria"], ["bug", "checkout"]),
        _pr(now, 409, "SHOP-139: brand and price filters", "opened", 2 * d, 3 * h, ["SHOP-139"], "feat/search-filters", 0, 4, "success", ["maria", "li"], ["feature", "search"]),
        _pr(now, 415, "SHOP-160: rate limit password resets", "opened", 5 * h, 2 * h, ["SHOP-160"], "feat/reset-rate-limit", 1, 1, "failed", [], ["security"], conflicts=True),
        _pr(now, 401, "SHOP-133: bulk edit prices", "merged", 3 * d, 2 * d, ["SHOP-133"], "feat/bulk-prices"),
        _pr(now, 398, "SHOP-128: orders CSV export", "merged", 5 * d, 4 * d, ["SHOP-128"], "feat/orders-csv"),
    ]
    sessions = [
        _session(
            now,
            "demo-1",
            "Checkout timeout fix",
            "shop-checkout",
            "busy",
            "fix/checkout-timeout",
            [(2 * h, "SHOP-142: the cart is lost when the payment page times out — find why and fix it", 25 * 60, 41), (12 * 60, "run the checkout tests again and push", 0, 9)],
            [("Bash", "Run checkout tests", 30), ("Edit", "cart/session.py", 140), ("Read", "payments/gateway.py", 300)],
            agents=[
                {
                    "id": "a1",
                    "description": "Review the payment retry flow",
                    "type": "general-purpose",
                    "model": "",
                    "background": True,
                    "started": now - 600,
                    "status": "running",
                    "ended": 0,
                    "summary": "",
                    "usage": {},
                    "depth": 1,
                    "last_write": now - 20,
                    "tools": 23,
                    "doing": {"tool": "Read", "what": "payments/retry.py", "ts": now - 20},
                }
            ],
            uses={"containers": ["shop-qa-checkout-fix", "shop-db-1"], "dbs": ["shop_checkout_fix"], "worktrees": ["checkout-fix"]},
            skills=["fix-review"],
        ),
        _session(
            now,
            "demo-2",
            "Search filters review",
            "shop-search",
            "idle",
            "feat/search-filters",
            [(5 * h, "/fix-review 409 push", 40 * 60, 77)],
            [("Bash", "opsboard review threads 409", 4 * h), ("Edit", "search/filters.py", 4 * h + 300)],
            agents=[
                {
                    "id": "a2",
                    "description": "Check filter SQL plans",
                    "type": "general-purpose",
                    "model": "",
                    "background": False,
                    "started": now - 5 * h,
                    "status": "completed",
                    "ended": now - 4 * h,
                    "summary": "",
                    "usage": {},
                    "depth": 1,
                    "last_write": now - 4 * h,
                    "tools": 18,
                    "doing": None,
                }
            ],
            uses={"containers": ["shop-qa-search-filters"], "dbs": ["shop_search_filters"], "worktrees": ["search-filters"]},
            skills=["fix-review"],
        ),
        _session(
            now,
            "demo-3",
            "VAT on EU invoices",
            "shop-invoices",
            "idle",
            "main",
            [(1 * d, "why does the invoice PDF show 0% VAT for German customers?", 18 * 60, 30)],
            [("Read", "invoices/vat.py", 1 * d)],
            uses={"dbs": ["shop"]},
            model="claude-sonnet-5-5",
        ),
    ]
    worktrees = [
        {
            "name": "checkout-fix",
            "path": "/home/dev/acme-shop.worktrees/checkout-fix",
            "slug": "checkout_fix",
            "branch": "fix/checkout-timeout",
            "dirty": 3,
            "last_commit_ts": now - 40 * 60,
            "last_commit": "Keep the cart id across payment retries",
            "mtime": now - 60,
        },
        {
            "name": "search-filters",
            "path": "/home/dev/acme-shop.worktrees/search-filters",
            "slug": "search_filters",
            "branch": "feat/search-filters",
            "dirty": 0,
            "last_commit_ts": now - 3 * h,
            "last_commit": "Brand filter: use the index",
            "mtime": now - 3 * h,
        },
        {
            "name": "reset-rate-limit",
            "path": "/home/dev/acme-shop.worktrees/reset-rate-limit",
            "slug": "reset_rate_limit",
            "branch": "feat/reset-rate-limit",
            "dirty": 0,
            "last_commit_ts": now - 2 * h,
            "last_commit": "Limit resets per account and IP",
            "mtime": now - 2 * h,
        },
    ]
    return {
        "history": {"cpu": _history(now, 28, 12), "mem": _history(now, 62, 4), "gpu": _history(now, 6, 5), "net_in": _history(now, 40000, 30000), "net_out": _history(now, 12000, 8000)},
        "mac_static": {
            "os": "macOS",
            "mem_total": 32 * GB,
            "ncpu": "12",
            "chip": "Apple M3 Pro",
            "model": "Mac15,6",
            "pcores": "6",
            "ecores": "6",
            "power": "AC",
            "battery": 92,
            "battery_state": "charging",
            "cpu_speed_limit": 100,
        },
        "mac": {
            "cpu_user": 19.4,
            "cpu_sys": 8.1,
            "cpu": 27.5,
            "load": [3.1, 2.8, 2.6],
            "mem_used": 19.8 * GB,
            "mem_wired": 3.1 * GB,
            "mem_compressed": 2.2 * GB,
            "mem_unused": 1.4 * GB,
            "processes": 512,
            "mem_free_pct": 58,
            "swap_total": 4 * GB,
            "swap_used": 0.6 * GB,
            "gpu": 6,
            "gpu_renderer": 4,
            "gpu_mem": 900 * MB,
            "disk_total": 994 * GB,
            "disk_used": 512 * GB,
            "disk_free": 482 * GB,
            "net_in": 41200,
            "net_out": 9800,
            "os": "macOS",
            "mem_total": 32 * GB,
            "ncpu": "12",
            "chip": "Apple M3 Pro",
            "model": "Mac15,6",
            "pcores": "6",
            "ecores": "6",
            "power": "AC",
            "battery": 92,
            "battery_state": "charging",
        },
        "containers": [
            {
                "name": n,
                "image": img,
                "state": "running",
                "health": None,
                "started": now - 6 * h,
                "finished": 0,
                "ports": [{"host": hp, "container": cp}] if hp else [],
                "ips": [f"172.20.0.{i + 2}"],
                "db_name": "",
                "service": n.split("-")[1],
                "project": "shop",
            }
            for i, (n, img, hp, cp) in enumerate(containers)
        ],
        "docker_stats": {n: {"cpu": 2.0 if "db" in n else 0.3, "mem": (900 if "db" in n else 310) * MB, "mem_limit": 8 * GB} for n, *_ in containers},
        "docker_df": {
            "rows": [
                {"Active": "5", "Reclaimable": "1.2GB (21%)", "Size": "5.6GB", "TotalCount": "7", "Type": "Images"},
                {"Active": "5", "Reclaimable": "0B (0%)", "Size": "12MB", "TotalCount": "5", "Type": "Containers"},
                {"Active": "3", "Reclaimable": "0B (0%)", "Size": "2.1GB", "TotalCount": "3", "Type": "Local Volumes"},
            ],
            "ncpu": "8",
            "mem": 8 * GB,
            "version": "29.1.3",
        },
        "pg": {
            "ok": True,
            "max_connections": 100,
            "waiting_locks": 0,
            "version": "PostgreSQL 16.4",
            "conns": [
                {"db": "shop", "state": "idle", "addr": "172.20.0.3", "count": 6, "for": 900},
                {"db": "shop_checkout_fix", "state": "active", "addr": "172.20.0.5", "count": 2, "for": 2},
                {"db": "shop_search_filters", "state": "idle", "addr": "172.20.0.6", "count": 3, "for": 4000},
            ],
            "active": [{"pid": 811, "db": "shop_checkout_fix", "addr": "172.20.0.5", "state": "active", "wait": "", "secs": 2, "query": "select id, total from cart where session_id = $1 for update"}],
        },
        "pg_sizes": {"shop": 1400 * MB, "shop_checkout_fix": 1380 * MB, "shop_search_filters": 1390 * MB, "postgres": 8 * MB},
        "worktrees": worktrees,
        "sessions": sessions,
        "procs": {
            "cpu": [{"pid": 501, "name": "node", "cpu": 34.0, "rss": 640 * MB, "args": "node web/dev-server.js"}, {"pid": 502, "name": "postgres", "cpu": 12.0, "rss": 900 * MB, "args": "postgres"}],
            "mem": [{"pid": 502, "name": "postgres", "cpu": 12.0, "rss": 900 * MB, "args": "postgres"}, {"pid": 501, "name": "node", "cpu": 34.0, "rss": 640 * MB, "args": "node web/dev-server.js"}],
            "count": 512,
        },
        "runs": [
            {
                "id": "r1",
                "iid": 409,
                "name": "fix-review !409 push",
                "prompt": "/fix-review 409 push",
                "pid": 0,
                "started": now - 5 * h,
                "status": "done",
                "result": "Fixed 3 review threads, pushed.",
                "ended": now - 4 * h,
                "outcome": {"status": "pushed", "commit": "a1b2c3d", "threads": {"resolved": 3, "open": 0}, "checks": "tests 128/128"},
            },
        ],
        "review": {
            "host": "github",
            "configured": True,
            "mrs": prs,
            "fetched": now - 90,
            "user": "dev",
            "labels": {
                "bug": {"color": "#d73a4a", "text": "#ffffff"},
                "feature": {"color": "#a2eeef", "text": "#1f2328"},
                "checkout": {"color": "#fbca04", "text": "#1f2328"},
                "search": {"color": "#0e8a16", "text": "#ffffff"},
                "security": {"color": "#b60205", "text": "#ffffff"},
            },
        },
        "jira": {
            "configured": True,
            "fetched": now - 95,
            "site": "https://acme.atlassian.net",
            "account": {"connected": True, "email": "dev@acme.example", "name": "Dev"},
            "issues": [
                {
                    "key": k,
                    "summary": s,
                    "status": st,
                    "category": cat,
                    "priority": "Medium",
                    "type": "Story",
                    "created": now - 6 * d,
                    "updated": now - upd,
                    "resolved": now - upd if cat == "done" else 0,
                    "due": None,
                }
                for k, s, st, cat, upd in issues
            ],
        },
        "key_aliases": {},
        "version": {"current": "0.10.0", "latest": "", "checked": now},
        "claude_usage": {
            "fetched": now - 120,
            "account": {"email": "dev@acme.example", "org": "Acme", "plan": "Claude Team"},
            "limits": [
                {"label": "Session (5hr)", "percent": 38, "severity": "normal", "resets_at": now + 35 * 60, "active": True},
                {"label": "Weekly (7 day)", "percent": 34, "severity": "normal", "resets_at": now + 4 * d, "active": False},
                {"label": "Weekly Fable", "percent": 0, "severity": "normal", "resets_at": now + 4 * d, "active": False},
            ],
        },
    }


DEMO_CONFIG = {
    "project.root": "/home/dev/acme-shop",
    "review.host": "github",
    "github.repo": "acme/shop",
    "github.username": "dev",
    "tasks.tracker": "jira",
    "jira.site": "https://acme.atlassian.net",
    "jira.email": "dev@acme.example",
    "jira.name": "Dev",
    "jira.projects": ["SHOP"],
    "db.container": "shop-db-1",
    "db.user": "postgres",
    "project.profile": "generic",
    "project.worktrees": "",
    "claude.skills": ["fix-review", "release-notes"],
    "claude.fix_skill": "fix-review",
    "claude.bin": "/usr/local/bin/claude",
    "claude.version": "2.1.300",
}


DEMO_DIFF = "\n".join(
    [
        "@@ -12,9 +12,11 @@ def cart_total(cart):",
        "     subtotal = sum(line.price * line.qty for line in cart.lines)",
        "-    discount = subtotal * cart.discount_rate",
        "-    total = subtotal - discount",
        "+    discount = round(subtotal * cart.discount_rate, 2)",
        "+    total = round(subtotal - discount, 2)",
        "+    if total < 0:",
        "+        total = 0",
        "     return total",
        " ",
        " ",
        " def cart_tax(cart):",
        "@@ -40,6 +42,7 @@ def checkout(cart, payment):",
        "     total = cart_total(cart)",
        "     tax = cart_tax(cart)",
        '+    log.info("checkout total=%s tax=%s", total, tax)',
        "     return payment.charge(total + tax)",
        "",
    ]
)


def mr_detail(iid):
    now = time.time()
    note = lambda who, body, ago: {"author": who, "username": who.lower(), "body": body, "created": now - ago}  # noqa: E731
    return {
        "number": iid,
        "title": "SHOP-139: brand and price filters",
        "url": f"https://github.com/acme/shop/pull/{iid}",
        "author": "dev",
        "description": "Rounds cart totals and logs the checkout amounts.",
        "files": [
            {"path": "shop/cart.py", "old_path": "shop/cart.py", "status": "modified", "diff": DEMO_DIFF, "too_large": False},
            {
                "path": "shop/tests/test_cart.py",
                "old_path": "shop/tests/test_cart.py",
                "status": "added",
                "diff": "@@ -0,0 +1,4 @@\n+def test_total_is_rounded(cart):\n+    cart.discount_rate = 0.333\n+    assert cart_total(cart) == 6.67\n+\n",
                "too_large": False,
            },
        ],
        "threads": [
            {
                "id": "t1",
                "resolvable": True,
                "resolved": False,
                "resolved_by": "",
                "path": "shop/cart.py",
                "new_line": 17,
                "old_line": None,
                "url": "",
                "notes": [
                    note("Lena", "Can the total really go below zero? If not, an `assert` is clearer than clamping.", 7200),
                    note("dev", "It can with a 100% coupon plus a store credit. Kept the clamp and added a test.", 3600),
                ],
            },
            {
                "id": "t2",
                "resolvable": True,
                "resolved": True,
                "resolved_at": now - 7000,
                "resolved_by": "Max",
                "path": "shop/cart.py",
                "new_line": 44,
                "old_line": None,
                "url": "",
                "notes": [note("Max", "Please do not log totals at info level — use **debug**.", 9000), note("dev", "Done in a1b2c3d.", 8000)],
            },
            {
                "id": "t3",
                "resolvable": False,
                "resolved": False,
                "resolved_by": "",
                "path": "",
                "new_line": None,
                "old_line": None,
                "url": "",
                "notes": [note("Lena", "Looks good overall, thanks!", 600)],
            },
        ],
    }


def notifications(now):
    return [
        {
            "id": "n1",
            "kind": "run",
            "run_id": "r1",
            "iid": 409,
            "name": "fix-review !409 push",
            "status": "done",
            "outcome": {"status": "pushed", "commit": "a1b2c3d", "threads": {"resolved": 3, "open": 0}, "checks": "tests 128/128"},
            "error": "",
            "mr_title": "Fix rounding in cart totals",
            "at": now - 4 * 3600,
            "read": False,
        },
    ]


DOCTOR = [
    {"id": "project", "ok": True, "detail": "/home/dev/acme-shop", "fix": ""},
    {"id": "github", "ok": True, "detail": "dev @ https://github.com/acme/shop", "fix": ""},
    {"id": "jira", "ok": True, "detail": "Dev @ https://acme.atlassian.net", "fix": ""},
    {"id": "docker", "ok": True, "detail": "running", "fix": ""},
    {"id": "postgres", "ok": True, "detail": "shop-db-1 as postgres", "fix": ""},
    {"id": "claude", "ok": True, "detail": "2.1.300", "fix": ""},
    {"id": "fix-skill", "ok": True, "detail": "fix-review installed", "fix": ""},
]
