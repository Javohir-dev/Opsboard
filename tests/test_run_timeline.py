import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import runs


def tool(tid, name, ts, **inp):
    return {"type": "assistant", "timestamp": ts, "message": {"content": [{"type": "tool_use", "id": tid, "name": name, "input": inp}]}}


def say(ts, text):
    return {"type": "assistant", "timestamp": ts, "message": {"content": [{"type": "text", "text": text}]}}


def result(tid, error=False):
    return {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "is_error": error}]}}


class RunTimelineTest(unittest.TestCase):
    def timeline(self, events, status="running"):
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "r.jsonl"
            log.write_text("\n".join(json.dumps(e) for e in events))
            run = {"id": "r1", "iid": 7, "status": status, "started": 0, "log": str(log), "pid": 1}
            with mock.patch.object(runs, "load_runs", return_value=[run]):
                return runs.run_timeline("r1")

    def test_phases_from_commands(self):
        t = self.timeline(
            [
                tool("a", "Bash", "2026-10-20T10:00:00Z", command="T=x/mr_threads.py; python3 $T list 7", description="Open threads"),
                result("a"),
                tool("b", "Bash", "2026-10-20T10:00:10Z", command="git fetch origin && git merge --no-edit origin/main"),
                result("b"),
                say("2026-10-20T10:00:20Z", 'Merged cleanly.\nOPS_STEP {"step": "threads", "note": "3 valid"}'),
                tool("c", "Edit", "2026-10-20T10:01:00Z", file_path="/x/cart.py"),
                result("c"),
                tool("d", "Bash", "2026-10-20T10:02:00Z", command="invoke test-warm -m shop", run_in_background=True),
                result("d"),
            ]
        )
        status = {p["key"]: p["status"] for p in t["phases"]}
        self.assertEqual(status, {"merge": "done", "threads": "done", "fix": "done", "checks": "running", "commit": "pending", "push": "pending"})
        self.assertEqual(next(p for p in t["phases"] if p["key"] == "threads")["note"], "3 valid")
        kinds = [(e["kind"], e.get("tool"), e.get("status")) for e in t["events"]]
        self.assertIn(("say", None, None), kinds)
        self.assertEqual(t["events"][-1]["status"], "background")
        self.assertEqual(t["events"][2]["text"], "Merged cleanly.")

    def test_finished_run_and_replies(self):
        t = self.timeline(
            [
                tool("a", "Bash", "2026-10-20T10:00:00Z", command="git -c user.name=x commit -m fix && git push origin b"),
                result("a"),
                tool("b", "Bash", "2026-10-20T10:00:05Z", command="T=x/mr_threads.py; python3 $T reply 7 0a1b2c3d4e5f r.md --resolve"),
                result("b", error=True),
            ],
            status="done",
        )
        status = {p["key"]: p["status"] for p in t["phases"]}
        self.assertEqual((status["commit"], status["push"], status["merge"]), ("done", "done", "skipped"))
        self.assertEqual(t["replied"], ["0a1b2c3d4e5f"])
        self.assertEqual(t["events"][-1]["status"], "failed")

    def test_unknown_run(self):
        with mock.patch.object(runs, "load_runs", return_value=[]), self.assertRaises(ValueError):
            runs.run_timeline("nope")


if __name__ == "__main__":
    unittest.main()
