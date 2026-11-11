import hashlib
import hmac
import json
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from urllib import error, request
from urllib.parse import urlencode

import config as cfg
import server
import webapp

TOKEN = "12345:" + "x" * 35


def signed(user_id, token=TOKEN, age=0, **extra):
    fields = {"auth_date": str(int(time.time() - age)), "query_id": "q1", "user": json.dumps({"id": user_id, "first_name": "J"}), **extra}
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(key, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


class InitDataTest(unittest.TestCase):
    def test_accepts_only_the_linked_user_with_a_fresh_signature(self):
        self.assertTrue(webapp.check_init_data(signed(111), TOKEN, 111))
        self.assertFalse(webapp.check_init_data(signed(222), TOKEN, 111))
        self.assertFalse(webapp.check_init_data(signed(111, token="999:" + "y" * 35), TOKEN, 111))
        self.assertFalse(webapp.check_init_data(signed(111, age=7200), TOKEN, 111))
        self.assertFalse(webapp.check_init_data(signed(111).replace("q1", "q2"), TOKEN, 111))
        self.assertFalse(webapp.check_init_data("", TOKEN, 111))

    def test_signature_field_is_accepted_either_way(self):
        self.assertTrue(webapp.check_init_data(signed(111, signature="abc"), TOKEN, 111))


class GatewayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.gateway_class(server.Handler, server.page_token))
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        cfg.set_secret("telegram.token", TOKEN)
        cfg.set("telegram.chat_id", "111", "user")
        cfg.set("telegram.webapp", True, "user")
        webapp._status.update(host="abc.trycloudflare.com", url="https://abc.trycloudflare.com")
        webapp._sessions.clear()
        webapp._auth_times.clear()

    def tearDown(self):
        for key in ("telegram.chat_id", "telegram.webapp"):
            cfg.set(key, None, "user")
        cfg.set_secret("telegram.token", "")
        webapp._status.update(host="", url="")

    def req(self, path, host="abc.trycloudflare.com", body=None, headers=None):
        r = request.Request(self.base + path, data=json.dumps(body).encode() if body is not None else None, headers={"Host": host, "Content-Type": "application/json", **(headers or {})})
        try:
            with request.urlopen(r, timeout=10) as resp:
                return resp.status, resp.headers, resp.read().decode()
        except error.HTTPError as exc:
            return exc.code, exc.headers, exc.read().decode()

    def test_everything_needs_a_session_and_the_tunnel_host(self):
        self.assertEqual(self.req("/api/state", host="127.0.0.1:8095")[0], 421)
        self.assertEqual(self.req("/api/state")[0], 401)
        self.assertEqual(self.req("/static/js/app.js")[0], 401)
        code, _, page = self.req("/")
        self.assertEqual(code, 200)
        self.assertIn("tgWebAppData", page)
        self.assertNotIn(server.page_token(), page)

    def test_signed_in_user_gets_the_app_but_not_tokens_or_settings(self):
        self.assertEqual(self.req("/tg/auth", body={"initData": signed(222)})[0], 403)
        code, headers, _ = self.req("/tg/auth", body={"initData": signed(111)})
        self.assertEqual(code, 200)
        cookie = headers["Set-Cookie"].split(";")[0]
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        auth = {"Cookie": cookie}
        self.assertEqual(self.req("/api/state", headers=auth)[0], 200)
        self.assertIn(server.page_token(), self.req("/", headers=auth)[2])
        ok = {**auth, "Origin": "https://abc.trycloudflare.com", "X-Ops-Token": server.page_token()}
        self.assertEqual(self.req("/api/settings", body={"key": "telegram.webapp", "value": False}, headers=ok)[0], 403)
        self.assertEqual(self.req("/api/telegram-account", body={}, headers=ok)[0], 403)
        self.assertEqual(self.req("/api/notifications", body={"action": "read", "ids": []}, headers={**ok, "Origin": "https://evil.example"})[0], 403)
        cfg.set("telegram.webapp", False, "user")
        self.assertEqual(self.req("/api/state", headers=auth)[0], 401)


if __name__ == "__main__":
    unittest.main()
