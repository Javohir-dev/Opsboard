import json
import os
import stat
import time
import unittest
from pathlib import Path

import claudeaccounts as ca
import claudeusage
import config as cfg
import notify
from core import DATA, lock, state

GOOD = "sk-ant-oat01-" + "a" * 40
SPARE = "sk-ant-oat01-" + "b" * 40
FULL = "sk-ant-oat01-" + "c" * 40
FAKE = """#!/bin/sh
echo "$CLAUDE_CONFIG_DIR $*" >> "{log}"
case "$CLAUDE_CODE_OAUTH_TOKEN" in
  *aaaa*|*dddd*) u5=0.85 ;;
  *bbbb*) u5=0.30 ;;
  *cccc*) u5=0.70 ;;
  *) echo '{{"type":"result","is_error":true,"result":"Failed to authenticate. API Error: 401"}}'; exit 1 ;;
esac
echo '{{"type":"system","subtype":"init"}}'
echo '{{"type":"rate_limit_event","rate_limit_info":{{"status":"allowed","unifiedWindows":{{"five_hour":{{"utilization":'$u5',"resetsAt":4102444800}},"seven_day":{{"utilization":0.2,"resetsAt":4102444800}}}}}}}}'
echo '{{"type":"result","is_error":false,"result":"ok"}}'
"""


