import hashlib
import hmac
import json
import re
import secrets
import shutil
import subprocess
import threading
import time
from urllib.parse import parse_qsl

import config as cfg
import telegram
from core import log

INIT_MAX_AGE = 3600
SESSION_TTL = 12 * 3600
COOKIE = "ops_tg"
OPEN_PATHS = ("/", "/index.html", "/tg/auth")
BLOCKED = ("/api/settings", "/api/gitlab-account", "/api/github-account", "/api/jira-account", "/api/telegram-account", "/api/telegram", "/api/pick-folder")
TUNNEL_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
AUTH_PER_MINUTE = 20

_sessions = {}
_auth_times = []
_lock = threading.Lock()
_status = {"url": "", "host": "", "error": "", "running": False}
_proc = {"p": None}

BOOT = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Opsboard</title><style>body{margin:0;display:grid;place-items:center;height:100vh;font:15px system-ui,sans-serif;background:#1b1d22;color:#c9ccd3}</style></head>
<body><div id="m">Signing in…</div><script>
var p=new URLSearchParams(location.hash.slice(1)),d=p.get("tgWebAppData");
if(!d){document.getElementById("m").textContent="Open Opsboard from the Telegram bot's menu button."}
else fetch("/tg/auth",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({initData:d})}).then(function(r){return r.json()}).then(function(x){if(x.ok){history.replaceState(null,"","/");location.reload()}else document.getElementById("m").textContent="Not allowed: "+(x.error||"")}).catch(function(){document.getElementById("m").textContent="Could not reach Opsboard"});
</script></body></html>"""


def enabled():
    return bool(cfg.get("telegram.webapp"))


def check_init_data(raw, token, user_id, now=None, max_age=INIT_MAX_AGE):
    """Telegram's Web App signature: HMAC-SHA256 over the sorted fields, keyed with HMAC("WebAppData", bot token)."""
    if not raw or not token or not user_id or len(raw) > 8192:
        return False
    fields = dict(parse_qsl(raw, keep_blank_values=True))
    sent = fields.pop("hash", "")
    if not re.fullmatch(r"[0-9a-f]{64}", sent):
        return False
    key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    ok = False
    for drop in ((), ("signature",)):
        check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()) if k not in drop)
        ok = ok or hmac.compare_digest(hmac.new(key, check.encode(), hashlib.sha256).hexdigest(), sent)
    if not ok:
        return False
    try:
        age = (now or time.time()) - int(fields.get("auth_date", "0"))
        user = json.loads(fields.get("user") or "{}")
    except ValueError:
        return False
    return 0 <= age <= max_age and user.get("id") == user_id


def login(raw):
    now = time.time()
    with _lock:
        _auth_times[:] = [t for t in _auth_times if now - t < 60]
        if len(_auth_times) >= AUTH_PER_MINUTE:
            return None, "too many attempts"
        _auth_times.append(now)
    if not enabled():
        return None, "the Mini App is off"
    if not check_init_data(raw, cfg.secret("telegram.token"), telegram.chat_id()):
        log.warning("webapp: rejected a sign-in")
        return None, "this Telegram account is not linked to this Opsboard"
    sid = secrets.token_urlsafe(32)
    with _lock:
        for k in [k for k, v in _sessions.items() if v < now]:
            _sessions.pop(k, None)
        _sessions[sid] = now + SESSION_TTL
    return sid, ""


def session_ok(cookie_header):
    if not enabled():
        return False
    for part in (cookie_header or "").split(";"):
        name, _, value = part.strip().partition("=")
        if name == COOKIE and value:
            with _lock:
                exp = _sessions.get(value)
            return bool(exp and exp > time.time())
    return False


