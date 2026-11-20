import os
import pwd
import unittest
from pathlib import Path

import safety


class SafetyTest(unittest.TestCase):
    def test_real_files_are_refused_during_tests(self):
        for p in (Path(pwd.getpwuid(os.getuid()).pw_dir) / ".claude" / "settings.json", Path(__file__).resolve().parent.parent / "config.json"):
            with self.assertRaises(RuntimeError):
                safety.allow_write(p)

    def test_scratch_files_are_allowed(self):
        safety.allow_write(Path(os.environ["OPS_DATA_DIR"]) / "config.json")

    def test_keychain_is_refused(self):
        with self.assertRaises(RuntimeError):
            safety.allow_keychain()

    def test_no_backups_are_taken_during_tests(self):
        self.assertIsNone(safety.backup(__file__, "config"))
