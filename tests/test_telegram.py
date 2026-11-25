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
        result = {"getMe": {"username": "test_bot"}, "sendMessage": {"message_id": len(SENT), "chat": {"id": body.get("chat_id")}}, "sendWidget": {"message_id": len(SENT)}}.get(method, True)
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
        patcher = mock.patch.object(telegram, "panelize", return_value=None)
        self.panelize = patcher.start()
        self.addCleanup(patcher.stop)
        topic = mock.patch.object(telegram, "haiku", return_value=None)
        self.haiku = topic.start()
        self.addCleanup(topic.stop)
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

    def test_widget_queries_go_to_handlers_from_the_linked_chat_only(self):
        self.link()
        seen = []
        telegram.WIDGET_HANDLERS.append(lambda q: seen.append(q["data"]) or "ok")
        try:
            telegram.handle_widget_query({"id": "w1", "chat": {"id": 222}, "data": "c"})
            telegram.handle_widget_query({"id": "w2", "chat": {"id": 111}, "data": "c"})
        finally:
            telegram.WIDGET_HANDLERS.clear()
        self.assertEqual(seen, ["c"])
        self.assertIn(("answerWidgetQuery", {"widget_query_id": "w2", "data": "ok"}), SENT)

    def test_reply_hook_takes_replies_before_commands_and_chat(self):
        self.link()
        SENT.clear()
        telegram.REPLY_HOOKS.append(lambda m: m["reply_to_message"]["message_id"] == 5)
        try:
            telegram.handle_message(dict(message("/mrs"), reply_to_message={"message_id": 5}))
            self.assertEqual(SENT, [])
            telegram.handle_message(dict(message("/mrs"), reply_to_message={"message_id": 6}))
        finally:
            telegram.REPLY_HOOKS.clear()
        self.assertIn("sendWidget", [m for m, _ in SENT])

    def test_mrs_widget_lists_labels_threads_and_working_agents(self):
        self.link()
        with lock:
            state["review"]["mrs"][0]["labels"] = ["pm:ok"]
            state["review"]["mrs"][0]["keys"] = ["AD-5"]
            state["review"]["labels"] = {"pm:ok": {"color": "#8FBC8F", "text": "#1F1E24"}}
            state["jira"] = {"issues": [{"key": "AD-5", "status": "Review"}]}
        telegram.MR_AGENTS.append(lambda m: {"who": "Dev Agent", "since": 100})
        try:
            data = json.loads(telegram.mrs_data())
        finally:
            telegram.MR_AGENTS.clear()
        self.assertEqual(data["b"], "https://gl/x/-/merge_requests/")
        self.assertEqual(data["l"][0], [7, "Fix totals", "success", 1, 3, 0, [["pm:ok", "8fbc8f", "1f1e24"]], "AD-5 · Review", "Dev Agent", 100, 0])

    def test_mrs_with_nothing_open_still_sends_the_widget_with_recent_merges(self):
        self.link()
        with lock:
            state["review"]["mrs"] = [dict(state["review"]["mrs"][0], iid=i, state="merged", merged=1000 + i) for i in range(1, 6)]
        data = json.loads(telegram.mrs_data())
        self.assertEqual((data["n"], data["l"], [r[0] for r in data["r"]]), (0, [], [5, 4, 3]))
        SENT.clear()
        telegram.handle_message(message("/mrs"))
        sent = next(b for m, b in SENT if m == "sendWidget")
        self.assertIn("No open requests", sent["caption"])
        self.assertIn("!5", telegram.cmd_mrs()[0])

    def test_mrs_widget_fits_and_takes_actions_only_on_its_own_message(self):
        self.link()
        with lock:
            state["review"]["mrs"] = [dict(state["review"]["mrs"][0], iid=i, title="Очень длинный заголовок " * 8) for i in range(1, 12)]
        self.assertLessEqual(len(telegram.mrs_data().encode()), 1024)
        SENT.clear()
        telegram.handle_message(message("/mrs"))
        mid = next(b for m, b in SENT if m == "sendWidget") and telegram._live_state()["mrs"]["mid"]
        with mock.patch.object(telegram, "_launch_fix", return_value=(None, "")) as launch:
            telegram.handle_widget_query({"id": "a", "chat": {"id": 111}, "message_id": mid + 1, "data": "f:3:p"})
            telegram.handle_widget_query({"id": "b", "chat": {"id": 111}, "message_id": mid, "data": "f:3:ps"})
            telegram.handle_widget_query({"id": "c", "chat": {"id": 111}, "message_id": mid, "data": "f:999:p"})
        launch.assert_called_once_with(3, True, True)
        answers = {b["widget_query_id"]: b.get("data") for m, b in SENT if m == "answerWidgetQuery"}
        self.assertEqual((answers["b"], answers["c"]), ("ok", "Unknown action"))

    def test_widget_send_and_silent_edit(self):
        self.link()
        SENT.clear()
        telegram.send_widget("<b>x</b>", "cap", chat_data="{}", notify=False)
        telegram.edit_widget(9, '{"s":1}')
        self.assertEqual([m for m, _ in SENT], ["sendWidget", "editMessageWidgetData"])
        self.assertTrue(SENT[0][1]["disable_notification"])
        self.assertEqual(SENT[1][1], {"chat_id": 111, "message_id": 9, "chat_data": '{"s":1}'})

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
        self.assertIn("sendWidget", [m for m, _ in SENT])

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
        widget = next(b for m, b in SENT if m == "sendWidget")
        self.assertEqual(widget["caption"], "<b>Claude usage</b> · Session 42%")
        data = json.loads(widget["chat_data"])
        self.assertEqual((data["e"], data["s"], data["l"][0][:2]), ("dev@example.com", "live", ["Session (5hr)", 42]))
        text = telegram.cmd_usage()[0]
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

    def test_md_to_html_bullets_and_collapsed_details(self):
        out = telegram.md_to_html("**✅ Hammasi ishlayapti**\n- 6 ta issue ishda\n\n> Daemon: v0.12.1\n> ISS-5252 <ci>\nend")
        self.assertEqual(out, "<b>✅ Hammasi ishlayapti</b>\n• 6 ta issue ishda\n\n<blockquote expandable>Daemon: v0.12.1\nISS-5252 &lt;ci&gt;</blockquote>\nend")

    def test_answers_arrive_as_a_panel_with_a_details_button(self):
        panel, details = telegram.split_panel("🔴 Qotgan · 3\n🟢 Daemon · 4 soat\n---\n- `ISS-4805` 24.11 dan beri")
        self.assertEqual((panel, details), ("🔴 Qotgan · 3\n🟢 Daemon · 4 soat", "- `ISS-4805` 24.11 dan beri"))
        long = "Multica'da hozir ham jiddiy nosozlik yo'q, lekin bir nechta issue uzoq vaqt qimirlamagan holatda turibdi."
        panel, details = telegram.split_panel(long + "\n- a")
        self.assertTrue(panel.splitlines()[0].endswith("…") and len(panel.splitlines()[0]) == 60)
        self.assertEqual(details, long + "\n- a")
        self.assertEqual(telegram.split_panel("🟢 Hammasi joyida"), ("🟢 Hammasi joyida", ""))
        self.link()
        SENT.clear()
        telegram.deliver_panel("🔴 Qotgan · 3\n---\n- `ISS-4805`", None, "uz")
        sent = [b for m, b in SENT if m == "sendMessage"][-1]
        self.assertEqual(sent["text"], "🔴 Qotgan · 3")
        button = sent["reply_markup"]["inline_keyboard"][0][0]
        self.assertEqual(button["text"], "📄 Batafsil")
        telegram.handle_callback({"id": "q", "data": button["callback_data"], "message": {"message_id": 9, "chat": {"id": 111}}})
        self.assertIn("<code>ISS-4805</code>", [b for m, b in SENT if m == "sendMessage"][-1]["text"])
        self.assertIn(("editMessageReplyMarkup", {"chat_id": 111, "message_id": 9, "reply_markup": {"inline_keyboard": []}}), SENT)
        self.panelize.return_value = "🟢 Daemon · ishlayapti\n🔴 Qotgan · 3"
        telegram.deliver_panel("Multica ishlayapti, nosozlik ko'rinmayapti. Agentlar va autopilotlar holati.", None, "uz")
        sent = [b for m, b in SENT if m == "sendMessage"][-1]
        self.assertEqual(sent["text"], "🟢 Daemon · ishlayapti\n\n🔴 Qotgan · 3")
        self.assertIn("📄 Batafsil", sent["reply_markup"]["inline_keyboard"][0][0]["text"])
        self.assertTrue(telegram.is_panel("🟢 a\n👉 b"))
        self.assertFalse(telegram.is_panel("Multica ishlayapti"))

    def test_claude_chat(self):
        self.link()
        self.assertTrue(cfg.get("telegram.claude_chat"))
        cfg.set("telegram.claude_chat", False, "user")
        telegram.handle_message(message("what changed in !7?"))
        self.assertIn("Claude chat is off", self.texts()[-1])
        cfg.set("telegram.claude_chat", None, "user")
        telegram._save_chat({})
        telegram._notes.clear()
        telegram.CHAT.seen = time.time()
        with mock.patch.object(telegram.subprocess, "Popen", FakeClaude), mock.patch.object(telegram.os, "killpg"):
            telegram.handle_message(dict(message("what changed?"), message_id=42))
            self.assertTrue(self.wait_for("echo <b>what changed?</b>"))
            react = [b for m, b in SENT if m == "setMessageReaction"]
            self.assertEqual((react[-1]["message_id"], react[-1]["reaction"]), (42, [{"type": "emoji", "emoji": "👀"}]))
            telegram.handle_message(message("and why?"))
            self.assertTrue(self.wait_for("echo <b>and why?</b>"))
            telegram._remember("⏳ <b>Claude ruxsat so'rayapti</b> — 5 daqiqadan beri javob yo'q")
            telegram.handle_message(dict(message("ruxsat beraman"), reply_to_message={"message_id": 3, "text": "⏳ Claude ruxsat so'rayapti"}))
            self.assertTrue(self.wait_for("[Opsboard notifications since your last turn]"))
            last = self.texts()[-1]
            self.assertIn("Claude ruxsat so&#x27;rayapti — 5 daqiqadan", last)
            self.assertIn("[He replied to]", last)
            self.assertIn("ruxsat beraman", last)
            telegram.handle_message(message("ok"))
            self.assertTrue(self.wait_for("echo <b>ok</b>"))
            self.assertEqual(len(FakeClaude.instances), 1)
            cmd = FakeClaude.instances[0].cmd
            self.assertIn("--append-system-prompt", cmd)
            self.assertNotIn("--resume", cmd)
            self.assertIn("--input-format", cmd)
            self.assertEqual(cmd[cmd.index("--permission-mode") + 1], "plan")
            self.assertEqual(telegram._load_chat()["session_id"], "s1")
            FakeClaude.instances[0].q.put(json.dumps({"type": "result", "result": "The other session answered.", "session_id": "s1"}))
            self.assertTrue(self.wait_for("Claude", method="sendMessage"))
            self.assertTrue(self.wait_for("The other session answered.", method="sendMessage"))
            self.assertTrue(telegram._load_chat().get("last"))
            self.assertEqual(telegram.CHAT.prev[0], "ok")
            telegram.CHAT.last = time.time() - 300
            self.haiku.return_value = "NEW"
            telegram.handle_message(message("jirada nima gap?"))
            self.assertTrue(self.wait_for("echo <b>jirada nima gap?</b>"))
            self.assertEqual(len(FakeClaude.instances), 2)
            self.assertIn("PREVIOUS USER: ok", self.haiku.call_args[0][0])
            self.haiku.return_value = "SAME"
            telegram.CHAT.last = time.time() - 300
            telegram.handle_message(message("va keyin?"))
            self.assertTrue(self.wait_for("echo <b>va keyin?</b>"))
            self.assertEqual(len(FakeClaude.instances), 2)
            telegram.handle_message(message("/new"))
            self.assertEqual(telegram._load_chat(), {})
        for inst in FakeClaude.instances:
            inst.stdin.close()
        FakeClaude.instances.clear()
        telegram.CHAT.proc = None
        cfg.set("telegram.claude_chat", None, "user")

    def test_assigned_request_gets_fix_buttons_too(self):
        self.link()
        cfg.set("claude.fix_skill", "mr-fix", "user")
        with lock:
            state["review"]["mrs"].append({"iid": 8, "title": "Group column", "state": "opened", "url": "https://gl/x/-/merge_requests/8", "role": "assignee"})
        SENT.clear()
        with mock.patch.object(telegram, "THREAD_GROUP", 0.1):
            telegram.on_notify({"kind": "thread", "iid": 8, "author": "Bakhrom", "body": "x", "mr_title": "Group column", "status": "thread"})
            self.assertTrue(self.wait_for("sizga assign qilingan", method="sendMessage"))
        markup = [b for m, b in SENT if m == "sendMessage"][-1]["reply_markup"]["inline_keyboard"][0]
        self.assertEqual([b["callback_data"] for b in markup], ["fix:8:p", "fix:8:ps"])
        cfg.set("claude.fix_skill", None, "user")

    def test_ultra_skip_button_runs_without_tests_and_pushes(self):
        self.link()
        with mock.patch("runs.launch_fix") as launch, mock.patch("runs.load_runs", return_value=[]):
            telegram.handle_callback({"id": "q", "data": "fix:7:ps", "message": {"message_id": 3, "chat": {"id": 111}, "text": "x"}})
        launch.assert_called_once_with({"iid": 7, "threads": True, "conflict": True, "skiptests": True, "push": True, "source": "telegram"})
        self.assertIn("ultra-skip ishga tushdi", self.texts()[-1])

    def test_battery_message(self):
        self.link()
        SENT.clear()
        telegram.on_notify({"kind": "battery", "level": 14, "minutes": 25})
        self.assertIn("Batareya 14% qoldi", self.texts()[-1])
        self.assertIn("taxminan <b>25 daqiqa</b>ga yetadi", self.texts()[-1])

    def test_emoji_number(self):
        self.assertEqual(telegram.emoji_number(12), "1️⃣2️⃣")

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
            self.assertTrue(self.wait_for("2️⃣ ta thread ochdi", method="sendMessage"))
        sent = [b for m, b in SENT if m == "sendMessage"][-1]
        self.assertEqual(len([b for m, b in SENT if m == "sendMessage"]), 1)
        self.assertIn("<b>!7</b> — <b>Lena</b>", sent["text"])
        buttons = sent["reply_markup"]["inline_keyboard"][0]
        self.assertEqual([(b["text"], b["callback_data"]) for b in buttons], [("⚡ mr-fix ultra", "fix:7:p"), ("🚀 mr-fix ultra-skip", "fix:7:ps")])
        runs_now = [{"id": "r9", "iid": 7, "status": "running"}]
        with mock.patch("runs.launch_fix") as launch, mock.patch("runs.load_runs", side_effect=[[], runs_now]):
            telegram.handle_callback({"id": "q", "data": "fix:7:p", "message": {"message_id": 1, "chat": {"id": 111}, "text": "x"}})
        launch.assert_called_once_with({"iid": 7, "threads": True, "conflict": True, "skiptests": False, "push": True, "source": "telegram"})
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

    def test_fix_started_from_opsboard_replies_under_the_thread_message_and_drops_its_buttons(self):
        self.link()
        SENT.clear()
        cfg.set("claude.fix_skill", "mr-fix", "user")
        with mock.patch.object(telegram, "THREAD_GROUP", 0.05):
            telegram.on_notify({"kind": "thread", "iid": 8, "author": "Lena", "body": "a", "mr_title": "T", "status": "thread"})
            self.assertTrue(self.wait_for("thread ochdi", method="sendMessage"))
        mid = [b for m, b in SENT if m == "sendMessage"][-1] and telegram._thread_msgs[8]
        telegram.on_notify({"kind": "run_started", "run_id": "r1", "iid": 8, "push": True, "skiptests": False, "source": "dashboard"})
        self.assertIn(("editMessageReplyMarkup", {"chat_id": 111, "message_id": mid, "reply_markup": {"inline_keyboard": []}}), SENT)
        reply = [b for m, b in SENT if m == "sendMessage"][-1]
        self.assertIn("mr-fix ultra ishga tushdi", reply["text"])
        self.assertEqual(reply["reply_parameters"]["message_id"], mid)
        telegram.on_notify({"kind": "run", "run_id": "r1", "iid": 8, "status": "done", "outcome": {"status": "pushed", "commit": "abc1234", "threads": {"replied": 3, "open": 0}}})
        done = [b for m, b in SENT if m == "sendMessage"][-1]
        self.assertIn("mr-fix ultra tugadi · pushed · abc1234 · 3 replied, 0 open", done["text"])
        self.assertEqual(done["reply_parameters"]["message_id"], mid)
        n = len(SENT)
        telegram.on_notify({"kind": "run_started", "run_id": "r2", "iid": 8, "push": True, "source": "telegram"})
        telegram.on_notify({"kind": "run_started", "run_id": "r3", "iid": 99, "push": True, "source": "dashboard"})
        self.assertEqual(len(SENT), n)
        cfg.set("claude.fix_skill", None, "user")

    def test_switch_proposal_buttons_decide_and_the_message_shows_the_result(self):
        import claudeaccounts

        cfg.set("telegram.chat_id", "111", "user")
        claudeaccounts._proposal.update(pid="p1", src="main", dst="main", level=91, to_level=10, at=time.time(), msg=None)
        cfg.set("telegram.language", "en", "user")
        telegram.on_notify({"kind": "claude_propose", "pid": "p1", "from": "work@x.uz", "to": "spare@x.uz", "level": 91, "to_level": 10, "src_w": {"five_hour": [91, 0], "seven_day": [40, 0]}, "dst_w": {"five_hour": [10, 0]}})
        sent = [b for m, b in SENT if m == "sendMessage"][-1]
        self.assertIn("Switch Claude account?", sent["text"])
        self.assertIn("work passed 91%", sent["text"])
        self.assertIn("🟧 █████████░  91%", sent["text"])
        self.assertIn("<code>spare@x.uz</code>", sent["text"])
        rows = sent["reply_markup"]["inline_keyboard"]
        self.assertEqual([(r[0]["text"], r[0]["callback_data"]) for r in rows], [("✅ Switch to spare", "cacc:y:p1"), ("✖ Stay", "cacc:n:p1")])
        self.assertTrue(claudeaccounts._proposal.get("msg"))
        telegram.handle_callback({"id": "q", "data": "cacc:n:p1", "message": {"message_id": 5, "chat": {"id": 999}}})
        self.assertEqual(claudeaccounts._proposal.get("pid"), "p1")
        with mock.patch("claudeaccounts.switch") as sw:
            telegram.handle_callback({"id": "q", "data": "cacc:n:p1", "message": {"message_id": 5, "chat": {"id": 111}}})
            sw.assert_not_called()
        self.assertEqual(claudeaccounts._proposal, {})
        self.assertGreater(claudeaccounts._snooze["until"], time.time())
        claudeaccounts._snooze["until"] = 0
        time.sleep(0.3)
        self.assertIn("Stayed</b> on", [b for m, b in SENT if m == "editMessageText"][-1]["text"])
        cfg.set("telegram.language", None, "user")

    def test_token_never_in_public_state(self):
        self.assertNotIn("x" * 35, json.dumps(telegram.public()))


if __name__ == "__main__":
    unittest.main()
