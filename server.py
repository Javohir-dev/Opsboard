import argparse
import gzip
import hmac
import json
import os
import re
import secrets
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import error

import config as cfg
import demo
import detect
import machine
import notify
import stackprofile as profile
import telegram
from core import DATA, HERE, gitlab_url, lock, log, loop, run, setup_logging, state
from notes import load_marks, load_notes, notes_lock, save_notes, set_mark
from providers import github, review_host, tracker
from providers.gitlab import gitlab_get
from providers.jira import jira_account, save_jira_account
from runs import fix_prompt, launch_fix, run_timeline, stop_run
from sessions import collect_sessions
from system import collect_claude_usage, collect_docker, collect_docker_df, collect_docker_stats, collect_mac, collect_mac_slow, collect_pg, collect_pg_sizes, collect_version, collect_worktrees
from tasks import collect_tasks_loop, refresh_tasks

RE_TOKENS = re.compile(r"ATATT[A-Za-z0-9_\-=]{20,}|glpat-[A-Za-z0-9_\-]{16,}|gh[pousr]_[A-Za-z0-9]{30,}|sk-ant-[A-Za-z0-9_\-]{20,}")


MR_CACHE = {}
MR_TTL = 60


def mr_detail(iid, fresh=False):
    with lock:
        mine = {m["iid"] for m in (state.get("review") or {}).get("mrs", [])}
    if not DEMO and iid not in mine:
        raise ValueError(f"!{iid} is not one of your merge requests")
    hit = MR_CACHE.get(iid)
    if hit and not fresh and time.time() - hit[0] < MR_TTL:
        return hit[1]
    out = demo.mr_detail(iid) if DEMO else review_host().detail(iid)
    out["fetched"] = time.time()
    MR_CACHE[iid] = (out["fetched"], out)
    return out


def redact(text):
    for key in cfg.SECRETS:
        value = cfg.secret(key)
        if value and len(value) >= 8:
            text = text.replace(value, "[redacted]")
    return RE_TOKENS.sub("[redacted]", text)


DEMO = os.environ.get("OPS_DEMO") == "1"


