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
