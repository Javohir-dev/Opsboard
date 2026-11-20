import json
import shutil
import time
import unittest
from pathlib import Path
from unittest import mock

import claudeaccounts as ca
import claudelogins as logins
import config as cfg
import notify
from core import DATA, lock, state

PEOPLE = {
    "at-ann": {"uuid": "u-ann", "email": "ann@x.uz", "plan": "Claude Team"},
    "at-ann-2": {"uuid": "u-ann", "email": "ann@x.uz", "plan": "Claude Team"},
    "at-bob": {"uuid": "u-bob", "email": "bob@x.uz", "plan": "Claude Team"},
}


def oauth(name, token=None):
    return {"accessToken": token or f"at-{name}", "refreshToken": f"rt-{name}", "expiresAt": (time.time() + 3600) * 1000, "scopes": ["user:inference", "user:profile"]}


class ClaudeLoginsTest(unittest.TestCase):
    def setUp(self):
        self.identity = mock.patch.object(logins, "identity", side_effect=lambda t: PEOPLE.get(t))
        self.identity.start()
        self.probe = mock.patch.object(ca, "probe", side_effect=lambda aid: {"windows": {"five_hour": {"percent": 5, "resets_at": 0}}, "at": time.time()})
        self.probe.start()
        logins.main_file().write_text(json.dumps({"claudeAiOauth": oauth("ann"), "mcpOAuth": {"keep": "me"}}))
        logins.main_json().write_text(json.dumps({"userID": "x", "oauthAccount": {"accountUuid": "u-ann", "emailAddress": "ann@x.uz"}}))
        ca.SETTINGS.write_text(json.dumps({"model": "opus"}))
        for d in (ca._usage, ca._synced, ca._pending, ca._proposal):
            d.clear()
        ca._main["uuid"] = None
        with lock:
            state["sessions"], state["runs"], state["claude_usage"] = [], [], {}
        notify.clear()

    def tearDown(self):
        self.identity.stop()
        self.probe.stop()
        for a in ca.accounts():
            cfg.set_secret(ca.secret_key(a["id"]), "")
        for key in ("claude.accounts", "claude.disabled"):
            cfg.set(key, None, "user")
        for key in ("claude.main_twin", "claude.main_twin_login"):
            cfg.set(key, None, "auto")
        shutil.rmtree(logins.SLOTS, ignore_errors=True)
        logins.main_file().unlink(missing_ok=True)
        logins.main_json().unlink(missing_ok=True)
        ca._main["uuid"] = None

    def sign_in(self, name, email="", aid=None):
        started = ca.login_begin(email, aid, terminal=False)
        slot = started["pid"]
        self.assertIn(str(logins.slot_dir(slot)), started["command"])
        self.assertEqual(ca.login_poll(), [])
        logins.write(slot, {"claudeAiOauth": oauth(name)})
        (logins.slot_dir(slot) / ".claude.json").write_text(json.dumps({"oauthAccount": {"accountUuid": f"u-{name}", "emailAddress": f"{name}@x.uz"}}))
        return ca.login_poll()[0]

    def test_the_account_claude_code_is_signed_in_to_is_listed_and_kept_in_its_slot(self):
        ann = ca.sync_login()
        self.assertEqual([(a["label"], a["uuid"]) for a in ca.accounts()], [("ann@x.uz", "u-ann")])
        self.assertEqual(ca.active_id(), ann)
        self.assertEqual(ca.pool(), [ann])
        self.assertEqual(logins.oauth(ann)["refreshToken"], "rt-ann")
        row = ca.public()["accounts"][0]
        self.assertEqual((row["kind"], row["login"], row["plan"], row["masked"]), ("login", True, "Claude Team", ""))
        logins.put_oauth(None, oauth("ann", "at-ann-2") | {"refreshToken": "rt-ann-rotated"})
        self.assertEqual(ca.sync_login(), ann)
        self.assertEqual(logins.oauth(ann)["refreshToken"], "rt-ann-rotated")
        self.assertEqual(len(ca.accounts()), 1)
        self.assertNotIn("rt-ann", json.dumps(ca.public()))

    def test_a_setup_token_account_with_the_login_email_becomes_the_signed_in_one(self):
        cfg.set("claude.accounts", [{"id": "aaaa1111", "label": "Ann@x.uz"}], "user")
        self.assertEqual(ca.sync_login(), "aaaa1111")
        self.assertEqual(len(ca.accounts()), 1)
        self.assertTrue(ca.signed_in("aaaa1111"))

    def test_switching_swaps_only_the_sign_in_and_saves_the_one_it_replaces(self):
        ann = ca.sync_login()
        bob = self.sign_in("bob", "bob@x.uz")
        self.assertEqual([a["label"] for a in ca.accounts()], ["ann@x.uz", "bob@x.uz"])
        self.assertEqual(ca.active_id(), ann)
        ca.SETTINGS.write_text(json.dumps({"model": "opus", "env": {ca.ENV_KEY: "sk-ant-oat01-" + "q" * 40, "KEEP": "1"}}))
        logins.put_oauth(None, oauth("ann", "at-ann-2") | {"refreshToken": "rt-ann-latest"})
        ca.switch(bob)
        main = json.loads(logins.main_file().read_text())
        self.assertEqual(main["claudeAiOauth"]["refreshToken"], "rt-bob")
        self.assertEqual(main["mcpOAuth"], {"keep": "me"})
        self.assertEqual(logins.oauth(ann)["refreshToken"], "rt-ann-latest")
        state_file = json.loads(logins.main_json().read_text())
        self.assertEqual((state_file["oauthAccount"]["accountUuid"], state_file["userID"]), ("u-bob", "x"))
        self.assertEqual(json.loads(ca.SETTINGS.read_text()), {"model": "opus", "env": {"KEEP": "1"}})
        self.assertEqual(ca.active_id(), bob)
        self.assertEqual(ca.sync_login(), bob)
        ca.switch(ann)
        self.assertEqual(logins.oauth()["refreshToken"], "rt-ann-latest")
        self.assertEqual(logins.oauth(bob)["refreshToken"], "rt-bob")
        self.assertEqual(ca.active_id(), ann)

    def test_signing_in_again_to_a_known_account_or_for_a_token_account(self):
        ca.sync_login()
        bob = self.sign_in("bob")
        self.assertEqual(self.sign_in("bob"), bob)
        self.assertEqual(len(ca.accounts()), 2)
        cfg.set("claude.accounts", ca.accounts() + [{"id": "cccc3333", "label": "Spare"}], "user")
        PEOPLE["at-cy"] = {"uuid": "u-cy", "email": "cy@x.uz", "plan": ""}
        self.assertEqual(self.sign_in("cy", aid="cccc3333"), "cccc3333")
        self.assertEqual(ca.label("cccc3333"), "Spare")
        self.assertEqual(logins.oauth("cccc3333")["refreshToken"], "rt-cy")
        self.assertEqual(sorted(p.name for p in logins.SLOTS.iterdir()), sorted(a["id"] for a in ca.accounts()))

    def test_nothing_is_overwritten_when_it_cannot_be_saved_first(self):
        ann = ca.sync_login()
        cfg.set("claude.accounts", ca.accounts() + [{"id": "dddd4444", "label": "Ghost", "uuid": "u-ghost"}], "user")
        with self.assertRaises(ValueError):
            ca.switch("dddd4444")
        self.assertEqual(logins.oauth()["refreshToken"], "rt-ann")
        bob = self.sign_in("bob")
        logins.main_file().write_text(json.dumps({"claudeAiOauth": oauth("stranger")}))
        logins.main_json().write_text("{}")
        ca._main["uuid"] = None
        with self.assertRaises(ValueError):
            ca.switch(bob)
        self.assertEqual(logins.oauth()["refreshToken"], "rt-stranger")
        self.assertEqual(logins.oauth(ann)["refreshToken"], "rt-ann")

    def test_remove_keeps_the_one_claude_code_uses_and_forgets_another(self):
        ann = ca.sync_login()
        bob = self.sign_in("bob")
        with self.assertRaises(ValueError):
            ca.remove(ann)
        ca.remove(bob)
        self.assertFalse(logins.slot_dir(bob).exists())
        self.assertEqual([a["id"] for a in ca.accounts()], [ann])

    def test_keychain_names_match_claude_code(self):
        self.assertEqual(logins.service(), "Claude Code-credentials")
        self.assertRegex(logins.service("abcd1234"), r"^Claude Code-credentials-[0-9a-f]{8}$")
        self.assertNotEqual(logins.service("abcd1234"), logins.service("abcd1235"))


