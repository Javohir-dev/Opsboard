import time
import unittest
from unittest import mock

import config as cfg
import notify


def run(status="done", outcome=None, result=""):
    return {"id": "r1", "iid": 7, "name": "fix !7", "status": status, "outcome": outcome, "result": result}


class NotifyTest(unittest.TestCase):
    def setUp(self):
        notify.clear()
        notify._last_alerting_page = 0.0
        p = mock.patch.object(notify, "os_notify")
        self.os_notify = p.start()
        self.addCleanup(p.stop)
        q = mock.patch.object(notify, "play_sound")
        self.sound = q.start()
        self.addCleanup(q.stop)
        cfg.set("notify.sound", None, "user")

    def test_one_unread_item_per_run(self):
        notify.run_finished(run(), "Fix totals")
        notify.mark_read()
        notify.run_finished(run(status="error", result="boom\nlast line"))
        items = notify.load()
        self.assertEqual(len(items), 1)
        self.assertEqual((items[0]["status"], items[0]["error"], items[0]["read"]), ("error", "last line", False))

    def test_desktop_alert_only_without_an_alerting_page(self):
        notify.run_finished(run())
        self.assertEqual(self.os_notify.call_count, 1)
        notify.page_seen(False)
        notify.run_finished(run())
        self.assertEqual(self.os_notify.call_count, 2)
        notify.page_seen(True)
        notify.run_finished(run())
        self.assertEqual(self.os_notify.call_count, 2)
        notify._last_alerting_page = time.time() - notify.PAGE_GONE - 1
        notify.run_finished(run())
        self.assertEqual(self.os_notify.call_count, 3)

    def test_text(self):
        o = {"status": "pushed", "commit": "a1b2c3d", "threads": {"resolved": 3, "open": 0}, "checks": "tests 4/4"}
        self.assertEqual(notify.text(notify.run_finished(run(outcome=o))), ("Fix pushed · !7", "a1b2c3d · threads 3 resolved · 0 open · tests 4/4"))
        self.assertEqual(notify.text(notify.run_finished(run(outcome={"status": "stopped", "note": "conflict"})))[0], "Fix stopped · !7")
        self.assertEqual(notify.text(notify.run_finished(run(status="error", result="  ")))[1], "the run ended with an error")

    def test_sound_unless_switched_off(self):
        notify.run_finished(run())
        notify.run_finished(run(status="error"))
        self.assertEqual([c.args for c in self.sound.call_args_list], [(False,), (True,)])
        cfg.set("notify.sound", False, "user")
        notify.run_finished(run())
        self.assertEqual(self.sound.call_count, 2)

    def test_new_threads_after_the_first_look(self):
        notify.SEEN_FILE.unlink(missing_ok=True)
        head = lambda tid, who="lena": {"id": tid, "author": who.title(), "username": who, "body": "why?", "path": "a/b.py", "line": 3}  # noqa: E731
        mr = lambda *heads: [{"iid": 7, "title": "Fix", "state": "opened", "_threads": list(heads)}]  # noqa: E731
        self.assertEqual(notify.new_threads(mr(head("t1")), "dev"), [])
        self.assertEqual(notify.new_threads(mr(head("t1")), "dev"), [])
        fresh = notify.new_threads(mr(head("t1"), head("t2"), head("t3", "dev")), "dev")
        self.assertEqual([t["id"] for t in fresh], ["t2"])
        item = notify.load()[0]
        self.assertEqual((item["kind"], item["thread_id"], item["iid"]), ("thread", "t2", 7))
        self.assertEqual(notify.text(item), ("New thread · !7 · b.py:3", "Lena: why?"))
        self.assertEqual(notify.new_threads(mr(head("t1"), head("t2")), "dev"), [])

    def test_a_new_request_is_only_remembered(self):
        notify.SEEN_FILE.unlink(missing_ok=True)
        notify.new_threads([], "dev")
        rows = [{"iid": 9, "state": "opened", "_threads": [{"id": "x", "username": "lena"}]}]
        self.assertEqual(notify.new_threads(rows, "dev"), [])
        self.assertNotIn("_threads", rows[0])

    def test_mark_read_and_clear(self):
        a = notify.run_finished(run())
        notify.run_finished({**run(), "id": "r2"})
        notify.mark_read({a["id"]})
        self.assertEqual([x["read"] for x in notify.load()], [False, True])
        notify.clear()
        self.assertEqual(notify.load(), [])


if __name__ == "__main__":
    unittest.main()
