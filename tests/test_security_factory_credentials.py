"""First-run factory identity, PIN, admin overrides and security regressions."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from chamber_web.security.auth import (
    AuthenticationError, AuthorizationError, Role, SecurityProfile, SecurityStore,
)


class FactoryCredentialTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "security"
        self.store = SecurityStore(self.path)

    def test_new_factory_account_and_initial_password_login(self):
        self.assertFalse(self.store.is_bootstrapped())
        self.assertTrue(self.store.provision_factory_admin())
        self.assertFalse(self.store.provision_factory_admin())
        self.assertEqual(self.store.get_security_profile(), SecurityProfile.GENERAL)
        self.assertEqual(self.store.factory_credentials_active(), (True, True))
        tokens = self.store.login("admin", "admin")
        self.assertEqual(self.store.authenticate(tokens.session).role, Role.ADMIN)
        with self.assertRaises(AuthenticationError):
            self.store.login("admin", "12345678", use_pin=True)
        with sqlite3.connect(self.store.database) as db:
            password_hash, pin_hash = db.execute(
                "SELECT password_hash,pin_hash FROM users WHERE username='admin'"
            ).fetchone()
            self.assertNotIn("admin", password_hash)
            self.assertNotIn("12345678", pin_hash)
        self.assertNotIn("12345678", str(self.store.audit_records()))

    def test_factory_pin_works_only_in_opted_in_isolated_mode(self):
        self.store.provision_factory_admin()
        tokens = self.store.login("admin", "admin")
        self.store.set_security_profile(
            tokens.session, tokens.csrf, "admin", SecurityProfile.ISOLATED_LAN
        )
        with self.assertRaises(AuthenticationError):
            self.store.authenticate(tokens.session)
        with self.assertRaises(AuthenticationError):
            self.store.login("admin", "admin")
        pin_tokens = self.store.login("admin", "12345678", use_pin=True)
        self.assertIs(self.store.authenticate(pin_tokens.session).role, Role.ADMIN)
        restarted = SecurityStore(self.path)
        self.assertEqual(restarted.get_security_profile(), SecurityProfile.ISOLATED_LAN)
        self.assertFalse(restarted.provision_factory_admin())
        self.assertIsNotNone(restarted.login("admin", "12345678", use_pin=True).session)

    def test_admin_can_change_both_credentials_and_restart_does_not_reset(self):
        self.store.provision_factory_admin()
        login = self.store.login("admin", "admin")
        self.store.change_password(
            login.session, login.csrf, "admin", "ReplacementPassword#123"
        )
        with self.assertRaises(AuthenticationError):
            self.store.authenticate(login.session)
        login = self.store.login("admin", "ReplacementPassword#123")
        self.store.configure_user_pin(
            login.session, login.csrf, "ReplacementPassword#123",
            "admin", "87654321",
        )
        with self.assertRaises(AuthenticationError):
            self.store.authenticate(login.session)
        self.assertEqual(self.store.factory_credentials_active(), (False, False))
        login = self.store.login("admin", "ReplacementPassword#123")
        self.store.set_security_profile(
            login.session, login.csrf, "ReplacementPassword#123",
            SecurityProfile.LARGE_NETWORK,
        )
        restarted = SecurityStore(self.path)
        self.assertFalse(restarted.provision_factory_admin())
        self.assertEqual(restarted.factory_credentials_active(), (False, False))
        self.assertEqual(restarted.get_security_profile(), SecurityProfile.LARGE_NETWORK)
        self.assertIsNotNone(restarted.login("admin", "ReplacementPassword#123").session)
        with self.assertRaises(AuthenticationError):
            restarted.login("admin", "admin")

    def test_default_password_cannot_select_large_network(self):
        self.store.provision_factory_admin()
        login = self.store.login("admin", "admin")
        with self.assertRaises(AuthorizationError):
            self.store.set_security_profile(
                login.session, login.csrf, "admin", SecurityProfile.LARGE_NETWORK
            )
        self.assertEqual(self.store.get_security_profile(), SecurityProfile.GENERAL)

    def test_username_override_is_persistent_and_invalidates_sessions(self):
        self.store.provision_factory_admin()
        login = self.store.login("admin", "admin")
        another = self.store.login("admin", "admin")
        with self.assertRaises(AuthorizationError):
            self.store.change_admin_username(
                login.session, login.csrf, "wrong", "new_admin"
            )
        with self.assertRaises(ValueError):
            self.store.change_admin_username(
                login.session, login.csrf, "admin", "x"
            )
        self.store.change_admin_username(
            login.session, login.csrf, "admin", "new_admin"
        )
        for tokens in (login, another):
            with self.assertRaises(AuthenticationError):
                self.store.authenticate(tokens.session)
        with self.assertRaises(AuthenticationError):
            self.store.login("admin", "admin")
        self.assertEqual(self.store.factory_credentials_active(), (True, True))
        restarted = SecurityStore(self.path)
        self.assertFalse(restarted.provision_factory_admin())
        self.assertIs(restarted.authenticate(
            restarted.login("new_admin", "admin").session).role, Role.ADMIN)
        with self.assertRaises(AuthorizationError):
            changed = restarted.login("new_admin", "admin")
            restarted.set_security_profile(changed.session, changed.csrf, "admin",
                                           SecurityProfile.LARGE_NETWORK)

    def test_existing_provisioned_database_never_gets_factory_account(self):
        self.store.bootstrap_admin("custom_admin", "StrongCustomPassword#123")
        self.assertFalse(self.store.provision_factory_admin())
        self.assertEqual(self.store.factory_credentials_active(), (False, False))
        with self.assertRaises(AuthenticationError):
            self.store.login("admin", "admin")
        self.assertIsNotNone(
            SecurityStore(self.path).login("custom_admin", "StrongCustomPassword#123")
        )

    def test_interrupted_partial_identity_does_not_trigger_factory_reset(self):
        with sqlite3.connect(self.store.database) as db:
            db.execute(
                "INSERT INTO users(username,password_hash,role)"
                " VALUES('partial_admin','redacted','ADMIN')"
            )
        with self.assertRaises(RuntimeError):
            self.store.provision_factory_admin()
        self.assertFalse(self.store.is_bootstrapped())

    def test_short_passwords_remain_forbidden_for_normal_accounts(self):
        self.store.provision_factory_admin()
        login = self.store.login("admin", "admin")
        with self.assertRaises(ValueError):
            self.store.change_password(login.session, login.csrf, "admin", "admin")
        with self.assertRaises(ValueError):
            self.store.create_user(login.session, login.csrf,
                                   "operator_a", "admin", Role.OPERATOR)

    def test_concurrent_factory_provisioning_has_single_winner(self):
        def attempt(_):
            instance = SecurityStore(self.path)
            return instance.provision_factory_admin()
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(attempt, range(4)))
        self.assertEqual(results.count(True), 1)
        self.assertEqual(results.count(False), 3)
        with sqlite3.connect(self.store.database) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM users").fetchone()[0], 1)

    def test_password_change_after_long_isolated_session(self):
        self.store.provision_factory_admin()
        login = self.store.login("admin", "admin")
        self.store.set_security_profile(login.session, login.csrf, "admin",
                                        SecurityProfile.ISOLATED_LAN)
        # This reproduces the old change_password bug where isolated sessions
        # were incorrectly rejected using the General profile's timeouts.
        old_time = self.store.clock
        try:
            self.store.clock = lambda: old_time() + 90000
            pin_login = self.store.login("admin", "12345678", use_pin=True)
            self.store.change_password(pin_login.session, pin_login.csrf,
                                       "admin", "NewOfflinePassword#123")
        finally:
            self.store.clock = old_time
        self.assertEqual(self.store.factory_credentials_active()[0], False)


if __name__ == "__main__":
    unittest.main()