class ClaudeAccountsTest(unittest.TestCase):
    def setUp(self):
        self.log = Path(DATA) / "fake-claude.log"
        self.log.write_text("")
        fake = Path(DATA) / "fake-claude"
        fake.write_text(FAKE.format(log=self.log))
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        cfg.set("claude.bin", str(fake), "user")
        ca.SETTINGS.write_text(json.dumps({"model": "opus", "env": {"KEEP": "1"}}))
        ca._usage.clear()
        ca._full["warned"] = False
        ca._proposal.clear()
        ca._snooze["until"] = 0
        with lock:
            state["sessions"], state["runs"], state["claude_usage"] = [], [], {"account": {"email": "me@x.uz"}}
        notify.clear()
        claudeusage.reset()

    def tearDown(self):
        claudeusage.CREDENTIALS_FILE.unlink(missing_ok=True)
        claudeusage.reset()
        for a in ca.accounts():
            cfg.set_secret(ca.secret_key(a["id"]), "")
        for key in ("claude.bin", "claude.accounts", "claude.auto_switch", "claude.disabled", "claude.switch_mode", "claude.watch", "claude.ask_in", "claude.when_none", "claude.switch_at", "claude.switch_to", "claude.confirm_manual"):
            cfg.set(key, None, "user")
        for key in ("claude.main_twin", "claude.main_twin_login"):
            cfg.set(key, None, "auto")
        for key in ():
            cfg.set(key, None, "user")

    def test_parse_probe_reads_both_windows_in_percent(self):
        line = json.dumps({"type": "rate_limit_event", "rate_limit_info": {"unifiedWindows": {"five_hour": {"utilization": 0.01, "resetsAt": 1795081800, "status": "allowed"}, "seven_day": {"utilization": 0.45, "resetsAt": 1795226400}}}})
        windows, error = ca.parse_probe(["noise", line])
        self.assertEqual(windows["five_hour"]["percent"], 1)
        self.assertEqual(windows["seven_day"], {"percent": 45, "resets_at": 1795226400, "status": ""})
        self.assertEqual(error, "")
        self.assertEqual(ca.parse_probe(['{"type":"result","is_error":true,"result":"401"}'])[0], None)

    def test_add_keeps_only_a_token_claude_accepts_and_probes_in_its_own_config_dir(self):
        with self.assertRaises(ValueError):
            ca.add("Bad", "sk-ant-oat01-" + "z" * 40)
        self.assertEqual(ca.accounts(), [])
        aid = ca.add("Work", GOOD)
        self.assertEqual(cfg.secret(ca.secret_key(aid)), GOOD)
        self.assertNotIn(GOOD, json.dumps(cfg.public()))
        self.assertEqual(ca.usage(aid)["windows"]["five_hour"]["percent"], 85)
        self.assertIn(str(ca.PROBE_HOME), self.log.read_text())
        self.assertIn("--no-session-persistence", self.log.read_text())
        with self.assertRaises(ValueError):
            ca.add("Again", GOOD)

    def test_switch_writes_only_the_token_and_back(self):
        aid = ca.add("Work", GOOD)
        self.assertEqual(ca.active_id(), ca.MAIN)
        ca.switch(aid)
        saved = json.loads(ca.SETTINGS.read_text())
        self.assertEqual(saved["env"], {"KEEP": "1", ca.ENV_KEY: GOOD})
        self.assertEqual(saved["model"], "opus")
        self.assertEqual(ca.active_id(), aid)
        self.assertEqual(os.stat(ca.SETTINGS).st_mode & 0o777, 0o600)
        ca.switch(ca.MAIN)
        self.assertEqual(json.loads(ca.SETTINGS.read_text())["env"], {"KEEP": "1"})
        with self.assertRaises(ValueError):
            ca.switch("nope")

    def test_auto_switch_asks_first_and_switches_only_on_yes(self):
        work, spare, _ = ca.add("Work", GOOD), ca.add("Spare", SPARE), ca.add("Half", FULL)
        ca.switch(work)
        with lock:
            state["sessions"] = [{"status": "busy"}]
        pid = ca.auto_switch()
        self.assertTrue(pid)
        self.assertEqual(ca.active_id(), work)
        item = notify.load()[0]
        self.assertEqual(item["kind"], "claude_propose")
        self.assertIn("Spare", item["head"])
        self.assertIn("session is working", item["body"])
        self.assertIsNone(ca.auto_switch())
        self.assertEqual(ca.public()["proposal"]["dst"], "Spare")
        self.assertIn("no longer open", ca.decide("other", True))
        self.assertIn("Switched to Spare", ca.decide(pid, True))
        self.assertEqual(ca.active_id(), spare)
        self.assertEqual(notify.load()[0]["kind"], "claude_switch")
        self.assertIsNone(ca.public()["proposal"])

    def test_switching_by_hand_closes_the_open_question(self):
        work, spare = ca.add("Work", GOOD), ca.add("Spare", SPARE)
        ca.switch(work)
        self.assertTrue(ca.auto_switch())
        ca.switch(spare)
        self.assertIsNone(ca.public()["proposal"])

    def test_not_now_keeps_the_account_and_waits_an_hour(self):
        work, _ = ca.add("Work", GOOD), ca.add("Spare", SPARE)
        ca.switch(work)
        pid = ca.auto_switch()
        self.assertIn("Stayed on Work", ca.decide(pid, False))
        self.assertEqual(ca.active_id(), work)
        self.assertIsNone(ca.auto_switch())
        ca._snooze["until"] = 0
        self.assertTrue(ca.auto_switch())

    def test_cached_numbers_never_start_a_switch(self):
        ca.add("Spare", SPARE)
        with lock:
            state["claude_usage"] = {"limits": [{"kind": "weekly_all", "percent": 92, "resets_at": 4102444800}], "fetched": time.time()}
        self.assertEqual(ca.level(ca.usage(ca.MAIN)), 92)
        self.assertIsNone(ca.auto_switch())
        self.assertEqual(notify.load(), [])

    def test_no_account_below_the_threshold_warns_once(self):
        work, half = ca.add("Work", GOOD), ca.add("Half", FULL)
        ca.switch(work)
        self.assertIsNone(ca.auto_switch())
        self.assertIsNone(ca.auto_switch())
        self.assertEqual([x["kind"] for x in notify.load()], ["claude_full"])
        self.assertEqual(ca.active_id(), work)
        cfg.set("claude.auto_switch", False, "user")
        notify.clear()
        ca._full["warned"] = False
        self.assertIsNone(ca.auto_switch())
        self.assertEqual(notify.load(), [])

    def test_disabled_account_is_never_a_target_and_deleting_the_one_in_use_goes_back_to_login(self):
        work, spare = ca.add("Work", GOOD), ca.add("Spare", SPARE)
        ca.switch(work)
        ca.set_enabled(spare, False)
        self.assertFalse(ca.enabled(spare))
        self.assertIsNone(ca.auto_switch())
        self.assertEqual(ca.active_id(), work)
        ca.set_enabled(spare, True)
        ca._full["warned"] = False
        ca.decide(ca.auto_switch(), True)
        self.assertEqual(ca.active_id(), spare)
        ca.remove(spare)
        self.assertEqual(ca.active_id(), ca.MAIN)
        self.assertNotIn(ca.ENV_KEY, json.loads(ca.SETTINGS.read_text())["env"])
        self.assertEqual(cfg.secret(ca.secret_key(spare)), "")
        with self.assertRaises(ValueError):
            ca.set_enabled("nope", False)

    def login_as(self, token):
        claudeusage.CREDENTIALS_FILE.write_text(json.dumps({"claudeAiOauth": {"accessToken": token, "expiresAt": (time.time() + 3600) * 1000}}))
        claudeusage.reset()

    def test_the_login_twin_is_kept_as_a_token_and_a_second_token_is_refused(self):
        self.login_as(GOOD)
        me = ca.add("Me", "sk-ant-oat01-" + "d" * 40)
        self.assertEqual(cfg.get("claude.main_twin"), me)
        self.assertEqual(ca.pool(), [me])
        self.assertEqual(ca.active_id(), me)
        self.assertTrue(ca.public()["accounts"][0]["login"])
        ca.switch(me)
        self.assertNotIn(ca.ENV_KEY, json.loads(ca.SETTINGS.read_text()).get("env", {}))
        self.assertEqual(ca.active_id(), me)
        spare = ca.add("Spare", SPARE)
        with self.assertRaises(ValueError) as err:
            ca.add("Spare 2", SPARE[:-1] + "x")
        self.assertIn("«Spare»", str(err.exception))
        with self.assertRaises(ValueError):
            ca.add("spare", FULL)
        self.assertEqual([a["id"] for a in ca.accounts()], [me, spare])
        ca.remove(me)
        self.assertFalse(cfg.get("claude.main_twin"))
        self.assertEqual(ca.pool(), [ca.MAIN, spare])

    def test_a_twin_found_later_hides_the_login_and_deletes_nothing(self):
        twin = ca.add("Twin", "sk-ant-oat01-" + "d" * 40)
        self.login_as(GOOD)
        ca._usage[ca.MAIN] = ca.probe(ca.MAIN)
        self.assertEqual(ca.dedupe(), twin)
        self.assertEqual([a["id"] for a in ca.accounts()], [twin])
        self.assertTrue(cfg.secret(ca.secret_key(twin)))
        self.assertEqual(ca.active_id(), twin)
        self.assertEqual(notify.load()[0]["kind"], "claude_duplicate")
        self.assertIsNone(ca.dedupe())

    def test_logging_in_to_another_account_forgets_the_twin(self):
        self.login_as(GOOD)
        with lock:
            state["claude_usage"] = {"account": {"email": "me@x.uz"}}
        me = ca.add("Me", "sk-ant-oat01-" + "d" * 40)
        self.assertEqual(ca.twin(), me)
        with lock:
            state["claude_usage"] = {"account": {"email": "other@x.uz"}}
        self.assertEqual(ca.twin(), "")
        self.assertEqual(ca.pool(), [ca.MAIN, me])
        self.assertEqual(ca.active_id(), ca.MAIN)

    def test_order_puts_use_first_ahead_and_last_resort_behind(self):
        work = ca.add("Work", GOOD)
        spare, half = ca.add("Spare", SPARE), ca.add("Half", FULL)
        ca.switch(work)
        cfg.set("claude.switch_to", 75, "user")
        self.assertEqual(ca.pick(work), spare)
        ca.update(spare, order="last")
        self.assertEqual(ca.pick(work), half)
        ca.update(half, order="last")
        ca.update(spare, order="first")
        self.assertEqual(ca.pick(work), spare)
        self.assertEqual(next(r for r in ca.public()["accounts"] if r["id"] == spare)["order"], "first")
        with self.assertRaises(ValueError):
            ca.update(spare, order="sometimes")

    def test_when_none_is_below_target_it_can_suggest_the_most_room(self):
        work, half = ca.add("Work", GOOD), ca.add("Half", FULL)
        ca.switch(work)
        self.assertIsNone(ca.auto_switch())
        self.assertEqual(notify.load()[0]["kind"], "claude_full")
        cfg.set("claude.when_none", "suggest", "user")
        ca._full["warned"] = False
        self.assertTrue(ca.auto_switch())
        self.assertEqual(ca.public()["proposal"]["dst"], "Half")

    def test_switch_without_asking_switches_and_only_notifies(self):
        work, spare = ca.add("Work", GOOD), ca.add("Spare", SPARE)
        ca.switch(work)
        cfg.set("claude.switch_mode", "auto", "user")
        self.assertEqual(ca.auto_switch(), spare)
        self.assertEqual(ca.active_id(), spare)
        item = notify.load()[0]
        self.assertEqual((item["kind"], item["how"]), ("claude_switch", "automatically"))
        self.assertNotIn("claude_propose", [x["kind"] for x in notify.load()])

    def test_rules_are_validated(self):
        ok = {"mode": "ask", "switch_at": 85, "switch_to": 50, "watch": ["five_hour", "fable"], "ask_in": ["telegram", "nope"], "when_none": "suggest"}
        ca.save_rules(ok)
        self.assertEqual((cfg.get("claude.switch_at"), cfg.get("claude.switch_to"), cfg.get("claude.ask_in")), (85, 50, ["telegram"]))
        for bad in ({"switch_at": 50, "switch_to": 60}, {"watch": []}, {"mode": "maybe"}, {"switch_to": 5}):
            with self.assertRaises(ValueError):
                ca.save_rules({**ok, **bad})

    def test_watched_limits_decide_the_level(self):
        u = {"windows": {"five_hour": {"percent": 10, "resets_at": 0}, "seven_day": {"percent": 30, "resets_at": 0}, "seven_day_fable": {"percent": 90, "resets_at": 0}}}
        self.assertEqual(ca.level(u), 30)
        cfg.set("claude.watch", ["five_hour", "fable"], "user")
        self.assertEqual(ca.level(u), 90)

    def test_add_options_check_and_replacing_a_token(self):
        with self.assertRaises(ValueError):
            ca.check("sk-ant-oat01-" + "z" * 40)
        self.assertEqual(ca.check(SPARE)["windows"]["five_hour"]["percent"], 30)
        spare = ca.add("", SPARE, include=False, switch_now=True)
        self.assertTrue(ca.label(spare).startswith("Account ••••"))
        self.assertFalse(ca.enabled(spare))
        self.assertEqual(ca.active_id(), spare)
        self.assertTrue(ca.public()["accounts"][-1]["added"])
        with self.assertRaises(ValueError):
            ca.update(spare, token=GOOD)
        ca.update(spare, token=SPARE[:-1] + "q")
        self.assertEqual(cfg.secret(ca.secret_key(spare)), SPARE[:-1] + "q")
        self.assertEqual(json.loads(ca.SETTINGS.read_text())["env"][ca.ENV_KEY], SPARE[:-1] + "q")

    def test_rename(self):
        work, spare = ca.add("Work", GOOD), ca.add("Spare", SPARE)
        ca.rename(work, " Office ")
        self.assertEqual(ca.label(work), "Office")
        with self.assertRaises(ValueError):
            ca.rename(work, "spare")
        with self.assertRaises(ValueError):
            ca.rename(work, "  ")
        self.assertEqual(ca.label(spare), "Spare")

    def test_unknown_token_in_settings_is_never_overwritten(self):
        ca.add("Spare", SPARE)
        ca.SETTINGS.write_text(json.dumps({"env": {ca.ENV_KEY: "sk-ant-oat01-" + "x" * 40}}))
        self.assertEqual(ca.active_id(), "other")
        self.assertIsNone(ca.auto_switch())

    def test_expired_windows_do_not_count(self):
        u = {"windows": {"five_hour": {"percent": 99, "resets_at": int(time.time()) - 10}, "seven_day": {"percent": 40, "resets_at": 0}}}
        self.assertEqual(ca.level(u), 40)


if __name__ == "__main__":
    unittest.main()