def snapshot():
    with lock:
        data = demo.build(time.time()) if DEMO else {k: v for k, v in state.items() if not k.startswith("_")}
        data["now"] = time.time()
        data["marks"] = load_marks()
        data["config"] = cfg.public()
        data["profile"] = profile.active()
        data["tracker"] = tracker()
        home = str(Path.home())
        data["paths"] = {k: str(v).replace(home, "~", 1) for k, v in (("config", cfg.CONFIG_FILE), ("home", HERE))}
        data["profiles"] = profile.names()
        data["notifications"] = notify.load()
        data["telegram"] = {"configured": False} if DEMO else telegram.public()
        return redact(json.dumps(data, default=str))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, body, ctype):
        raw = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        if len(raw) > 2048 and "gzip" in (self.headers.get("Accept-Encoding") or ""):
            raw = gzip.compress(raw, 5)
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def send_static(self, rel):
        root = (HERE / "static").resolve()
        path = (root / rel).resolve()
        if root not in path.parents or not path.is_file() or path.suffix not in STATIC_TYPES:
            self.send_error(404)
            return
        raw = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", STATIC_TYPES[path.suffix])
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def host_ok(self):
        if (self.headers.get("Host") or "").lower() in ALLOWED_HOSTS:
            return True
        self.send_error(421, "Unknown host")
        return False

    def same_origin(self):
        origin = self.headers.get("Origin")
        sent = self.headers.get("X-Ops-Token") or ""
        return (origin is None or origin in {f"http://{h}" for h in ALLOWED_HOSTS}) and hmac.compare_digest(sent, page_token())

    def do_POST(self):
        if not self.host_ok():
            return
        if not self.same_origin():
            self.send_error(403)
            return
        if self.path.startswith("/api/refresh-tasks"):
            refresh_tasks.set()
            self.send('{"ok": true}', "application/json")
        elif self.path.startswith("/api/fix-preview") or self.path.startswith("/api/fix"):
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                if self.path.startswith("/api/fix-preview"):
                    opts = {k: bool(body.get(k)) for k in ("threads", "conflict", "skiptests", "push")}
                    out = {"ok": True, "prompt": fix_prompt(int(body.get("iid")), opts)}
                elif DEMO:
                    raise ValueError("demo mode — nothing is started")
                else:
                    out = {"ok": True, "prompt": launch_fix(body)}
            except (ValueError, TypeError, OSError, subprocess.SubprocessError) as exc:
                out = {"ok": False, "error": str(exc)[:200]}
            self.send(json.dumps(out), "application/json")
        elif self.path.startswith("/api/detect"):
            results, notes = detect.detect_all()
            changed = detect.apply(results)
            self.send(json.dumps({"ok": True, "results": results, "notes": notes, "changed": changed}), "application/json")
        elif self.path.startswith("/api/task-mark"):
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                set_mark(str(body.get("key", "")), body.get("color") or None)
                out = {"ok": True}
            except (ValueError, OSError) as exc:
                out = {"ok": False, "error": str(exc)}
            self.send(json.dumps(out), "application/json")
        elif self.path.startswith("/api/notifications"):
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                if body.get("action") == "clear":
                    notify.clear()
                elif body.get("action") == "sound":
                    if not notify.play_sound():
                        raise ValueError("no sound player found (afplay on macOS, paplay or pw-play on Linux)")
                elif body.get("action") == "read":
                    ids = body.get("ids")
                    notify.mark_read({str(i) for i in ids} if isinstance(ids, list) else None)
                else:
                    raise ValueError("unknown action")
                out = {"ok": True}
            except ValueError as exc:
                out = {"ok": False, "error": str(exc)}
            self.send(json.dumps(out), "application/json")
        elif self.path.startswith("/api/run-stop"):
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                stop_run(str(body.get("id", "")))
                out = {"ok": True}
            except ValueError as exc:
                out = {"ok": False, "error": str(exc)}
            self.send(json.dumps(out), "application/json")
        elif self.path.startswith("/api/notes"):
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                out = save_notes(body)
            except (ValueError, TypeError) as exc:
                out = {"ok": False, "error": str(exc)[:200]}
            self.send(json.dumps(out, ensure_ascii=False), "application/json")
        elif self.path.startswith("/api/start-docker"):
            self.send(json.dumps(machine.start_docker()), "application/json")
        elif self.path.startswith("/api/pick-folder"):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            kind = "file" if body.get("kind") == "file" else "folder"
            self.send(json.dumps(machine.pick_path(str(body.get("start") or ""), str(body.get("prompt") or f"Choose a {kind}"), kind)), "application/json")
        elif self.path.startswith("/api/settings"):
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                key = str(body.get("key", ""))
                if key in cfg.SECRETS:
                    raise ValueError("tokens are saved through their own form")
                value = body.get("value")
                if key == "project.root" and value is not None:
                    value = str(Path(str(value)).expanduser())
                    if not Path(value).is_dir():
                        raise ValueError(f"folder not found: {value}")
                if key == "ui.hotkeys" and value is not None:
                    if not isinstance(value, dict) or len(value) > 30:
                        raise ValueError("bad shortcuts")
                    value = {str(k)[:20]: str(v).strip().lower()[:40] for k, v in value.items()}
                    combos = [v for v in value.values() if v]
                    if len(combos) != len(set(combos)):
                        raise ValueError("two pages use the same shortcut")
                if key == "claude.bin" and value is not None:
                    value = str(Path(str(value)).expanduser())
                    if not (Path(value).is_file() and os.access(value, os.X_OK)):
                        raise ValueError(f"not an executable file: {value}")
                    if not run([value, "--version"], timeout=10).strip():
                        raise ValueError(f"{value} does not answer to --version — is it the Claude CLI?")
                if key == "review.host" and value not in (None, "gitlab", "github"):
                    raise ValueError("unknown code host")
                if key == "tasks.tracker" and value not in (None, "", "jira", "none"):
                    raise ValueError("unknown task tracker")
                if key == "github.repo" and value and not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", str(value)):
                    raise ValueError("use owner/name")
                if key == "project.profile" and value not in (None, *profile.names()):
                    raise ValueError("unknown profile")
                if key == "claude.fix_skill" and value and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", str(value)):
                    raise ValueError("not a skill name")
                if key == "claude.reply_language" and value not in (None, "thread", "uz", "ru", "en"):
                    raise ValueError("unknown reply language")
                if key in ("server.port", "refresh.tasks_seconds") and value is not None:
                    value = int(value)
                    if not (1024 <= value <= 65535 if key == "server.port" else 30 <= value <= 3600):
                        raise ValueError("value out of range")
                cfg.set(key, value, "user", "Settings page")
                if key in ("project.root", "jira.projects", "jira.jql"):
                    threading.Thread(target=lambda: detect.apply(detect.detect_all()[0]), daemon=True).start()
                    refresh_tasks.set()
                elif key == "claude.live_usage":
                    threading.Thread(target=collect_claude_usage, daemon=True).start()
                elif key in ("review.host", "tasks.tracker", "gitlab.url", "gitlab.project", "github.url", "github.repo", "jira.site", "jira.email"):
                    refresh_tasks.set()
                out = {"ok": True, "entry": cfg.entry(key)}
            except (ValueError, TypeError) as exc:
                out = {"ok": False, "error": str(exc)[:200]}
            self.send(json.dumps(out), "application/json")
        elif self.path.startswith("/api/gitlab-account"):
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                token = body.get("token", "").strip() or cfg.secret("gitlab.token")
                base = (body.get("url", "").strip() or gitlab_url()).rstrip("/")
                if not base.startswith(("https://", "http://")):
                    raise ValueError("GitLab URL must start with https://")
                if not token:
                    raise ValueError("token is required")
                user = gitlab_get("user", token=token, base=base)["username"]
                cfg.set_secret("gitlab.token", token)
                if body.get("url"):
                    cfg.set("gitlab.url", base, "user", "Settings page")
                cfg.set("gitlab.username", user, "auto", "GitLab /user")
                detect.apply(detect.detect_all()[0])
                refresh_tasks.set()
                out = {"ok": True, "name": user}
            except error.HTTPError as exc:
                out = {"ok": False, "error": f"GitLab rejected this token ({exc.code})"}
            except (error.URLError, ValueError, KeyError, OSError) as exc:
                out = {"ok": False, "error": str(exc)[:200]}
            self.send(json.dumps(out), "application/json")
        elif self.path.startswith("/api/github-account"):
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                token = body.get("token", "").strip() or cfg.secret("github.token")
                url = (body.get("url", "").strip() or cfg.get("github.url") or "https://github.com").rstrip("/")
                if not url.startswith("https://"):
                    raise ValueError("GitHub URL must start with https://")
                if not token:
                    raise ValueError("token is required")
                base = "https://api.github.com" if url == "https://github.com" else f"{url}/api/v3"
                user = github.get("user", token=token, base=base)["login"]
                cfg.set_secret("github.token", token)
                if body.get("url"):
                    cfg.set("github.url", url, "user", "Settings page")
                cfg.set("github.username", user, "auto", "GitHub /user")
                detect.apply(detect.detect_all()[0])
                refresh_tasks.set()
                out = {"ok": True, "name": user}
            except error.HTTPError as exc:
                out = {"ok": False, "error": f"GitHub rejected this token ({exc.code})"}
            except (error.URLError, ValueError, KeyError, OSError) as exc:
                out = {"ok": False, "error": str(exc)[:200]}
            self.send(json.dumps(out), "application/json")
        elif self.path.startswith("/api/telegram-account"):
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                token = str(body.get("token", "")).strip()
                if not re.fullmatch(r"\d{5,}:[A-Za-z0-9_-]{30,}", token):
                    raise ValueError("this does not look like a bot token from @BotFather")
                bot = telegram.call("getMe", token=token)["username"]
                if token != cfg.secret("telegram.token"):
                    cfg.set("telegram.chat_id", None, "user")
                    cfg.set("telegram.user", None, "user")
                cfg.set_secret("telegram.token", token)
                telegram.connected(bot)
                out = {"ok": True, "name": "@" + bot, "telegram": telegram.public()}
            except telegram.TelegramError as exc:
                out = {"ok": False, "error": f"Telegram rejected this token: {exc}"}
            except ValueError as exc:
                out = {"ok": False, "error": str(exc)[:200]}
            self.send(json.dumps(out), "application/json")
        elif self.path.startswith("/api/telegram"):
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                action = body.get("action")
                if action == "unlink":
                    cfg.set("telegram.chat_id", None, "user")
                    cfg.set("telegram.user", None, "user")
                elif action == "forget":
                    cfg.set_secret("telegram.token", "")
                    cfg.set("telegram.chat_id", None, "user")
                    cfg.set("telegram.user", None, "user")
                elif action == "test":
                    if not telegram.send("👋 Opsboard is connected. Send /help to see what I can do."):
                        raise ValueError("could not send — is the chat linked?")
                else:
                    raise ValueError("unknown action")
                out = {"ok": True}
            except ValueError as exc:
                out = {"ok": False, "error": str(exc)[:200]}
            self.send(json.dumps(out), "application/json")
        elif self.path.startswith("/api/jira-account"):
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                email = body.get("email", "").strip()
                token = body.get("token", "").strip() or cfg.secret("jira.token")
                site = body.get("site", "").strip().rstrip("/") or None
                if site and not site.startswith("https://"):
                    raise ValueError("Jira site must start with https://")
                if not email or not token:
                    raise ValueError("email and token are required")
                me = save_jira_account(email, token, site)
            except error.HTTPError as exc:
                self.send(json.dumps({"ok": False, "error": f"Jira rejected these credentials ({exc.code})"}), "application/json")
                return
            except (error.URLError, ValueError, OSError) as exc:
                self.send(json.dumps({"ok": False, "error": str(exc)[:200]}), "application/json")
                return
            with lock:
                state["jira"] = {"configured": True, "account": jira_account()}
            refresh_tasks.set()
            self.send(json.dumps({"ok": True, "name": me.get("displayName", "")}), "application/json")
        else:
            self.send_error(404)

    def do_GET(self):
        if not self.host_ok():
            return
        if self.path.startswith("/api/notes"):
            with notes_lock:
                self.send(json.dumps(load_notes(), ensure_ascii=False), "application/json")
        elif self.path.startswith("/api/mr?"):
            query = dict(p.split("=", 1) for p in self.path.split("?", 1)[1].split("&") if "=" in p)
            try:
                out = {"ok": True, "mr": mr_detail(int(query.get("iid", "")), query.get("fresh") == "1")}
            except (ValueError, PermissionError, KeyError) as exc:
                out = {"ok": False, "error": str(exc)[:300]}
            except (error.URLError, OSError) as exc:
                out = {"ok": False, "error": f"{exc.__class__.__name__}: {str(exc)[:200]}"}
            self.send(redact(json.dumps(out, ensure_ascii=False)), "application/json")
        elif self.path.startswith("/api/run?"):
            query = dict(p.split("=", 1) for p in self.path.split("?", 1)[1].split("&") if "=" in p)
            try:
                out = {"ok": True, **(demo.run_timeline(query.get("id", "")) if DEMO else run_timeline(query.get("id", "")))}
            except ValueError as exc:
                out = {"ok": False, "error": str(exc)}
            self.send(redact(json.dumps(out, ensure_ascii=False, default=str)), "application/json")
        elif self.path.startswith("/api/doctor"):
            self.send(redact(json.dumps(demo.DOCTOR if DEMO else detect.doctor())), "application/json")
        elif self.path.startswith("/api/state"):
            notify.page_seen("alerts=1" in self.path)
            self.send(snapshot(), "application/json")
        elif self.path.startswith("/static/"):
            self.send_static(self.path.split("?")[0][len("/static/") :])
        elif self.path.split("?")[0] in ("/", "/index.html"):
            page = (HERE / "index.html").read_text(encoding="utf-8")
            self.send(page.replace("{{OPS_TOKEN}}", page_token(), 1), "text/html; charset=utf-8")
        else:
            self.send_error(404)


