import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config as cfg
import stackprofile as profile
import worktrees
from core import lock, state


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True)


class WorktreeCleanupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.repo, remote = root / "repo", root / "remote.git"
        git(root, "init", "-q", "--bare", str(remote))
        git(root, "init", "-q", "-b", "main", str(self.repo))
        git(self.repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "first")
        git(self.repo, "remote", "add", "origin", str(remote))
        git(self.repo, "push", "-q", "origin", "main")
        self.wt = root / "wts" / "wt1"
        git(self.repo, "worktree", "add", "-q", "-b", "feature-x", str(self.wt))
        cfg.set("project.root", str(self.repo), "user")
        cfg.set("project.worktrees", None, "user")
        cfg.set("project.profile", "generic", "user")
        with lock:
            state["containers"], state["pg_sizes"], state["sessions"] = [], {}, []
            state["review"] = {"mrs": [{"iid": 5, "title": "Feature", "source": "feature-x", "state": "opened", "url": "https://gl/5"}]}
        for p in (mock.patch.object(worktrees, "_refresh"),):
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        cfg.set("project.root", None, "user")
        cfg.set("project.profile", None, "user")
        worktrees._jobs.clear()
        self.tmp.cleanup()

    def wait(self, name):
        for _ in range(200):
            if worktrees._jobs[name]["status"] != "running":
                return worktrees._jobs[name]
            import time

            time.sleep(0.05)
        raise AssertionError("cleanup did not finish")

    def test_plan_lists_what_would_be_lost(self):
        p = worktrees.plan("wt1")
        self.assertEqual((p["branch"], p["command"]), ("feature-x", ""))
        self.assertEqual([w["kind"] for w in p["warnings"]], ["mr"])
        git(self.wt, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "local only")
        (self.wt / "new.txt").write_text("x")
        kinds = [w["kind"] for w in worktrees.plan("wt1")["warnings"]]
        self.assertEqual(kinds, ["uncommitted", "unpushed", "mr"])

    def test_refuses_unsaved_work_unless_forced(self):
        (self.wt / "new.txt").write_text("x")
        worktrees.remove("wt1")
        self.assertEqual(self.wait("wt1")["status"], "error")
        self.assertTrue(self.wt.exists())
        worktrees.remove("wt1", force=True)
        self.assertEqual(self.wait("wt1")["status"], "done")
        self.assertFalse(self.wt.exists())
        branches = subprocess.run(["git", "-C", str(self.repo), "branch", "--list", "feature-x"], capture_output=True, text=True).stdout
        self.assertEqual(branches.strip(), "")

    def test_only_listed_worktrees(self):
        for bad in ("../repo", "main", "repo", "a;rm -rf /"):
            with self.assertRaises(ValueError):
                worktrees.plan(bad)
        with self.assertRaises(ValueError):
            worktrees.remove(self.repo.name, force=True)

    def test_profile_command_is_used_with_force(self):
        with mock.patch.object(
            profile, "get", side_effect=lambda key, default=None: {"worktrees": {"remove": "invoke remove-worktree -n {name}", "force_flag": "--force"}}.get(key, default)
        ), mock.patch.object(worktrees, "_sh", return_value=True) as sh:
            worktrees.remove("wt1", force=True)
            self.wait("wt1")
        self.assertEqual(sh.call_args[0][1], "invoke remove-worktree -n wt1 --force")


if __name__ == "__main__":
    unittest.main()
