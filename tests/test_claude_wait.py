import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

import claudewait
import config as cfg
import telegram


class ClaudeWaitTest(unittest.TestCase):
    def setUp(self):
        claudewait._waiting.clear()
        claudewait.SESSIONS.mkdir(parents=True, exist_ok=True)
        self.tr = claudewait.SESSIONS / "t.jsonl"
        self.tr.write_text("x")
        (claudewait.SESSIONS / "1.json").write_text(json.dumps({"sessionId": "s1", "name": "fix bug", "entrypoint": "claude-vscode"}))
        for k in ("telegram.claude_wait", "telegram.claude_wait_minutes", "telegram.claude_wait_idle"):
            cfg.set(k, None, "user")

    def ev(self, kind="permission_prompt", sid="s1"):
        return {"session_id": sid, "cwd": "/p", "transcript_path": str(self.tr), "type": kind, "message": "Claude needs your permission to use Bash"}

    def test_alert_after_the_wait_when_nothing_happened(self):
        t0 = time.time()
        self.assertTrue(claudewait.report(self.ev()))
        sent = []
        self.assertEqual(claudewait.check(t0 + 30, sent.append), [])
        self.assertEqual(claudewait.check(t0 + 299, sent.append), [])
        out = claudewait.check(t0 + 301, sent.append)
        self.assertEqual(len(sent), 1)
        self.assertEqual((out[0]["name"], out[0]["kind"], out[0]["minutes"]), ("fix bug", "permission_prompt", 5))
        self.assertEqual(claudewait.check(t0 + 900, sent.append), [])

    def test_no_alert_when_the_user_answered(self):
        t0 = time.time()
        claudewait.report(self.ev())
        claudewait.check(t0 + 30)
        os.utime(self.tr, (t0 + 60, t0 + 60))
        self.assertEqual(claudewait.check(t0 + 400), [])
        self.assertEqual(claudewait.pending(), {})

    def test_idle_only_when_turned_on_and_gone_sessions_are_skipped(self):
        self.assertFalse(claudewait.report(self.ev("idle_prompt")))
        cfg.set("telegram.claude_wait_idle", True, "user")
        self.assertTrue(claudewait.report(self.ev("idle_prompt")))
        claudewait.report(self.ev(sid="gone"))
        t0 = time.time()
        claudewait.check(t0 + 30)
        out = claudewait.check(t0 + 400)
        self.assertEqual([o["sid"] for o in out], ["s1"])

    def test_turned_off(self):
        cfg.set("telegram.claude_wait", False, "user")
        claudewait.report(self.ev())
        self.assertEqual(claudewait.check(time.time() + 999), [])
        self.assertEqual(claudewait.pending(), {})

    def test_telegram_text(self):
        with mock.patch.object(telegram, "send") as send, mock.patch.object(telegram, "_bot_lang", return_value="uz"):
            telegram.claude_wait_alert({"kind": "question", "minutes": 6, "name": "fix bug", "cwd": "/p", "message": "Which branch?"})
        text = send.call_args[0][0]
        self.assertIn("Claude savol beryapti</b> — 6 daqiqadan beri", text)
        self.assertIn("<code>fix bug · /p</code>", text)
        self.assertIn("<i>Which branch?</i>", text)

    def test_held_permission_is_alerted_at_once_and_allowed_from_telegram(self):
        got = []
        with mock.patch.object(claudewait, "ON_NEW", got.append):
            req = claudewait.report(dict(self.ev("permission_request"), message="Bash: rm x"))
            for _ in range(50):
                if got:
                    break
                time.sleep(0.02)
        self.assertIsInstance(req, str)
        self.assertEqual((got[0]["req"], got[0]["minutes"], got[0]["name"]), (req, 0, "fix bug"))
        self.assertTrue(claudewait.report(self.ev("permission_prompt")))
        self.assertEqual(claudewait.pending()["s1"]["kind"], "permission_request")
        self.assertEqual(claudewait.poll(req), {"decision": None, "open": True})
        self.assertTrue(claudewait.decide(req, "allow"))
        self.assertEqual(claudewait.poll(req), {"decision": "allow", "answers": None})
        self.assertEqual(claudewait.poll(req), {"decision": None, "open": False})
        self.assertFalse(claudewait.decide(req, "deny"))

    def test_held_question_collects_answers(self):
        qs = [{"question": "Which branch?", "options": [{"label": "main"}, {"label": "dev"}]}, {"question": "Push?", "options": [{"label": "Yes"}]}]
        with mock.patch.object(claudewait, "ON_NEW", None):
            req = claudewait.report(dict(self.ev("question_request"), questions=qs))
        self.assertEqual(claudewait.answer(req, 0, "dev"), (False, mock.ANY))
        done, entry = claudewait.answer(req, 1, "no, wait")
        self.assertTrue(done)
        self.assertEqual(claudewait.poll(req), {"decision": "allow", "answers": {"Which branch?": "dev", "Push?": "no, wait"}})
        self.assertIsNone(claudewait.answer(req, 0, "x"))

    def test_answered_on_the_mac_closes_the_telegram_message(self):
        closed = []
        with mock.patch.object(claudewait, "ON_NEW", lambda item: None):
            req = claudewait.report(self.ev("permission_request"))
        t0 = time.time()
        claudewait.check(t0 + 30)
        os.utime(self.tr, (t0 + 60, t0 + 60))
        claudewait.check(t0 + 90, closed=closed.append)
        self.assertEqual([c["req"] for c in closed], [req])
        self.assertEqual(claudewait.poll(req), {"decision": None, "open": False})

    def test_telegram_buttons_and_reply(self):
        qs = [{"question": "Which branch?", "options": [{"label": "main", "description": "stable"}, {"label": "dev"}]}]
        with mock.patch.object(claudewait, "ON_NEW", None):
            req = claudewait.report(dict(self.ev("question_request"), questions=qs))
        item = dict(claudewait.pending()["s1"], sid="s1", name="fix bug", minutes=0)
        with mock.patch.object(telegram, "send", return_value={"message_id": 77}) as send, mock.patch.object(telegram, "_bot_lang", return_value="en"):
            telegram.claude_wait_alert(item)
            text, buttons = send.call_args[0][0], send.call_args[0][1]
            self.assertIn("❓ <b>Claude is asking a question</b>", text)
            self.assertIn("<b>Which branch?</b>", text)
            self.assertIn("• main — stable", text)
            self.assertEqual([r[0]["callback_data"] for r in buttons], [f"cq:{req}:0:0", f"cq:{req}:0:1"])
            with mock.patch.object(telegram, "edit") as edit, mock.patch.object(telegram, "react"):
                self.assertTrue(telegram._wait_reply({"message_id": 5, "text": "release branch", "reply_to_message": {"message_id": 77}}))
                self.assertIn("✅ Answer: release branch", edit.call_args[0][1])
        self.assertEqual(claudewait.poll(req)["answers"], {"Which branch?": "release branch"})
        with mock.patch.object(claudewait, "ON_NEW", None):
            req2 = claudewait.report(dict(self.ev("permission_request"), message="Bash: ls"))
        item = dict(claudewait.pending()["s1"], sid="s1", name="", minutes=0)
        with mock.patch.object(telegram, "send", return_value={"message_id": 78}) as send, mock.patch.object(telegram, "_bot_lang", return_value="en"):
            telegram.claude_wait_alert(item)
            self.assertEqual([b["callback_data"] for b in send.call_args[0][1][0]], [f"cq:{req2}:a".replace("cq", "cw"), f"cw:{req2}:d"])
            with mock.patch.object(telegram, "edit") as edit:
                self.assertEqual(telegram._wait_decide(req2, False), "")
                self.assertIn("❌ Denied from Telegram", edit.call_args[0][1])
        self.assertEqual(claudewait.poll(req2)["decision"], "deny")

    def test_hook_script_never_fails_and_never_prints(self):
        hook = Path(claudewait.__file__).resolve().parent / "hooks" / "claude-wait.py"
        env = dict(os.environ, OPS_PORT="9", OPS_TOKEN_FILE=str(claudewait.SESSIONS / "no-token"))
        for payload in ('{"hook_event_name":"Notification","notification_type":"permission_prompt"}', "not json", '{"hook_event_name":"PreToolUse","tool_name":"Bash"}'):
            r = subprocess.run([sys.executable, str(hook)], input=payload, capture_output=True, text=True, env=env, timeout=10)
            self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))


if __name__ == "__main__":
    unittest.main()
