import json
import tempfile
import unittest
from pathlib import Path

import sessions


def line(d):
    return json.dumps(d) + "\n"


class SessionChatTest(unittest.TestCase):
    def test_visible_conversation_and_incremental_reads(self):
        path = Path(tempfile.mkdtemp()) / "s.jsonl"
        path.write_text(
            line({"type": "user", "message": {"content": "<system-reminder>hidden</system-reminder>Fix the ring"}, "timestamp": "t1"})
            + line({"type": "user", "isMeta": True, "message": {"content": "meta"}})
            + line({"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": "x"}, {"type": "text", "text": "On it."}]}})
            + line({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "a", "name": "Read", "input": {"file_path": "/x/app.js"}}]}})
            + line({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "a", "is_error": True}]}})
            + line({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "b", "name": "Bash", "input": {"description": "Run tests"}}]}})
            + line({"type": "assistant", "isSidechain": True, "message": {"content": [{"type": "text", "text": "agent"}]}})
        )
        items = sessions.chat_items(path)
        self.assertEqual([i["kind"] for i in items], ["user", "assistant", "tools"])
        self.assertEqual(items[0]["text"], "Fix the ring")
        self.assertEqual([(t["name"], t["what"], t["error"]) for t in items[2]["tools"]], [("Read", "app.js", True), ("Bash", "Run tests", False)])
        with open(path, "a") as fh:
            fh.write(line({"type": "user", "message": {"content": [{"type": "text", "text": "thanks"}, {"type": "image", "source": {}}]}}))
            fh.write('{"type": "assistant", "message"')
        items = sessions.chat_items(path)
        self.assertEqual((items[-1]["text"], items[-1]["images"]), ("thanks", 1))
        self.assertEqual(len(items), 4)


if __name__ == "__main__":
    unittest.main()
