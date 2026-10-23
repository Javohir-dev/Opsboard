import io
import json
import queue
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


class FakeClaude:
    instances = []

    def __init__(self, cmd, **kw):
        self.cmd, self.q, self.returncode, self.pid = cmd, queue.Queue(), None, 999999
        FakeClaude.instances.append(self)
        outer = self

        class In:
            def write(self, line):
                text = json.loads(line)["message"]["content"]
                outer.q.put(json.dumps({"type": "system", "subtype": "init", "session_id": "s1"}))
                outer.q.put(json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "/x/cart.py"}}]}}))
                outer.q.put(json.dumps({"type": "result", "result": f"echo **{text}**", "session_id": "s1"}))

            def flush(self):
                pass

            def close(self):
                outer.returncode = 0
                outer.q.put(None)

        self.stdin, self.stderr = In(), io.StringIO("")
        self.stdout = iter(self.q.get, None)

    def poll(self):
        return self.returncode


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

    def test_info_shows_accounts_but_no_secrets(self):
        self.link()
        cfg.set("gitlab.url", "https://gitlab.example", "user")
        cfg.set("gitlab.project", "team/app", "user")
        telegram.handle_message(message("/info"))
        text = self.texts()[-1]
        self.assertIn("linked to @javohir", text)
        self.assertIn("gitlab.example", text)
        self.assertIn("team/app", text)
        self.assertNotIn("x" * 35, text)
        self.assertNotIn("\n\n\n", text)

    def test_usage_from_live_state(self):
        self.link()
        cfg.set("claude.live_usage", True, "user")
        with lock:
            state["claude_usage"] = {
                "limits": [{"label": "Session (5hr)", "percent": 42, "severity": "normal", "resets_at": time.time() + 3600}],
                "fetched": time.time(),
                "account": {"email": "dev@example.com"},
                "source": "live",
                "live_error": "",
            }
        telegram.handle_message(message("/usage"))
        text = self.texts()[-1]
        self.assertIn("Session (5hr)</b> · 42%", text)
        self.assertIn("▰▰▰▰▱▱▱▱▱▱", text)
        self.assertRegex(text, r"resets in (59m|1\.0h)")
        self.assertNotIn("\n\n\n", text)
        self.assertIn("live", text)
        cfg.set("claude.live_usage", None, "user")

    def test_language_of_the_question(self):
        self.assertEqual(telegram.lang_of("nima o'zgardi?"), "uz")
        self.assertEqual(telegram.lang_of("MR larni tekshir"), "uz")
        cfg.set("telegram.language", "uz", "user")
        self.assertEqual(telegram.lang_of("what changed?"), "uz")
        cfg.set("telegram.language", None, "user")
        self.assertEqual(telegram.lang_of("что изменилось?"), "ru")
        self.assertEqual(telegram.lang_of("what changed?"), "en")

    def wait_for(self, needle, method="editMessageText", seconds=3):
        end = time.time() + seconds
        while time.time() < end:
            if any(m == method and needle in b.get("text", "") for m, b in list(SENT)):
                return True
            time.sleep(0.05)
        return False

    def test_claude_chat(self):
        self.link()
        telegram.handle_message(message("what changed in !7?"))
        self.assertIn("Claude chat is off", self.texts()[-1])
        cfg.set("telegram.claude_chat", True, "user")
        telegram._save_chat({})
        with mock.patch.object(telegram.subprocess, "Popen", FakeClaude), mock.patch.object(telegram.os, "killpg"):
            telegram.handle_message(dict(message("what changed?"), message_id=42))
            self.assertTrue(self.wait_for("echo <b>what changed?</b>"))
            react = [b for m, b in SENT if m == "setMessageReaction"]
            self.assertEqual((react[-1]["message_id"], react[-1]["reaction"]), (42, [{"type": "emoji", "emoji": "👀"}]))
            telegram.handle_message(message("and why?"))
            self.assertTrue(self.wait_for("echo <b>and why?</b>"))
            self.assertEqual(len(FakeClaude.instances), 1)
            cmd = FakeClaude.instances[0].cmd
            self.assertIn("--input-format", cmd)
            self.assertEqual(cmd[cmd.index("--permission-mode") + 1], "plan")
            self.assertEqual(telegram._load_chat()["session_id"], "s1")
            FakeClaude.instances[0].q.put(json.dumps({"type": "result", "result": "The other session answered.", "session_id": "s1"}))
            self.assertTrue(self.wait_for("Claude", method="sendMessage"))
            self.assertTrue(self.wait_for("The other session answered.", method="sendMessage"))
            telegram.handle_message(message("/new"))
            self.assertEqual(telegram._load_chat(), {})
        FakeClaude.instances[0].stdin.close()
        FakeClaude.instances.clear()
        telegram.CHAT.proc = None
        cfg.set("telegram.claude_chat", None, "user")

    def test_assigned_request_gets_a_link_instead_of_fix_buttons(self):
        self.link()
        with lock:
            state["review"]["mrs"].append({"iid": 8, "title": "Group column", "state": "opened", "url": "https://gl/x/-/merge_requests/8", "role": "assignee"})
        SENT.clear()
        with mock.patch.object(telegram, "THREAD_GROUP", 0.1):
            telegram.on_notify({"kind": "thread", "iid": 8, "author": "Bakhrom", "body": "x", "mr_title": "Group column", "status": "thread"})
            self.assertTrue(self.wait_for("sizga assign qilingan", method="sendMessage"))
        markup = [b for m, b in SENT if m == "sendMessage"][-1]["reply_markup"]["inline_keyboard"]
        self.assertEqual(markup, [[{"text": "Open in GitLab", "url": "https://gl/x/-/merge_requests/8"}]])

    def test_merged_message(self):
        self.link()
        SENT.clear()
        now = time.time()
        telegram.on_notify(
            {
                "kind": "merged",
                "iid": 7,
                "mr_title": "Fix totals",
                "url": "https://gl/x/-/merge_requests/7",
                "source": "feat/x",
                "target": "main",
                "merged_by": "Max",
                "created": now - 2 * 86400 - 4 * 3600,
                "merged_at": now,
                "threads_total": 3,
                "approved_by": ["Lena"],
            }
        )
        text = self.texts()[-1]
        self.assertIn("<b>!7</b>", text)
        self.assertIn("Fix totals", text)
        self.assertIn("<code>feat/x</code> → <code>main</code>", text)
        self.assertIn("<b>Max</b>", text)
        self.assertIn("2 kun 4 soat", text)
        self.assertIn("3 ta thread", text)
        self.assertEqual(SENT[-1][1]["reply_markup"]["inline_keyboard"][0][0]["url"], "https://gl/x/-/merge_requests/7")

    def test_new_threads_are_grouped_with_fix_buttons(self):
        telegram.on_notify({"kind": "thread", "iid": 7, "author": "Lena", "body": "why?", "mr_title": "Fix totals", "status": "thread"})
        time.sleep(0.1)
        self.assertEqual(SENT, [])
        self.link()
        SENT.clear()
        cfg.set("claude.fix_skill", "mr-fix", "user")
        with mock.patch.object(telegram, "THREAD_GROUP", 0.2):
            telegram.on_notify({"kind": "thread", "iid": 7, "author": "Lena", "body": "a", "mr_title": "Fix totals", "status": "thread"})
            telegram.on_notify({"kind": "thread", "iid": 7, "author": "Lena", "body": "b", "mr_title": "Fix totals", "status": "thread"})
            self.assertTrue(self.wait_for("2 ta thread ochdi", method="sendMessage"))
        sent = [b for m, b in SENT if m == "sendMessage"][-1]
        self.assertEqual(len([b for m, b in SENT if m == "sendMessage"]), 1)
        self.assertIn("<b>!7</b> — <b>Lena</b>", sent["text"])
        buttons = sent["reply_markup"]["inline_keyboard"][0]
        self.assertEqual([(b["text"], b["callback_data"]) for b in buttons], [("▶ mr-fix", "fix:7:"), ("⚡ mr-fix ultra", "fix:7:p")])
        runs_now = [{"id": "r9", "iid": 7, "status": "running"}]
        with mock.patch("runs.launch_fix") as launch, mock.patch("runs.load_runs", side_effect=[[], runs_now]):
            telegram.handle_callback({"id": "q", "data": "fix:7:p", "message": {"message_id": 1, "chat": {"id": 111}, "text": "x"}})
        launch.assert_called_once_with({"iid": 7, "threads": True, "conflict": True, "skiptests": False, "push": True})
        self.assertIn("mr-fix ultra ishga tushdi", self.texts()[-1])
        telegram.on_notify({"kind": "run", "run_id": "r9", "iid": 7, "status": "done", "outcome": {"status": "pushed", "commit": "abc1234", "threads": {"resolved": 2, "open": 0}}})
        self.assertIn("mr-fix ultra tugadi · pushed · abc1234 · 2/2 threads", self.texts()[-1])
        with mock.patch("runs.launch_fix") as launch, mock.patch("runs.load_runs", return_value=runs_now):
            telegram.handle_callback({"id": "q", "data": "fix:7:", "message": {"message_id": 1, "chat": {"id": 111}}})
            launch.assert_not_called()
        with mock.patch("runs.launch_fix") as launch:
            telegram.handle_callback({"id": "q", "data": "fix:7:", "message": {"message_id": 1, "chat": {"id": 999}}})
            launch.assert_not_called()
        cfg.set("claude.fix_skill", None, "user")

    def test_token_never_in_public_state(self):
        self.assertNotIn("x" * 35, json.dumps(telegram.public()))


if __name__ == "__main__":
    unittest.main()
