"""Regression tests for the single password-only session policy."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from chamber_web.security.auth import (
    AuthenticationError, AuthorizationError, Role, SecurityStore,
)


class SessionPolicyTests(unittest.TestCase):
    PASSWORD = "StrongAdminPassword#1"

    def setUp(self):
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        self.path = Path(root.name) / "security"
        self.now = [1_000_000.]
        self.store = SecurityStore(
            self.path, clock=lambda: self.now[0],
            idle_timeout_s=60, absolute_timeout_s=120,
        )
        self.store.bootstrap_admin("admin_user", self.PASSWORD)
        self.admin = self.store.login("admin_user", self.PASSWORD)

    def test_idle_timeout_and_restart(self):
        self.now[0] += 60
        with self.assertRaises(AuthenticationError):
            self.store.authenticate(self.admin.session, touch=False)
        restarted = SecurityStore(self.path, clock=lambda: self.now[0],
                                  idle_timeout_s=60, absolute_timeout_s=120)
        with self.assertRaises(AuthenticationError):
            restarted.authenticate(self.admin.session, touch=False)

    def test_absolute_timeout_cannot_be_extended_by_touch(self):
        session = self.store.login("admin_user", self.PASSWORD)
        for _ in range(2):
            self.now[0] += 59
            self.store.authenticate(session.session)
        self.now[0] += 2
        with self.assertRaises(AuthenticationError):
            self.store.authenticate(session.session)

    def test_password_change_revokes_sessions(self):
        other = self.store.login("admin_user", self.PASSWORD)
        self.store.change_password(
            self.admin.session, self.admin.csrf, self.PASSWORD,
            "ReplacementPassword#2",
        )
        for tokens in (self.admin, other):
            with self.assertRaises(AuthenticationError):
                self.store.authenticate(tokens.session)
        self.assertIsNotNone(
            self.store.login("admin_user", "ReplacementPassword#2").session)

    def test_wrong_password_or_csrf_denies_password_change(self):
        with self.assertRaises(AuthenticationError):
            self.store.change_password(
                self.admin.session, self.admin.csrf, "wrong password",
                "ReplacementPassword#2",
            )
        with self.assertRaises(AuthorizationError):
            self.store.change_password(
                self.admin.session, "bad csrf", self.PASSWORD,
                "ReplacementPassword#2",
            )
        self.assertIsNotNone(self.store.login("admin_user", self.PASSWORD).session)

    def test_operator_cannot_manage_accounts(self):
        self.store.create_user(self.admin.session, self.admin.csrf,
                               "operator_a", "OperatorPassword#2", Role.OPERATOR)
        operator = self.store.login("operator_a", "OperatorPassword#2")
        with self.assertRaises(AuthorizationError):
            self.store.create_user(operator.session, operator.csrf,
                                   "operator_b", "OperatorPassword#3", Role.VIEWER)
        with self.assertRaises(AuthorizationError):
            self.store.list_users(operator.session)

    def test_lockout_blocks_valid_password(self):
        for _ in range(5):
            with self.assertRaises(AuthenticationError):
                self.store.login("admin_user", "000000",
                                 client_id="192.168.0.20")
        with self.assertRaises(AuthenticationError):
            self.store.login("admin_user", self.PASSWORD,
                             client_id="192.168.0.20")


if __name__ == "__main__":
    unittest.main()
