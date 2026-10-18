"""Offline credential-reset regression tests (no device or web access)."""
from __future__ import annotations

from contextlib import closing, redirect_stdout
from io import StringIO
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from chamber_web.security.auth import (
    AuthenticationError, AuthorizationError, Role, SecurityProfile, SecurityStore,
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

    def test_factory_reset_without_password_restores_renamed_admin_and_preserves_users(self):
        operator = self._isolated_lan()
        issued = self.store.issue_recovery_token(
            self.admin.session, self.admin.csrf,
        )
        self.store.change_admin_username(
            self.admin.session, self.admin.csrf,
            self.OLD_PASSWORD, "renamed_admin",
        )
        self.store.reset_factory_credentials_offline()

        self.assertEqual(self.store.get_security_profile(), SecurityProfile.GENERAL)
        self.assertEqual(self.store.factory_credentials_active(), (True, True))
        admin = self.store.login("admin", "admin")
        self.assertEqual(self.store.authenticate(admin.session).role, Role.ADMIN)
        with self.assertRaises(AuthenticationError):
            self.store.login("renamed_admin", self.OLD_PASSWORD)
        with self.assertRaises(AuthenticationError):
            self.store.login("admin", "12345678", use_pin=True)
        with self.assertRaises(AuthenticationError):
            self.store.authenticate(operator.session)
        self.assertIsNotNone(self.store.login(
            "operator_user", "StrongOperatorPassword#789"
        ).session)
        with self.assertRaises(AuthenticationError):
            self.store.recover_admin_offline(
                issued, "admin", self.NEW_PASSWORD, reset_credentials=True,
            )
        with closing(sqlite3.connect(self.store.database)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM users").fetchone()[0], 2)
            self.assertEqual(db.execute(
                "SELECT count(*) FROM sessions WHERE revoked=0"
            ).fetchone()[0], 2)  # Admin and operator logins after reset.
            row = db.execute(
                "SELECT password_hash,pin_hash,enabled FROM users WHERE username='admin'"
            ).fetchone()
            self.assertEqual(row[2], 1)
            self.assertTrue(row[0].startswith("scrypt:"))
            self.assertTrue(row[1].startswith("scrypt:"))
            self.assertNotEqual(row[0], "admin")
            self.assertNotEqual(row[1], "12345678")
        self.assertGreater(self.store.verify_audit_integrity(), 0)
        self.assertIn("recovery.factory.reset", str(self.store.audit_records()))

    def test_local_reset_refuses_nonadmin_username_collision_atomically(self):
        self.store.create_user(
            self.admin.session, self.admin.csrf,
            "admin", "StrongOperatorPassword#789", Role.OPERATOR,
        )
        baseline = self.store.audit_records()
        with self.assertRaises(AuthorizationError):
            self.store.reset_factory_credentials_offline()
        self.assertEqual(self.store.audit_records(), baseline)
        self.assertIsNotNone(self.store.login("admin_user", self.OLD_PASSWORD).session)
        self.assertEqual(self.store.get_security_profile(), SecurityProfile.GENERAL)

    def test_local_reset_refuses_ambiguous_admin_and_unbootstrapped_store(self):
        self.store.create_user(
            self.admin.session, self.admin.csrf,
            "other_admin", "StrongSecondAdminPass#789", Role.ADMIN,
        )
        with self.assertRaises(AuthorizationError):
            self.store.reset_factory_credentials_offline()
        with tempfile.TemporaryDirectory() as directory:
            empty = SecurityStore(Path(directory) / "security")
            with self.assertRaises(AuthorizationError):
                empty.reset_factory_credentials_offline()
            self.assertFalse(empty.is_bootstrapped())

    def test_factory_reset_works_without_proof_in_pin_only_mode(self):
        self._isolated_lan()
        with patch.dict(os.environ, {"CHAMBER_SECURITY_DIR": str(self.path)}), \
             patch("chamber_web.security.bootstrap._local_reset_console",
                   return_value=True), \
             patch("builtins.input", side_effect=["RESET"]) as response, \
             redirect_stdout(StringIO()) as output:
            self.assertEqual(interactive_reset_credentials(), 0)
            self.assertEqual(response.call_count, 1)
            self.assertNotIn(self.OLD_PASSWORD, output.getvalue())
        self.assertEqual(self.store.get_security_profile(), SecurityProfile.GENERAL)
        self.assertIsNotNone(self.store.login("admin", "admin").session)

    def test_local_reset_refuses_noninteractive_and_cancelled_confirmation(self):
        with patch("chamber_web.security.bootstrap.sys.stdin") as stdin:
            stdin.isatty.return_value = False
            self.assertEqual(interactive_reset_credentials(self.path), 2)
        with patch("chamber_web.security.bootstrap._local_reset_console",
                   return_value=True), \
             patch("builtins.input", return_value="NO"), \
             redirect_stdout(StringIO()):
            self.assertEqual(interactive_reset_credentials(self.path), 2)
        self.assertEqual(self.store.factory_credentials_active(), (False, False))
        self.assertIsNotNone(self.store.login(
            "admin_user", self.OLD_PASSWORD,
        ).session)

    def test_reject_ssh_and_rdp_remote_session_markers(self):
        from chamber_web.security.bootstrap import _local_reset_console
        with patch("chamber_web.security.bootstrap.sys.stdin") as stdin:
            stdin.isatty.return_value = True
            for env in ({"SSH_CONNECTION": "192.0.2.1 7777 192.0.2.2 22"},
                        {"SSH_TTY": "/dev/pts/1"},
                        {"SESSIONNAME": "RDP-Tcp#4"}):
                with self.subTest(env=env), patch.dict(os.environ, env):
                    self.assertFalse(_local_reset_console())
    def test_missing_database_refused_without_creating_authority(self):
        unknown = self.path.parent / "wrong-data-directory"
        with patch("chamber_web.security.bootstrap._local_reset_console",
                   return_value=True):
            self.assertEqual(interactive_reset_credentials(unknown), 2)
        self.assertFalse(unknown.exists())


class DirectScriptInvocationTests(unittest.TestCase):
    """Regression for ModuleNotFoundError when script is run by filename."""

    def test_script_loads_from_repo_root_and_unrelated_working_directory(self):
        script = Path(__file__).resolve().parents[1] / "scripts" / "reset_credentials.py"
        with tempfile.TemporaryDirectory() as other_cwd:
            for cwd in (script.parent.parent, Path(other_cwd)):
                with self.subTest(cwd=str(cwd)):
                    env = os.environ.copy()
                    env.pop("PYTHONPATH", None)
                    result = subprocess.run(
                        [sys.executable, "-I", str(script), "--help"],
                        cwd=cwd, env=env, capture_output=True, text=True,
                        timeout=30, check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("--data-dir", result.stdout)
                    self.assertNotIn("ModuleNotFoundError", result.stderr)

    def test_direct_execution_remains_interactive_only(self):
        script = Path(__file__).resolve().parents[1] / "scripts" / "reset_credentials.py"
        with tempfile.TemporaryDirectory() as other_cwd:
            result = subprocess.run(
                [sys.executable, "-I", str(script)],
                cwd=other_cwd, capture_output=True, text=True,
                timeout=30, check=False,
            )
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("interactive console", result.stderr)
        self.assertNotIn("ModuleNotFoundError", result.stderr)

    def test_standalone_copied_script_exits_with_clear_diagnostic(self):
        script = Path(__file__).resolve().parents[1] / "scripts" / "reset_credentials.py"
        with tempfile.TemporaryDirectory() as directory:
            detached = Path(directory) / "scripts" / script.name
            detached.parent.mkdir()
            shutil.copyfile(script, detached)
            result = subprocess.run(
                [sys.executable, "-I", str(detached), "--help"],
                cwd=directory, capture_output=True, text=True,
                timeout=30, check=False,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("complete GUI repository checkout", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
