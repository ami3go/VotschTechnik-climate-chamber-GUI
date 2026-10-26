"""First-run factory identity and password-only security regressions."""
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
    AuthenticationError, AuthorizationError, Role, SecurityStore,
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
        self.assertTrue(self.store.factory_credentials_active())
        tokens = self.store.login("admin", "admin")
        self.assertEqual(self.store.authenticate(tokens.session).role, Role.ADMIN)
        with closing(sqlite3.connect(self.store.database)) as db:
            password_hash = db.execute(
                "SELECT password_hash FROM users WHERE username='admin'"
            ).fetchone()[0]
            self.assertNotIn("admin", password_hash)
            tables = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertNotIn("pin_hash", {
                row[1] for row in db.execute("PRAGMA table_info(users)")})
            self.assertNotIn("recovery_tokens", tables)
            self.assertNotIn("security_policy", tables)

    def test_lab_factory_credentials_warn_without_blocking_startup(self):
        from chamber_web.security import nicegui as security_ui
        from chamber_web.security.deployment import DeploymentPolicy

        policy = DeploymentPolicy(
            mode="lab", bind_host="192.168.0.23", port=8080,
            allowed_origins=frozenset({"http://192.168.0.23:8080"}),
            client_networks=(ipaddress.ip_network("192.168.0.0/24"),),
        )
        with patch.dict(os.environ, {"CHAMBER_SECURITY_DIR": str(self.path)}), \
                patch.object(security_ui, "deployment_policy", policy), \
                patch.object(security_ui, "_store", None):
            with self.assertLogs("chamber_web.security.nicegui", level="WARNING") as logs:
                started = security_ui.get_security()
            self.assertTrue(started.factory_credentials_active())
            self.assertIn("factory administrator password remains active",
                          " ".join(logs.output))
            self.assertIs(started.authenticate(
                started.login("admin", "admin").session).role, Role.ADMIN)

    def test_admin_can_change_password_and_restart_does_not_reset(self):
        self.store.provision_factory_admin()
        login = self.store.login("admin", "admin")
        self.store.change_password(
            login.session, login.csrf, "admin", "ReplacementPassword#123"
        )
        with self.assertRaises(AuthenticationError):
            self.store.authenticate(login.session)
        self.assertFalse(self.store.factory_credentials_active())
        restarted = SecurityStore(self.path)
        self.assertFalse(restarted.provision_factory_admin())
        self.assertFalse(restarted.factory_credentials_active())
        self.assertIsNotNone(
            restarted.login("admin", "ReplacementPassword#123").session)
        with self.assertRaises(AuthenticationError):
            restarted.login("admin", "admin")

    def test_factory_banner(self):
        from chamber_web.security.nicegui import factory_credential_warning

        self.assertIsNone(factory_credential_warning(False))
        warning = factory_credential_warning(True)
        self.assertIn("Factory administrator password is still active", warning)
        self.assertIn("Administrator Credentials", warning)

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
        self.assertTrue(self.store.factory_credentials_active())
        restarted = SecurityStore(self.path)
        self.assertFalse(restarted.provision_factory_admin())
        self.assertIs(restarted.authenticate(
            restarted.login("new_admin", "admin").session).role, Role.ADMIN)

    def test_existing_provisioned_database_never_gets_factory_account(self):
        self.store.bootstrap_admin("custom_admin", "StrongCustomPassword#123")
        self.assertFalse(self.store.provision_factory_admin())
        self.assertFalse(self.store.factory_credentials_active())
        with self.assertRaises(AuthenticationError):
            self.store.login("admin", "admin")
        self.assertIsNotNone(
            SecurityStore(self.path).login(
                "custom_admin", "StrongCustomPassword#123")
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


if __name__ == "__main__":
    unittest.main()
