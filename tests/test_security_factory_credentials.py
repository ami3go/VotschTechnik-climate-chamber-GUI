"""First-run factory identity, PIN, admin overrides and security regressions."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import ipaddress
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

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
        with closing(sqlite3.connect(self.store.database)) as db:
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

    def test_lan_factory_credentials_warn_without_blocking_startup(self):
        """Warn about weak credentials without weakening normal LAN auth rules."""
        from chamber_web.security import nicegui as security_ui
        from chamber_web.security.deployment import DeploymentPolicy

        policy = DeploymentPolicy(
            mode="lan", bind_host="192.168.0.23", port=8443,
            allowed_origins=frozenset({"https://chamber.example:8443"}),
            client_networks=(ipaddress.ip_network("192.168.0.0/24"),),
        )
        with patch.dict(os.environ, {"CHAMBER_SECURITY_DIR": str(self.path)}), \
                patch.object(security_ui, "deployment_policy", policy), \
                patch.object(security_ui, "_store", None):
            with self.assertLogs("chamber_web.security.nicegui", level="WARNING") as logs:
                started = security_ui.get_security()
            self.assertEqual(started.factory_credentials_active(), (True, True))
            self.assertIn("factory administrator password and PIN",
                          " ".join(logs.output))
            self.assertIs(started.authenticate(
                started.login("admin", "admin").session).role, Role.ADMIN)

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

    def test_password_only_change_survives_reopen_and_does_not_require_repeat(self):
        self.store.provision_factory_admin()
        first = self.store.login("admin", "admin")
        self.store.change_password(
            first.session, first.csrf, "admin", "DifferentPassword#123")
        restarted = SecurityStore(self.path)
        self.assertFalse(restarted.provision_factory_admin())
        self.assertEqual(restarted.factory_credentials_active(), (False, True))
        with self.assertRaises(AuthenticationError):
            restarted.login("admin", "admin")
        self.assertIsNotNone(
            restarted.login("admin", "DifferentPassword#123").session)

    def test_factory_banner_names_only_unmodified_credential(self):
        from chamber_web.security.nicegui import factory_credential_warning

        self.assertIsNone(factory_credential_warning(False, False))
        combined = factory_credential_warning(True, True)
        self.assertIn("password and PIN are still active", combined)
        password_only = factory_credential_warning(True, False)
        self.assertIn("password is still active", password_only)
        pin_only = factory_credential_warning(False, True)
        self.assertIn("password has been changed", pin_only)
        self.assertIn("PIN is still active", pin_only)
        self.assertIn("does not need to be changed again", pin_only)

    def test_factory_password_does_not_block_large_network_profile(self):
        self.store.provision_factory_admin()
        login = self.store.login("admin", "admin")
        with self.assertRaises(AuthorizationError):
            self.store.set_security_profile(
                login.session, login.csrf, "bad", SecurityProfile.LARGE_NETWORK)
        self.store.set_security_profile(
            login.session, login.csrf, "admin", SecurityProfile.LARGE_NETWORK)
        self.assertEqual(self.store.get_security_profile(), SecurityProfile.LARGE_NETWORK)
        with self.assertRaises(AuthenticationError):
            self.store.authenticate(login.session)
        restarted = SecurityStore(self.path)
        self.assertEqual(restarted.get_security_profile(), SecurityProfile.LARGE_NETWORK)
        self.assertIsNotNone(restarted.login("admin", "admin").session)

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
        changed = restarted.login("new_admin", "admin")
        restarted.set_security_profile(changed.session, changed.csrf, "admin",
                                       SecurityProfile.LARGE_NETWORK)
        self.assertEqual(restarted.get_security_profile(), SecurityProfile.LARGE_NETWORK)

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
        with closing(sqlite3.connect(self.store.database)) as db:
            db.execute(
                "INSERT INTO users(username,password_hash,role)"
                " VALUES('partial_admin','redacted','ADMIN')"
            )
            db.commit()
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
        with closing(sqlite3.connect(self.store.database)) as db:
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
