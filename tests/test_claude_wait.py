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

    def test_hook_script_never_fails_and_never_prints(self):
        hook = Path(claudewait.__file__).resolve().parent / "hooks" / "claude-wait.py"
        env = dict(os.environ, OPS_PORT="9", OPS_TOKEN_FILE=str(claudewait.SESSIONS / "no-token"))
        for payload in ('{"hook_event_name":"Notification","notification_type":"permission_prompt"}', "not json", '{"hook_event_name":"PreToolUse","tool_name":"Bash"}'):
            r = subprocess.run([sys.executable, str(hook)], input=payload, capture_output=True, text=True, env=env, timeout=10)
            self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))


if __name__ == "__main__":
    unittest.main()
