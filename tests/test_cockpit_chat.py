import io
import json
import queue
import tempfile
import time
import unittest
from unittest import mock

import cockpitchat


class FakeProc:
    instances = []

    def __init__(self, cmd, **kw):
        self.cmd, self.env, self.q, self.returncode, self.pid = cmd, kw.get("env"), queue.Queue(), None, 999998
        FakeProc.instances.append(self)
        outer = self

        class In:
            def write(self, line):
                outer.q.put(json.dumps({"type": "system", "subtype": "init", "session_id": "sid-1"}))
                outer.q.put(json.dumps({"type": "result", "result": "ok", "session_id": "sid-1"}))

            def flush(self):
                pass

            def close(self):
                outer.returncode = 0
                outer.q.put(None)

        self.stdin, self.stderr = In(), io.StringIO("")
        self.stdout = iter(self.q.get, None)

    def poll(self):
        return self.returncode


class CockpitChatTest(unittest.TestCase):
    def wait(self, cond):
        for _ in range(100):
            if cond():
                return True
            time.sleep(0.02)
        return False

    def test_start_send_continue(self):
        folder = tempfile.mkdtemp()
        with mock.patch.object(cockpitchat.subprocess, "Popen", FakeProc):
            with self.assertRaises(ValueError):
                cockpitchat.start("  ", folder)
            s = cockpitchat.start("Fix the ring", folder)
            self.assertEqual(s["title"], "Fix the ring")
            self.assertTrue(self.wait(lambda: cockpitchat.find(s["key"]).sid == "sid-1"))
            proc = FakeProc.instances[-1]
            self.assertEqual(proc.env["OPS_COCKPIT"], "1")
            self.assertIn("--permission-mode", proc.cmd)
            self.assertTrue(self.wait(lambda: not cockpitchat.find("sid-1").busy))
            self.assertTrue(cockpitchat.send("sid-1", "and the bar")["busy"])
            with self.assertRaises(ValueError):
                cockpitchat.send("other", "x")
            self.assertEqual(cockpitchat.set_mode("sid-1", "plan")["mode"], "plan")
            with self.assertRaises(ValueError):
                cockpitchat.set_mode("sid-1", "bypassPermissions")
            b2 = cockpitchat.start("go on", folder, resume="0123abcd-0000", fork=True, mode="acceptEdits")
            self.assertEqual((b2["parent"], b2["first"], b2["mode"]), ("0123abcd-0000", "go on", "acceptEdits"))
            self.assertIn("acceptEdits", FakeProc.instances[-1].cmd)
            self.assertEqual(FakeProc.instances[-1].cmd[-3:], ["--resume", "0123abcd-0000", "--fork-session"])
            with self.assertRaises(ValueError):
                cockpitchat.start("x", folder, resume="../etc")
            for p in FakeProc.instances:
                p.stdin.close()
            self.assertTrue(self.wait(lambda: not cockpitchat.find("sid-1").alive()))
            cockpitchat._sessions.clear()
            cockpitchat._load()
            old = cockpitchat.find("sid-1")
            self.assertEqual((old.alive(), old.public()["resumable"], old.title), (False, True, "Fix the ring"))
            n = len(FakeProc.instances)
            cockpitchat.send("sid-1", "continue please")
            self.assertEqual(FakeProc.instances[n].cmd[-2:], ["--resume", "sid-1"])
            self.assertTrue(cockpitchat.find("sid-1").alive())
            FakeProc.instances[n].stdin.close()


if __name__ == "__main__":
    unittest.main()
