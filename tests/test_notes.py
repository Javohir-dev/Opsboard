import json
import os
import unittest

import notes


def item(id_, text, **kw):
    return dict({"id": id_, "kind": "item", "text": text}, **kw)


class NotesTest(unittest.TestCase):
    def setUp(self):
        notes.NOTES_FILE.unlink(missing_ok=True)

    def test_writes_into_the_test_data_dir(self):
        self.assertTrue(str(notes.NOTES_FILE).startswith(os.environ["OPS_DATA_DIR"]))

    def test_save_and_version(self):
        r = notes.save_notes({"version": 0, "items": [item("a", "one")]})
        self.assertEqual(r, {"ok": True, "version": 1})
        self.assertEqual(notes.load_notes()["items"][0]["text"], "one")

    def test_stale_client_gets_conflict_and_current_copy(self):
        notes.save_notes({"version": 0, "items": [item("a", "one")]})
        notes.save_notes({"version": 1, "items": [item("a", "two")]})
        r = notes.save_notes({"version": 1, "items": [item("a", "stale")]})
        self.assertFalse(r["ok"])
        self.assertTrue(r["conflict"])
        self.assertEqual(r["notes"]["items"][0]["text"], "two")

    def test_newer_client_is_accepted(self):
        notes.save_notes({"version": 0, "items": [item("a", "one")]})
        r = notes.save_notes({"version": 7, "items": [item("a", "rescued")]})
        self.assertEqual(r, {"ok": True, "version": 8})

    def test_every_save_keeps_a_backup(self):
        notes.save_notes({"version": 0, "items": [item("a", "one")]})
        notes.save_notes({"version": 1, "items": [item("a", "two")]})
        backups = sorted(notes.NOTES_HISTORY.glob("*.json"))
        self.assertTrue(backups)
        self.assertEqual(json.loads(backups[-1].read_text())["items"][0]["text"], "one")

    def test_clean_note_sanitises(self):
        n = notes.clean_note({"text": "x" * 6000, "tag": "evil", "indent": 9, "history": [{"type": "hack"}, {"type": "text", "to": "y"}]})
        self.assertEqual(len(n["text"]), 5000)
        self.assertEqual(n["tag"], "")
        self.assertEqual(n["indent"], 4)
        self.assertFalse(n["collapsed"])
        self.assertTrue(notes.clean_note({"text": "a", "collapsed": 1})["collapsed"])
        self.assertEqual([h["type"] for h in n["history"]], ["text"])

    def test_bad_payload(self):
        with self.assertRaises(ValueError):
            notes.save_notes({"items": "nope"})


if __name__ == "__main__":
    unittest.main()
