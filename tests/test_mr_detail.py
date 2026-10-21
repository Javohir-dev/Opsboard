import unittest
from unittest import mock
from urllib import error

import server
from core import lock, state
from providers import gitlab

MR = {"iid": 7, "title": "Fix totals", "web_url": "https://gl/x/-/merge_requests/7", "author": {"name": "Dev"}, "description": "d"}
DIFFS = [
    {"new_path": "a.py", "old_path": "a.py", "diff": "@@ -1 +1 @@\n-x\n+y\n"},
    {"new_path": "b.py", "old_path": "old_b.py", "renamed_file": True, "diff": ""},
]
NOTE = {"id": 1, "author": {"name": "Lena", "username": "lena"}, "body": "why?", "created_at": "2026-10-20T10:00:00Z"}
DISCUSSIONS = [
    {
        "id": "d1",
        "notes": [
            {**NOTE, "resolvable": True, "resolved": True, "resolved_by": {"name": "Max"}, "position": {"new_path": "a.py", "new_line": 1}},
            {**NOTE, "id": 2, "body": "fixed", "resolvable": True, "resolved": True},
        ],
    },
    {"id": "d2", "notes": [{**NOTE, "id": 3, "resolvable": True, "resolved": False}]},
    {"id": "d3", "notes": [{**NOTE, "id": 4, "system": True, "body": "added 1 commit"}]},
    {"id": "d4", "notes": [{**NOTE, "id": 5, "body": "thanks"}]},
]


def fake_get(path, params=None, **kw):
    if path.endswith("/diffs"):
        return DIFFS if (params or {}).get("page", 1) == 1 else []
    if path.endswith("/discussions"):
        return DISCUSSIONS
    return MR


class GitLabDetailTest(unittest.TestCase):
    def setUp(self):
        for p in (mock.patch.object(gitlab, "gitlab_get", fake_get), mock.patch.object(gitlab, "_pid", lambda: "x")):
            p.start()
            self.addCleanup(p.stop)

    def test_files_and_threads(self):
        d = gitlab.detail(7)
        self.assertEqual([(f["path"], f["status"]) for f in d["files"]], [("a.py", "modified"), ("b.py", "renamed")])
        self.assertEqual([t["id"] for t in d["threads"]], ["d1", "d2", "d4"])
        d1, d2, d4 = d["threads"]
        self.assertEqual((d1["resolved"], d1["resolved_by"], d1["path"], d1["new_line"], len(d1["notes"])), (True, "Max", "a.py", 1, 2))
        self.assertEqual((d2["resolvable"], d2["resolved"]), (True, False))
        self.assertEqual((d4["resolvable"], d4["notes"][0]["author"]), (False, "Lena"))

    def test_old_gitlab_without_diffs_endpoint(self):
        def old_get(path, params=None, **kw):
            if path.endswith("/diffs"):
                raise error.HTTPError(path, 404, "not found", {}, None)
            if path.endswith("/changes"):
                return {"changes": DIFFS[:1]}
            return fake_get(path, params)

        with mock.patch.object(gitlab, "gitlab_get", old_get):
            self.assertEqual(len(gitlab.detail(7)["files"]), 1)


class MrEndpointTest(unittest.TestCase):
    def test_only_your_own_merge_requests(self):
        with lock:
            state["review"] = {"mrs": [{"iid": 7}]}
        server.MR_CACHE.clear()
        with mock.patch.object(server, "review_host", return_value=mock.Mock(detail=lambda iid: {"number": iid})) as host:
            self.assertEqual(server.mr_detail(7)["number"], 7)
            server.mr_detail(7)
            self.assertEqual(host.call_count, 1)
            with self.assertRaises(ValueError):
                server.mr_detail(8)


if __name__ == "__main__":
    unittest.main()
