import json
import os
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import claudeusage
import config as cfg
import core
import system

SEEN = []
REPLY = {"code": 200}


class FakeAnthropic(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        SEEN.append((self.path, self.headers.get("Authorization"), self.headers.get("anthropic-beta")))
        if REPLY["code"] != 200:
            self.send_response(REPLY["code"])
            self.end_headers()
            return
        raw = json.dumps({"limits": [{"kind": "session", "percent": 57, "severity": "normal", "resets_at": "2099-01-01T00:00:00+00:00"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class LiveUsageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeAnthropic)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        claudeusage.API = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        data = Path(os.environ["OPS_DATA_DIR"])
        self.creds = data / "credentials.json"
        self.saved = (claudeusage.CREDENTIALS_FILE, system.CLAUDE_STATE, os.environ["OPS_CLAUDE_CREDENTIALS"])
        claudeusage.CREDENTIALS_FILE = self.creds
        os.environ["OPS_CLAUDE_CREDENTIALS"] = str(self.creds)
        system.CLAUDE_STATE = data / "claude.json"
        system.CLAUDE_STATE.write_text(json.dumps({"cachedUsageUtilization": {"fetchedAtMs": 1000, "utilization": {"limits": [{"kind": "session", "percent": 1}]}}}))
        cfg.save(cfg._empty())
        claudeusage.reset()
        SEEN.clear()
        REPLY["code"] = 200

    def tearDown(self):
        claudeusage.CREDENTIALS_FILE, system.CLAUDE_STATE, os.environ["OPS_CLAUDE_CREDENTIALS"] = self.saved
        claudeusage.reset()

    def write_token(self, expires_in):
        self.creds.write_text(json.dumps({"claudeAiOauth": {"accessToken": "test-oauth-token", "expiresAt": (time.time() + expires_in) * 1000}}))

    def test_switched_off_shows_no_limits(self):
        self.write_token(3600)
        cfg.set("claude.live_usage", False, "user")
        system.collect_claude_usage()
        self.assertEqual(core.state["claude_usage"], {})
        self.assertEqual(SEEN, [])

    def test_live_by_default(self):
        self.write_token(3600)
        cfg.set("claude.live_usage", None, "user")
        system.collect_claude_usage()
        usage = core.state["claude_usage"]
        self.assertEqual((usage["source"], usage["limits"][0]["percent"]), ("live", 57))
        self.assertEqual(SEEN, [("/api/oauth/usage?cedar_ember=1", "Bearer test-oauth-token", "oauth-2025-04-20")])
        self.assertNotIn("test-oauth-token", json.dumps(core.state))

    def test_asks_at_most_once_a_minute(self):
        self.write_token(3600)
        cfg.set("claude.live_usage", True, "user")
        system.collect_claude_usage()
        system.collect_claude_usage()
        self.assertEqual(len(SEEN), 1)
        self.assertEqual(core.state["claude_usage"]["source"], "live")

    def test_expired_sign_in_is_not_renewed_and_falls_back(self):
        self.write_token(-10)
        cfg.set("claude.live_usage", True, "user")
        system.collect_claude_usage()
        usage = core.state["claude_usage"]
        self.assertEqual(usage["source"], "cache")
        self.assertIn("expired", usage["live_error"])
        self.assertEqual(SEEN, [])

    def test_rejected_token_falls_back(self):
        self.write_token(3600)
        REPLY["code"] = 401
        cfg.set("claude.live_usage", True, "user")
        system.collect_claude_usage()
        usage = core.state["claude_usage"]
        self.assertEqual(usage["source"], "cache")
        self.assertIn("401", usage["live_error"])


if __name__ == "__main__":
    unittest.main()
