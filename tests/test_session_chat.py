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
            + line({"type": "assistant", "thinkingDurationMs": 2400, "message": {"content": [{"type": "thinking", "thinking": "x"}, {"type": "text", "text": "On it."}]}})
            + line({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "a", "name": "Read", "input": {"file_path": "/x/app.js"}}]}})
            + line({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "a", "is_error": True, "content": "File does not exist."}]}})
            + line({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "b", "name": "Bash", "input": {"description": "Run tests"}}]}})
            + line({"type": "assistant", "isSidechain": True, "message": {"content": [{"type": "text", "text": "agent"}]}})
        )
        items = sessions.chat_items(path)
        self.assertEqual([i["kind"] for i in items], ["user", "thought", "assistant", "tool", "tool"])
        self.assertEqual((items[0]["text"], items[1]["secs"]), ("Fix the ring", 2))
        self.assertEqual([(t["name"], t["title"], t["in"], t["out"], t["error"], t["done"]) for t in items[3:]], [("Read", "app.js", "/x/app.js", "File does not exist.", True, True), ("Bash", "Run tests", "", "", False, False)])
        with open(path, "a") as fh:
            fh.write(line({"type": "user", "message": {"content": [{"type": "text", "text": "thanks"}, {"type": "image", "source": {}}]}}))
            fh.write('{"type": "assistant", "message"')
        items = sessions.chat_items(path)
        self.assertEqual((items[-1]["text"], items[-1]["images"]), ("thanks", 1))
        self.assertEqual(len(items[-1]["imgs"]), 1)
        self.assertEqual(len(items), 6)


class SessionImageTest(unittest.TestCase):
    def test_pasted_image_is_served_from_the_transcript(self):
        import base64
        from unittest import mock

        path = Path(tempfile.mkdtemp()) / "s2.jsonl"
        png = base64.b64encode(b"\x89PNG fake").decode()
        path.write_text(line({"type": "user", "sessionId": "s2", "message": {"content": [{"type": "text", "text": "look"}, {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": png}}]}}))
        ref = sessions.chat_items(path)[-1]["imgs"][0]
        with mock.patch.object(sessions, "find_transcript", return_value=path):
            self.assertEqual(sessions.session_image("s2", ref), ("image/png", b"\x89PNG fake"))
            with self.assertRaises(ValueError):
                sessions.session_image("s2", "../1")
            with self.assertRaises(ValueError):
                sessions.session_image("other", ref)


if __name__ == "__main__":
    unittest.main()