def gateway_class(base, page_token):
    class Gateway(base):
        def host_ok(self):
            path = self.path.split("?")[0]
            if not _status["host"] or (self.headers.get("Host") or "").lower() != _status["host"]:
                self.send_error(421, "Unknown host")
                return False
            if path.startswith(BLOCKED):
                self.send_error(403, "Not available from Telegram")
                return False
            if path not in OPEN_PATHS and not session_ok(self.headers.get("Cookie")):
                self.send_error(401)
                return False
            return True

        def same_origin(self):
            origin = self.headers.get("Origin")
            sent = self.headers.get("X-Ops-Token") or ""
            return origin in (None, f"https://{_status['host']}") and session_ok(self.headers.get("Cookie")) and hmac.compare_digest(sent, page_token())

        def do_GET(self):
            path = self.path.split("?")[0]
            if path in ("/", "/index.html") and not session_ok(self.headers.get("Cookie")):
                if not self.host_ok():
                    return None
                return self.send(BOOT, "text/html; charset=utf-8")
            return super().do_GET()

        def do_POST(self):
            if self.path.split("?")[0] != "/tg/auth":
                return super().do_POST()
            if not self.host_ok():
                return None
            if self.headers.get("Origin") not in (None, f"https://{_status['host']}"):
                return self.send_error(403)
            try:
                body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 10000)) or b"{}")
            except ValueError:
                body = {}
            sid, err = login(str(body.get("initData") or ""))
            raw = json.dumps({"ok": bool(sid), "error": err}).encode()
            self.send_response(200 if sid else 403)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            if sid:
                self.send_header("Set-Cookie", f"{COOKIE}={sid}; Path=/; Max-Age={SESSION_TTL}; HttpOnly; Secure; SameSite=Lax")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return None

    return Gateway


def public():
    return {"enabled": enabled(), "installed": bool(shutil.which("cloudflared")), **{k: _status[k] for k in ("url", "error", "running")}}


def _set_menu(url):
    if not telegram.chat_id():
        return
    button = {"type": "web_app", "text": "Opsboard", "web_app": {"url": url}} if url else {"type": "default"}
    try:
        telegram.call("setChatMenuButton", chat_id=telegram.chat_id(), menu_button=button)
    except telegram.TelegramError as exc:
        log.warning("webapp: menu button failed: %s", exc)


def _stop():
    p = _proc["p"]
    _proc["p"] = None
    if p and p.poll() is None:
        p.terminate()
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill()
    if _status["url"]:
        _set_menu("")
    with _lock:
        _sessions.clear()
    _status.update(url="", host="", running=False)


def _run_tunnel(port):
    binary = shutil.which("cloudflared") or "/opt/homebrew/bin/cloudflared"
    p = subprocess.Popen([binary, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    _proc["p"] = p
    for line in p.stderr:
        m = TUNNEL_URL.search(line)
        if m and not _status["url"]:
            url = m.group(0)
            _status.update(url=url, host=url.split("//", 1)[1], running=True, error="")
            log.info("webapp: tunnel at %s", url)
            _set_menu(url + "/")
    p.wait()


def loop(port):
    failures = 0
    while True:
        if enabled() and telegram.chat_id() and shutil.which("cloudflared"):
            try:
                _run_tunnel(port)
                failures = 0 if _status["running"] else failures + 1
            except OSError as exc:
                _status["error"] = str(exc)[:200]
                failures += 1
            was = _status["url"]
            _stop()
            if enabled():
                _status["error"] = _status["error"] or ("the tunnel stopped — restarting" if was else "could not open a tunnel")
                time.sleep(min(300, 5 * 2 ** min(failures, 6)))
            continue
        if not enabled():
            _status["error"] = ""
        elif not shutil.which("cloudflared"):
            _status["error"] = "cloudflared is not installed — brew install cloudflared"
        elif not telegram.chat_id():
            _status["error"] = "link Telegram first"
        time.sleep(5)


def watch():
    while True:
        time.sleep(3)
        if not enabled() and _proc["p"]:
            _stop()


def start(base, page_token, port):
    from http.server import ThreadingHTTPServer

    class Server(ThreadingHTTPServer):
        allow_reuse_address = True
        daemon_threads = True

    server = Server(("127.0.0.1", port), gateway_class(base, page_token))
    threading.Thread(target=server.serve_forever, daemon=True, name="webapp-gateway").start()
    threading.Thread(target=loop, args=(port,), daemon=True, name="webapp-tunnel").start()
    threading.Thread(target=watch, daemon=True, name="webapp-watch").start()
