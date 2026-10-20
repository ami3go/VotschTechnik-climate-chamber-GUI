"""Administrator-saved chamber settings: validation, persistence and precedence.

No physical hardware is contacted; settings only take effect at server start.
"""
from __future__ import annotations

import ast
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from chamber_web.domain.chamber import ChamberSafetyError
from chamber_web.hil.chamber_settings import (
    ChamberSettings, effective_hil_environment, load_settings, save_settings,
)
from chamber_web.hil.physical import ACKNOWLEDGEMENT, hil_authorization_from_env
from chamber_web.security.auth import AuthorizationError, Role, SecurityStore

PHYSICAL = ChamberSettings(
    chamber_type="votsch", chamber_id="lab-1", address="192.168.10.20",
    expected_serial="ABC123", temperature_min_c=15.0, temperature_max_c=35.0,
    person_present_acknowledged=True,
)


class ChamberSettingsTests(unittest.TestCase):
    PASSWORD = "StrongAdminPassword#1"

    def setUp(self):
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        self.root = Path(root.name)
        self.path = self.root / "chamber_settings.json"
        self.store = SecurityStore(self.root / "security")
        self.store.bootstrap_admin("admin_user", self.PASSWORD)
        self.admin = self.store.login("admin_user", self.PASSWORD)

    def save(self, settings=PHYSICAL, password=PASSWORD, tokens=None):
        tokens = tokens or self.admin
        return save_settings(self.store, tokens.session, tokens.csrf, password,
                             settings, path=self.path)

    def test_saved_physical_settings_produce_hil_authorization(self):
        stored = self.save()
        self.assertEqual(stored.saved_by, "admin_user")
        self.assertEqual(load_settings(self.path), stored)
        env, source = effective_hil_environment({}, self.path)
        self.assertEqual(source, "chamber settings")
        hil = hil_authorization_from_env(env)
        self.assertEqual((hil.chamber_id, hil.address, hil.expected_serial),
                         ("lab-1", "192.168.10.20", "ABC123"))
        self.assertEqual((hil.temperature_min_c, hil.temperature_max_c), (15.0, 35.0))
        actions = [row for row in self.store.audit_records()
                   if "chamber.settings.save" in row]
        self.assertTrue(actions)

    def test_main_composes_h02_from_effective_settings_environment(self):
        """Saved H02 fields must reach the runtime, not only CHAMBER_HIL fields."""
        source = (Path(__file__).resolve().parents[1] / "chamber_web" / "main.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "supervised_runtime_from_env"
        ]
        self.assertEqual(len(calls), 1)
        self.assertIsInstance(calls[0].args[0], ast.Name)
        self.assertEqual(calls[0].args[0].id, "_HIL_ENV")

    def test_simulator_and_missing_file_stay_simulated(self):
        self.assertEqual(effective_hil_environment({}, self.path), ({}, "default"))
        self.save(ChamberSettings())
        env, source = effective_hil_environment({}, self.path)
        self.assertIsNone(hil_authorization_from_env(env))
        self.assertEqual(source, "default")

    def test_environment_overrides_saved_settings(self):
        self.save()
        env = {"CHAMBER_HIL_ADDRESS": "10.0.0.5"}
        self.assertEqual(effective_hil_environment(env, self.path), (env, "environment"))

    def test_launch_rules_rejected_before_writing(self):
        for bad in (
            replace(PHYSICAL, address="8.8.8.8"),
            replace(PHYSICAL, address="127.0.0.1"),
            replace(PHYSICAL, expected_serial=""),
            replace(PHYSICAL, temperature_min_c=0.0, temperature_max_c=60.0),
            replace(PHYSICAL, temperature_max_c=10.0),
            replace(PHYSICAL, person_present_acknowledged=False),
            replace(PHYSICAL, chamber_id="bad id"),
            replace(PHYSICAL, chamber_type="other"),
        ):
            with self.subTest(bad=bad), self.assertRaises(ChamberSafetyError):
                self.save(bad)
        self.assertFalse(self.path.exists())

    def test_requires_admin_password_and_role(self):
        with self.assertRaises(AuthorizationError):
            self.save(password="wrong-password-123")
        self.store.create_user(self.admin.session, self.admin.csrf, "operator_user",
                               "OperatorPassword#1", Role.OPERATOR)
        operator = self.store.login("operator_user", "OperatorPassword#1")
        with self.assertRaises(AuthorizationError):
            self.save(password="OperatorPassword#1", tokens=operator)
        self.assertFalse(self.path.exists())

    def test_factory_credentials_warn_only_and_physical_settings_can_be_saved(self):
        store = SecurityStore(self.root / "factory")
        store.provision_factory_admin()
        admin = store.login("admin", "admin")
        saved = save_settings(store, admin.session, admin.csrf, "admin",
                              PHYSICAL, path=self.path)
        self.assertEqual(load_settings(self.path), saved)
        self.assertEqual(store.factory_credentials_active(), (True, True))
        self.assertIsNotNone(hil_authorization_from_env(
            effective_hil_environment({}, self.path)[0]))
        self.assertTrue(any("chamber.settings.save" in row
                            for row in store.audit_records()))
        with self.assertRaises(AuthorizationError):
            save_settings(store, admin.session, admin.csrf,
                          "wrong-password", PHYSICAL, path=self.path)
        store.change_password(admin.session, admin.csrf, "admin", "NewPassword#123")
        restarted = SecurityStore(self.root / "factory")
        self.assertEqual(restarted.factory_credentials_active(), (False, True))
        renewed = restarted.login("admin", "NewPassword#123")
        saved = save_settings(restarted, renewed.session, renewed.csrf,
                              "NewPassword#123", PHYSICAL, path=self.path)
        self.assertEqual(load_settings(self.path), saved)

    def test_corrupt_or_tampered_file_fails_closed(self):
        self.path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(ChamberSafetyError):
            effective_hil_environment({}, self.path)
        data = {"chamber_type": "votsch", "chamber_id": "lab-1", "address": "192.168.1.2",
                "expected_serial": "X1", "temperature_min_c": 15, "temperature_max_c": 35,
                "person_present_acknowledged": "yes"}
        self.path.write_text(json.dumps(data), encoding="utf-8")
        env, _ = effective_hil_environment({}, self.path)
        # A non-boolean acknowledgement is never treated as the HIL ACK.
        self.assertNotEqual(env.get("CHAMBER_HIL_ACK"), ACKNOWLEDGEMENT)
        with self.assertRaises(ChamberSafetyError):
            hil_authorization_from_env(env)


if __name__ == "__main__":
    unittest.main()
