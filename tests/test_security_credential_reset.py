"""Offline credential-reset regression tests (no device or web access)."""
from __future__ import annotations

from contextlib import closing, redirect_stdout
from io import StringIO
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from chamber_web.security.auth import (
    AuthenticationError, Role, SecurityProfile, SecurityStore,
)
from chamber_web.security.bootstrap import interactive_reset_credentials


class OfflineCredentialResetTests(unittest.TestCase):
    OLD_PASSWORD = "StrongAdminPassword#123"
    NEW_PASSWORD = "ReplacementAdminPassword#456"

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "security"
        self.store = SecurityStore(self.path)
        self.store.bootstrap_admin("admin_user", self.OLD_PASSWORD)
        self.admin = self.store.login("admin_user", self.OLD_PASSWORD)

    def _isolated_lan(self):
        self.store.create_user(
            self.admin.session, self.admin.csrf,
            "operator_user", "StrongOperatorPassword#789", Role.OPERATOR,
        )
        self.store.configure_user_pin(
            self.admin.session, self.admin.csrf, self.OLD_PASSWORD,
            "operator_user", "246801",
        )
        self.store.configure_user_pin(
            self.admin.session, self.admin.csrf, self.OLD_PASSWORD,
            "admin_user", "123456",
        )
        self.admin = self.store.login("admin_user", self.OLD_PASSWORD)
        self.store.set_security_profile(
            self.admin.session, self.admin.csrf,
            self.OLD_PASSWORD, SecurityProfile.ISOLATED_LAN,
        )
        self.admin = self.store.login("admin_user", "123456", use_pin=True)
        operator = self.store.login("operator_user", "246801", use_pin=True)
        return operator

    def test_reset_token_resets_password_pin_profile_and_all_sessions(self):
        operator = self._isolated_lan()
        recovery = self.store.issue_recovery_token(
            self.admin.session, self.admin.csrf,
        )
        self.store.recover_admin_offline(
            recovery, "admin_user", self.NEW_PASSWORD, reset_credentials=True,
        )
        self.assertEqual(self.store.get_security_profile(), SecurityProfile.GENERAL)
        with closing(sqlite3.connect(self.store.database)) as db:
            self.assertIsNone(db.execute(
                "SELECT pin_hash FROM users WHERE username='admin_user'"
            ).fetchone()[0])
            self.assertEqual(db.execute(
                "SELECT count(*) FROM users"
            ).fetchone()[0], 2)
            self.assertEqual(db.execute(
                "SELECT count(*) FROM sessions WHERE revoked=0"
            ).fetchone()[0], 0)
            self.assertEqual(db.execute(
                "SELECT count(*) FROM recovery_tokens"
            ).fetchone()[0], 0)
        for session in (self.admin, operator):
            with self.assertRaises(AuthenticationError):
                self.store.authenticate(session.session)
        with self.assertRaises(AuthenticationError):
            self.store.login("admin_user", self.OLD_PASSWORD)
        with self.assertRaises(AuthenticationError):
            self.store.login("admin_user", "123456", use_pin=True)
        self.assertEqual(
            self.store.authenticate(
                self.store.login("admin_user", self.NEW_PASSWORD).session,
            ).role, Role.ADMIN,
        )
        self.assertIsNotNone(self.store.login(
            "operator_user", "StrongOperatorPassword#789"
        ).session)
        with self.assertRaises(AuthenticationError):
            self.store.recover_admin_offline(
                recovery, "admin_user", self.NEW_PASSWORD, reset_credentials=True,
            )
        self.assertGreater(self.store.verify_audit_integrity(), 0)
        self.assertIn("recovery.credentials.reset", str(self.store.audit_records()))

    def test_invalid_or_wrong_account_token_is_atomic(self):
        self._isolated_lan()
        recovery = self.store.issue_recovery_token(
            self.admin.session, self.admin.csrf,
        )
        for credential, account in (("invalid", "admin_user"),
                                    (recovery, "operator_user")):
            with self.subTest(account=account), self.assertRaises(AuthenticationError):
                self.store.recover_admin_offline(
                    credential, account, self.NEW_PASSWORD,
                    reset_credentials=True,
                )
        self.assertEqual(self.store.get_security_profile(), SecurityProfile.ISOLATED_LAN)
        with closing(sqlite3.connect(self.store.database)) as db:
            self.assertIsNotNone(db.execute(
                "SELECT pin_hash FROM users WHERE username='admin_user'"
            ).fetchone()[0])
        self.assertIsNotNone(self.store.login(
            "admin_user", "123456", use_pin=True,
        ).session)

    def test_legacy_recovery_does_not_change_pin_profile(self):
        self._isolated_lan()
        recovery = self.store.issue_recovery_token(
            self.admin.session, self.admin.csrf,
        )
        self.store.recover_admin_offline(recovery, "admin_user", self.NEW_PASSWORD)
        self.assertEqual(self.store.get_security_profile(), SecurityProfile.ISOLATED_LAN)
        with self.assertRaises(AuthenticationError):
            self.store.login("admin_user", self.NEW_PASSWORD)
        self.assertIsNotNone(self.store.login(
            "admin_user", "123456", use_pin=True,
        ).session)

    def test_password_proof_works_in_pin_only_mode(self):
        self._isolated_lan()
        with patch.dict(os.environ, {"CHAMBER_SECURITY_DIR": str(self.path)}), \
             patch("chamber_web.security.bootstrap.sys.stdin") as stdin, \
             patch("builtins.input", side_effect=["admin_user", "p"]), \
             patch("chamber_web.security.bootstrap.getpass.getpass",
                   side_effect=[self.OLD_PASSWORD, self.NEW_PASSWORD, self.NEW_PASSWORD]), \
             redirect_stdout(StringIO()) as output:
            stdin.isatty.return_value = True
            self.assertEqual(interactive_reset_credentials(), 0)
            self.assertNotIn(self.OLD_PASSWORD, output.getvalue())
        self.assertEqual(self.store.get_security_profile(), SecurityProfile.GENERAL)
        self.assertIsNotNone(self.store.login(
            "admin_user", self.NEW_PASSWORD,
        ).session)

    def test_token_proof_and_refuse_noninteractive(self):
        token = self.store.issue_recovery_token(
            self.admin.session, self.admin.csrf,
        )
        with patch("chamber_web.security.bootstrap.sys.stdin") as stdin:
            stdin.isatty.return_value = False
            self.assertEqual(interactive_reset_credentials(self.path), 2)
        with patch("chamber_web.security.bootstrap.sys.stdin") as stdin, \
             patch("builtins.input", side_effect=["admin_user", "t"]), \
             patch("chamber_web.security.bootstrap.getpass.getpass",
                   side_effect=[token, self.NEW_PASSWORD, self.NEW_PASSWORD]), \
             redirect_stdout(StringIO()) as output:
            stdin.isatty.return_value = True
            self.assertEqual(interactive_reset_credentials(self.path), 0)
            self.assertNotIn(token, output.getvalue())
        self.assertIsNotNone(self.store.login(
            "admin_user", self.NEW_PASSWORD,
        ).session)

    def test_missing_database_refused_without_creating_authority(self):
        unknown = self.path.parent / "wrong-data-directory"
        with patch("chamber_web.security.bootstrap.sys.stdin") as stdin:
            stdin.isatty.return_value = True
            self.assertEqual(interactive_reset_credentials(unknown), 2)
        self.assertFalse(unknown.exists())


if __name__ == "__main__":
    unittest.main()
