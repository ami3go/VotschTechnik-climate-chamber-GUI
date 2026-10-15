"""Security profile regression tests: offline PINs, revocation and expiry.

Use a fake clock; no physical hardware or network listener is required.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path

from chamber_web.security.auth import (
    AuthenticationError, AuthorizationError, Role, SecurityProfile, SecurityStore,
)


class SecurityProfileTests(unittest.TestCase):
    PASSWORD = "StrongAdminPassword#1"
    PIN = "629480"

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

    def enroll(self, username="admin_user", pin=PIN):
        return self.store.configure_user_pin(
            self.admin.session, self.admin.csrf, self.PASSWORD, username, pin)

    def activate_isolated(self):
        self.enroll()
        # Enrolling the current user revokes all their sessions immediately.
        self.admin = self.store.login("admin_user", self.PASSWORD)
        self.store.set_security_profile(
            self.admin.session, self.admin.csrf,
            self.PASSWORD, SecurityProfile.ISOLATED_LAN,
        )

    def test_defaults_and_legacy_password_expiry(self):
        self.assertIs(self.store.get_security_profile(), SecurityProfile.GENERAL)
        self.now[0] += 60
        with self.assertRaises(AuthenticationError):
            self.store.authenticate(self.admin.session, touch=False)
        restarted = SecurityStore(self.path, clock=lambda: self.now[0],
                                  idle_timeout_s=60, absolute_timeout_s=120)
        self.assertIs(restarted.get_security_profile(), SecurityProfile.GENERAL)
        with self.assertRaises(AuthenticationError):
            restarted.login("admin_user", self.PIN, use_pin=True)

    def test_pin_setup_validated_no_plaintext(self):
        for pin in ("12345", "1234567890123", "12345x", "１２３４５６", ""):
            with self.subTest(pin=pin), self.assertRaises(ValueError):
                self.enroll(pin=pin)
        self.enroll()
        with closing(sqlite3.connect(self.store.database)) as db:
            stored = db.execute("SELECT pin_hash FROM users WHERE username='admin_user'"
                                ).fetchone()[0]
        self.assertTrue(stored.startswith("scrypt:"))
        self.assertNotIn(self.PIN, stored)
        self.assertNotIn(self.PIN, str(self.store.audit_records()))

    def test_pin_mode_must_be_opted_into_with_enrolled_admin(self):
        with self.assertRaises(AuthorizationError):
            self.store.set_security_profile(
                self.admin.session, self.admin.csrf, self.PASSWORD,
                SecurityProfile.ISOLATED_LAN)
        self.assertIs(self.store.get_security_profile(), SecurityProfile.GENERAL)
        self.activate_isolated()
        self.assertIs(self.store.get_security_profile(), SecurityProfile.ISOLATED_LAN)
        with self.assertRaises(AuthenticationError):
            self.store.authenticate(self.admin.session)
        with self.assertRaises(AuthenticationError):
            self.store.login("admin_user", self.PASSWORD)
        tokens = self.store.login("admin_user", self.PIN, use_pin=True)
        self.assertIs(self.store.authenticate(tokens.session).role, Role.ADMIN)

    def test_isolated_session_never_expires_server_side(self):
        self.activate_isolated()
        tokens = self.store.login("admin_user", self.PIN, use_pin=True)
        self.now[0] += 365 * 24 * 3600 * 3
        self.store.authenticate(tokens.session, touch=False)
        restarted = SecurityStore(self.path, clock=lambda: self.now[0])
        self.assertIs(restarted.get_security_profile(), SecurityProfile.ISOLATED_LAN)
        restarted.authenticate(tokens.session, touch=False)
        restarted.logout(tokens.session)
        with self.assertRaises(AuthenticationError):
            self.store.authenticate(tokens.session)

    def test_profile_change_revokes_sessions_and_restores_password_auth(self):
        self.activate_isolated()
        tokens = self.store.login("admin_user", self.PIN, use_pin=True)
        self.store.set_security_profile(
            tokens.session, tokens.csrf, self.PASSWORD,
            SecurityProfile.LARGE_NETWORK)
        with self.assertRaises(AuthenticationError):
            self.store.authenticate(tokens.session)
        with self.assertRaises(AuthenticationError):
            self.store.login("admin_user", self.PIN, use_pin=True)
        pw_tokens = self.store.login("admin_user", self.PASSWORD)
        self.now[0] += 3599
        self.store.authenticate(pw_tokens.session, touch=False)
        self.now[0] += 1
        with self.assertRaises(AuthenticationError):
            self.store.authenticate(pw_tokens.session, touch=False)

    def test_large_network_absolute_expiry(self):
        self.store.set_security_profile(
            self.admin.session, self.admin.csrf, self.PASSWORD,
            SecurityProfile.LARGE_NETWORK)
        session = self.store.login("admin_user", self.PASSWORD)
        for index in range(24):
            self.now[0] += 1800
            if index < 23:
                self.store.authenticate(session.session)
        with self.assertRaises(AuthenticationError):
            self.store.authenticate(session.session)

    def test_wrong_password_or_csrf_denies_security_changes(self):
        with self.assertRaises(AuthorizationError):
            self.store.set_security_profile(
                self.admin.session, self.admin.csrf, "wrong password",
                SecurityProfile.LARGE_NETWORK)
        with self.assertRaises(AuthorizationError):
            self.store.configure_user_pin(
                self.admin.session, "bad csrf", self.PASSWORD,
                "admin_user", self.PIN)
        self.assertIs(self.store.get_security_profile(), SecurityProfile.GENERAL)

    def test_operator_cannot_choose_profile_or_enroll_pin(self):
        self.store.create_user(self.admin.session, self.admin.csrf,
                               "operator_a", "OperatorPassword#2", Role.OPERATOR)
        operator = self.store.login("operator_a", "OperatorPassword#2")
        with self.assertRaises(AuthorizationError):
            self.store.set_security_profile(
                operator.session, operator.csrf, "OperatorPassword#2",
                SecurityProfile.LARGE_NETWORK)
        with self.assertRaises(AuthorizationError):
            self.store.configure_user_pin(
                operator.session, operator.csrf, "OperatorPassword#2",
                "operator_a", "123456")

    def test_no_lockout_bypass_in_pin_mode(self):
        self.activate_isolated()
        for attempt in range(5):
            with self.assertRaises(AuthenticationError):
                self.store.login("admin_user", "000000", use_pin=True,
                                 client_id="192.168.0.20")
        with self.assertRaises(AuthenticationError):
            self.store.login("admin_user", self.PIN, use_pin=True,
                             client_id="192.168.0.20")

    def test_offline_primary_password_still_works_for_recovery_enrollment(self):
        self.activate_isolated()
        with self.assertRaises(AuthenticationError):
            self.store.login("admin_user", self.PASSWORD)
        offline = self.store.login(
            "admin_user", self.PASSWORD, offline_primary_password=True)
        self.assertIs(self.store.authenticate(offline.session).role, Role.ADMIN)
        self.store.logout(offline.session)

    def test_cannot_enable_bad_profile(self):
        with self.assertRaises(ValueError):
            self.store.set_security_profile(
                self.admin.session, self.admin.csrf, self.PASSWORD, "isolated_lan")


if __name__ == "__main__":
    unittest.main()