if __name__ == "__main__":
    unittest.main()


GRANTS = {
    "cedar_ember": {
        "eligible": True,
        "grants": [
            {"id": "full-1", "label": "One full reset", "resets_total": 1, "resets_left": 1, "ends_at": "2030-01-01T00:00:00+00:00", "clears": ["five_hour", "seven_day"], "usable_now": True, "percent_used": {"five_hour": 7, "seven_day": 23}},
            {"id": "used-1", "label": "Used", "resets_total": 1, "resets_left": 0, "clears": ["five_hour"], "usable_now": False, "unavailable_reason": "unavailable"},
            {"id": "BAD ID", "resets_total": 1, "resets_left": 1},
        ],
    }
}


class LimitResetsTest(unittest.TestCase):
    def setUp(self):
        logins.reset()
        logins._agent["v"] = "9.9.9"
        self.aid = "aaaa1111"
        patches = [
            mock.patch.object(ca, "signed_in", side_effect=lambda a: a == self.aid),
            mock.patch.object(ca, "twin", return_value=None),
            mock.patch.object(ca, "label", return_value="ann"),
            mock.patch.object(ca, "refresh_all"),
            mock.patch.object(logins, "access", return_value=("at-ann", "")),
            mock.patch.object(logins, "identity", return_value={"org_uuid": "org-1"}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        logins._usage[self.aid] = {"next": 0.0, "windows": {}, "at": 0.0, "resets": logins.parse_resets(GRANTS)}

    def test_granted_resets_are_listed_with_what_they_refill(self):
        full, used = ca.resets(self.aid)
        self.assertEqual((full["id"], full["left"], full["clears"], full["usable"], full["used"]), ("full-1", 1, ["Session", "Weekly"], True, {"Session": 7, "Weekly": 23}))
        self.assertEqual((used["left"], used["usable"]), (0, False))
        self.assertEqual(ca.resets("token-acc"), [])

    def test_a_reset_is_spent_only_when_it_is_offered_and_usable(self):
        with mock.patch.object(logins, "claim_reset", return_value=(True, "reset", {"resets_left": 0})) as claim:
            for grant in ("used-1", "nope"):
                with self.assertRaises(ValueError):
                    ca.use_reset(self.aid, grant)
            claim.assert_not_called()
            self.assertIn("0 left", ca.use_reset(self.aid, "full-1"))
            claim.assert_called_once_with("at-ann", "org-1", "full-1")

    def test_a_refused_reset_says_why(self):
        with mock.patch.object(logins, "claim_reset", return_value=(False, "not_limited", {})):
            with self.assertRaisesRegex(ValueError, "only be used at a limit"):
                ca.use_reset(self.aid, "full-1")

    def test_the_claim_goes_to_the_accounts_organization(self):
        seen = {}

        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b'{"result": "reset", "resets_left": 0}'

        def fake(req, timeout=0):
            seen.update(url=req.full_url, body=json.loads(req.data), agent=req.get_header("User-agent"))
            return Resp()

        with mock.patch.object(logins.request, "urlopen", side_effect=fake):
            self.assertEqual(logins.claim_reset("at-ann", "org-1", "full-1")[:2], (True, "reset"))
        self.assertTrue(seen["url"].endswith("/api/organizations/org-1/reset_rate_limits"))
        self.assertEqual((seen["body"]["program"], seen["body"]["grant_id"], seen["agent"]), ("cedar_ember", "full-1", "claude-cli/9.9.9 (external, cli)"))
        self.assertRegex(seen["body"]["request_id"], r"^[A-Za-z0-9_-]{1,64}$")