ALLOWED_HOSTS = set()
STATIC_TYPES = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".json": "application/json; charset=utf-8"}
TOKEN_FILE = Path(os.environ.get("OPS_TOKEN_FILE", DATA / ".page-token"))


def page_token():
    try:
        return TOKEN_FILE.read_text().strip()
    except OSError:
        token = secrets.token_urlsafe(32)
        fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(token)
        return token


class Server(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def serve_demo(port):
    if not os.environ.get("OPS_DATA_DIR"):
        raise SystemExit("demo mode needs OPS_DATA_DIR pointing to an empty folder — it never touches your own data")
    if not cfg.CONFIG_FILE.exists():
        for key, value in demo.DEMO_CONFIG.items():
            cfg.set(key, value, "user", "demo")
        cfg.set_secret("github.token", "demo-github-token")
        cfg.set_secret("jira.token", "demo-jira-token")
    if not notify.FILE.exists():
        notify.FILE.write_text(json.dumps(demo.notifications(time.time())))
    ALLOWED_HOSTS.update({f"127.0.0.1:{port}", f"localhost:{port}"})
    page_token()
    log.info("demo mode on http://127.0.0.1:%s/", port)
    print(f"http://127.0.0.1:{port}/ (demo)", flush=True)
    Server(("127.0.0.1", port), Handler).serve_forever()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    setup_logging()
    if not (machine.IS_MAC or machine.IS_LINUX):
        raise SystemExit(f"Opsboard supports macOS and Linux — {machine.OS_NAME} is not supported")
    args.port = args.port or int(cfg.get("server.port", 8095))
    if DEMO:
        serve_demo(args.port)
        return
    collect_mac_slow()
    for first in (collect_docker, collect_pg_sizes, collect_worktrees):
        try:
            first()
        except Exception:  # noqa: BLE001
            log.exception("initial %s failed", first.__name__)
    for interval, fn in (
        (60, collect_mac_slow),
        (0.5, collect_mac),
        (2, collect_sessions),
        (8, collect_docker),
        (3, collect_docker_stats),
        (120, collect_docker_df),
        (3, collect_pg),
        (60, collect_pg_sizes),
        (30, collect_worktrees),
        (6 * 3600, collect_version),
        (30, collect_claude_usage),
    ):
        loop(interval, fn)
    threading.Thread(target=lambda: detect.apply(detect.detect_all()[0]), daemon=True).start()
    threading.Thread(target=collect_tasks_loop, daemon=True).start()
    notify.HOOKS.append(telegram.on_notify)
    telegram.start()
    ALLOWED_HOSTS.update({f"127.0.0.1:{args.port}", f"localhost:{args.port}"})
    page_token()
    server = Server(("127.0.0.1", args.port), Handler)
    log.info("listening on http://127.0.0.1:%s/ (data in %s, secrets in %s)", args.port, DATA, cfg.secretstore.name())
    print(f"http://127.0.0.1:{args.port}/", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
