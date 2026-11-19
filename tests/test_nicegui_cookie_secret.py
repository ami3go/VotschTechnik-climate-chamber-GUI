"""G08 cookie-key filesystem trust boundary (offline; no network or hardware)."""
from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from chamber_web.security import nicegui as web_security


class CookieSecretFileTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.directory = Path(tmp.name) / "security"
        self.path = self.directory / "nicegui_cookie_secret"
        override = patch.object(
            web_security, "security_directory", return_value=self.directory)
        override.start()
        self.addCleanup(override.stop)

    def test_secret_is_generated_once_and_persisted(self):
        first = web_security.cookie_secret()
        second = web_security.cookie_secret()
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)
        self.assertEqual(self.path.read_text(encoding="ascii"), first)
        if os.name != "nt":
            self.assertEqual(self.directory.stat().st_mode & 0o777, 0o700)
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_existing_symlink_key_is_refused(self):
        self.directory.mkdir()
        target = Path(self.directory.parent) / "external_key"
        target.write_text("a" * 64, encoding="ascii")
        if os.name != "nt":
            target.chmod(0o600)
        try:
            self.path.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("Symlink unavailable on this runner")
        with self.assertRaisesRegex(RuntimeError, "Symlink"):
            web_security.cookie_secret()

    def test_non_regular_key_is_refused(self):
        self.directory.mkdir()
        self.path.mkdir()
        with self.assertRaisesRegex(RuntimeError, "Nonregular"):
            web_security.cookie_secret()

    @unittest.skipIf(os.name == "nt", "POSIX ownership and mode validation")
    def test_insecure_permissions_are_refused(self):
        self.directory.mkdir(mode=0o700)
        self.path.write_text("a" * 64, encoding="ascii")
        self.path.chmod(0o644)
        with self.assertRaisesRegex(PermissionError, "permissions"):
            web_security.cookie_secret()

    @unittest.skipIf(os.name == "nt", "POSIX ownership and mode validation")
    def test_foreign_owner_is_refused(self):
        self.directory.mkdir(mode=0o700)
        self.path.write_text("a" * 64, encoding="ascii")
        self.path.chmod(0o600)
        with patch.object(web_security.os, "getuid", return_value=-1):
            with self.assertRaisesRegex(PermissionError, "ownership"):
                web_security.cookie_secret()


if __name__ == "__main__":
    unittest.main()
