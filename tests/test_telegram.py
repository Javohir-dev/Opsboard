import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

import config as cfg
import telegram
from core import lock, state

SENT = []


class FakeTelegram(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        method = self.path.rsplit("/", 1)[-1]
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        SENT.append((method, body))
        result = {"getMe": {"username": "test_bot"}, "sendMessage": {"message_id": len(SENT), "chat": {"id": body.get("chat_id")}}}.get(method, True)
        raw = json.dumps({"ok": True, "result": result}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(raw)


def message(text, chat=111, kind="private"):
    return {"chat": {"id": chat, "type": kind}, "from": {"username": "javohir"}, "text": text, "date": int(time.time())}


class TelegramTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeTelegram)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.api = mock.patch.object(telegram, "API", f"http://127.0.0.1:{cls.server.server_port}")
        cls.api.start()

    @classmethod
    def tearDownClass(cls):
        cls.api.stop()
        cls.server.shutdown()

    def setUp(self):
        SENT.clear()
        cfg.set_secret("telegram.token", "12345:" + "x" * 35)
        for key in ("telegram.chat_id", "telegram.user", "telegram.claude_chat"):
            cfg.set(key, None, "user")
        telegram._pair.update(code="", until=0)
        with lock:
            state["review"] = {
                "mrs": [
                    {
                        "iid": 7,
                        "title": "Fix totals",
                        "state": "opened",
                        "url": "https://gl/x/-/merge_requests/7",
                        "source": "f",
                        "target": "main",
                        "threads": 1,
                        "threads_total": 3,
                        "pipeline": "success",
                        "approved": False,
                        "approved_by": [],
                        "conflicts": False,
                    }
                ]
            }

    def tearDown(self):
        cfg.set_secret("telegram.token", "")

    def link(self):
        code = telegram.pair_code()
        telegram.handle_message(message(f"/start {code}"))

    def texts(self):
        return [b.get("text", "") for m, b in SENT if m in ("sendMessage", "editMessageText")]

    def test_pairing_needs_the_code(self):
        telegram.pair_code()
        telegram.handle_message(message("/start wrong"))
        self.assertIsNone(telegram.chat_id())
        self.link()
        self.assertEqual((telegram.chat_id(), cfg.get("telegram.user")), (111, "javohir"))
        self.assertIn("Linked", self.texts()[-1])

    def test_other_chats_and_groups_are_ignored(self):
        self.link()
        SENT.clear()
        telegram.handle_message(message("/mrs", chat=222))
        telegram.handle_message(message("/mrs", kind="group"))
        self.assertEqual(SENT, [])
        telegram.handle_message(message("/mrs"))
        self.assertIn("!7", self.texts()[-1])

    def test_sessions_show_working_ones_with_agents(self):
        self.link()
        with lock:
            state["sessions"] = [
                {
                    "title": "Fix cart",
                    "cwd": "/x/shop",
                    "status": "busy",
                    "status_since": time.time() - 90,
                    "agents": [{"status": "running", "description": "review diff"}, {"status": "completed"}],
                    "jobs": [],
                    "doing": {"tool": "Bash", "what": "pytest"},
                },
                {"title": "Idle one", "cwd": "/x/shop", "status": "idle", "agents": [], "jobs": []},
            ]
        telegram.handle_message(message("/sessions"))
        text = self.texts()[-1]
        self.assertIn("1 working · 1 idle", text)
        self.assertIn("1 agent running", text)
        self.assertIn("review diff", text)
        self.assertNotIn("Idle one", text)

    def test_claude_chat(self):
        self.link()
        telegram.handle_message(message("what changed in !7?"))
        self.assertIn("Claude chat is off", self.texts()[-1])
        cfg.set("telegram.claude_chat", True, "user")
        telegram._save_chat({})
        calls = []

        class Proc:
            pid = 1
            returncode = 0

            def __init__(self, cmd, **kw):
                calls.append(cmd)

            def communicate(self, timeout=None):
                return json.dumps({"result": "It **rounds** totals.", "session_id": "s1"}), ""

        with mock.patch.object(telegram.subprocess, "Popen", Proc):
            telegram._run_claude("what changed?")
            telegram._run_claude("and why?")
        self.assertNotIn("--resume", calls[0])
        self.assertEqual(calls[1][calls[1].index("--resume") + 1], "s1")
        self.assertEqual(calls[0][calls[0].index("--permission-mode") + 1], "plan")
        self.assertIn("It <b>rounds</b> totals.", self.texts()[-1])
        telegram.handle_message(message("/new"))
        self.assertEqual(telegram._load_chat(), {})
        cfg.set("telegram.claude_chat", None, "user")

    def test_notifications_go_to_the_linked_chat(self):
        telegram.on_notify({"kind": "thread", "iid": 7, "author": "Lena", "body": "why?", "path": "a.py", "line": 3, "mr_title": "Fix totals", "status": "thread"})
        self.assertEqual(SENT, [])
        self.link()
        SENT.clear()
        telegram.on_notify({"kind": "thread", "iid": 7, "author": "Lena", "body": "why?", "path": "a.py", "line": 3, "mr_title": "Fix totals", "status": "thread"})
        self.assertIn("New thread · !7</b> · <code>a.py:3</code>", self.texts()[-1])
        SENT.clear()
        telegram.on_notify({"kind": "run", "run_id": "r1", "iid": 7, "status": "done"})
        self.assertEqual(SENT, [])
        cfg.set("telegram.notify", False, "user")
        SENT.clear()
        telegram.on_notify({"kind": "thread", "iid": 7, "author": "Lena", "body": "b", "status": "thread"})
        self.assertEqual(SENT, [])
        cfg.set("telegram.notify", None, "user")

    def test_token_never_in_public_state(self):
        self.assertNotIn("x" * 35, json.dumps(telegram.public()))


if __name__ == "__main__":
    unittest.main()
