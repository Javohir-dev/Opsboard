import json
import tempfile
import unittest
from pathlib import Path

import sessions


class WorkflowJournalTest(unittest.TestCase):
    def test_states_from_the_journal(self):
        with tempfile.TemporaryDirectory() as d:
            journal = Path(d) / "journal.jsonl"
            events = [
                {"type": "launched"},
                {"type": "started", "agentId": "a1", "label": "check:1"},
                {"type": "started", "agentId": "a2", "label": "check:2"},
                {"type": "started", "agentId": "a3", "label": "check:3"},
                {"type": "result", "agentId": "a2", "result": "Items 2: done.\nmore"},
                {"type": "error", "agentId": "a3", "error": "timed out"},
            ]
            journal.write_text("\n".join(json.dumps(e) for e in events) + "\nnot json\n")
            out = sessions.workflow_journal(journal)
        self.assertEqual(out["a1"], {"status": "running", "summary": ""})
        self.assertEqual(out["a2"], {"status": "completed", "summary": "Items 2: done."})
        self.assertEqual(out["a3"], {"status": "failed", "summary": "timed out"})

    def test_missing_journal(self):
        self.assertEqual(sessions.workflow_journal(Path("/nonexistent/journal.jsonl")), {})


if __name__ == "__main__":
    unittest.main()
