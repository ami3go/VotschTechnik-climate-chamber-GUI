"""Signed bench-emulator enrollment: positive, negative and composition tests.

No physical chamber or network emulator is contacted here. A fake driver
exercises the adapter/controller path; the live Leonardo is verified
separately by an explicit opt-in bench script.
"""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import time
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from chamber_web.adapters.votsch import VotschBackend
from chamber_web.domain.chamber import ChamberError, ChamberSafetyError
from chamber_web.domain.config import ChamberConfig
from chamber_web.execution.profile_runner import TERMINAL, RunParameters, RunState
from chamber_web.hil.emulator import (
    ACK, ACK_ENV, ENROLLMENT_ENV, TRUSTED_KEY_ENV,
    EmulatorAuthorization, emulator_authorization_from_env,
    verify_signed_enrollment,
)
from chamber_web.services.chamber_manager import ChamberManager
from chamber_web.persistence.profiles import ProfileStore
from chamber_web.security.auth import SecurityStore
from chamber_web.security.guards import AuthorizedChamber
from chamber_web.services.profile_editor import ProfileEditorService
from chamber_web.services.profile_execution import ProfileExecutionService
from chamber_web.services.profile_runtime import ProfileRunRuntime


def _keypair():
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return private, public


def _spec(**overrides):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    spec = {
        "schema_version": 1,
        "scope": "EMULATOR_BENCH_DEVICE",
        "chamber_id": "leo-emu",
        "backend_id": "votsch_emulator",
        "address": "192.168.31.146",
        "expected_serial": "SIMLEO0001",
        "expected_model": "VT4011-EMULATOR",
        "temperature_min_c": 15.0,
        "temperature_max_c": 35.0,
        "valid_from_utc": (now - timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
        "valid_until_utc": (now + timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
        "operator": "bench-operator",
        "approval_reference": "LEO-BENCH-01",
        "isolated_network_ack": True,
        "firmware_sha256": None,
    }
    spec.update(overrides)
    return spec


def _sign(spec, private):
    canonical = json.dumps(spec, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, allow_nan=False).encode("utf-8")
    return {"enrollment": spec,
            "signature_base64": base64.b64encode(private.sign(canonical)).decode("ascii")}


class FakeEmulatorDriver:
    test_system_type = "VT4011-EMULATOR"
    serial_number = "SIMLEO0001"
    temperature_measured = 23.0
    temperature_set_point = 23.0
    is_running = False
    gradient_up = 2.0
    gradient_down = 2.0
    number_of_digital_outputs = 8

    def __init__(self):
        self.outputs = {number: False for number in range(1, 9)}
        self.calls = []
        self.disconnected = False

    def disconnect(self):
        self.disconnected = True

    def start(self):
        self.calls.append(("start",))
        self.is_running = True
        self.outputs[1] = True

    def stop(self):
        self.calls.append(("stop",))
        self.is_running = False
        self.outputs[1] = False

    def digital_output_name(self, number):
        return f"output-{number}"

    def read_digital_output(self, number):
        self.calls.append(("read", number))
        return self.outputs[number]

    def set_digital_output(self, number, state):
        self.calls.append(("set", number, state))
        self.outputs[number] = state


class EnrollmentVerificationTests(unittest.TestCase):
    def setUp(self):
        self.private, self.public = _keypair()

    def test_signed_enrollment_verifies_exact_device(self):
        authorization = verify_signed_enrollment(
            _sign(_spec(), self.private), trusted_public_key=self.public)
        self.assertIsInstance(authorization, EmulatorAuthorization)
        self.assertEqual(authorization.chamber_id, "leo-emu")
        self.assertEqual(authorization.expected_serial, "SIMLEO0001")
        self.assertEqual(authorization.backend_id, "votsch_emulator")
        self.assertFalse(authorization.expected_model == "VT4011")

    def test_tampered_field_is_rejected(self):
        signed = _sign(_spec(), self.private)
        signed["enrollment"]["address"] = "192.168.31.147"
        with self.assertRaises(ChamberSafetyError):
            verify_signed_enrollment(signed, trusted_public_key=self.public)

    def test_wrong_scope_and_backend_are_rejected(self):
        for change in ({"scope": "H02_SUPERVISED_PHYSICAL_PROFILE"},
                       {"backend_id": "votsch"}):
            with self.subTest(change=change):
                with self.assertRaises(ChamberSafetyError):
                    verify_signed_enrollment(
                        _sign(_spec(**change), self.private),
                        trusted_public_key=self.public)

    def test_real_serial_and_wrong_model_are_rejected(self):
        for change in ({"expected_serial": "58566207770010"},
                       {"expected_serial": "EMU0001"},
                       {"expected_model": "VT4011"}):
            with self.subTest(change=change):
                with self.assertRaises(ChamberSafetyError):
                    verify_signed_enrollment(
                        _sign(_spec(**change), self.private),
                        trusted_public_key=self.public)

    def test_expired_overlong_and_unacknowledged_are_rejected(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        expired = _spec(
            valid_from_utc=(now - timedelta(hours=4)).isoformat().replace("+00:00", "Z"),
            valid_until_utc=(now - timedelta(hours=3)).isoformat().replace("+00:00", "Z"))
        overlong = _spec(
            valid_from_utc=(now - timedelta(days=1)).isoformat().replace("+00:00", "Z"),
            valid_until_utc=(now + timedelta(days=20)).isoformat().replace("+00:00", "Z"))
        for change in (expired, overlong, _spec(isolated_network_ack=False)):
            with self.subTest(change=change):
                with self.assertRaises(ChamberSafetyError):
                    verify_signed_enrollment(
                        _sign(change, self.private), trusted_public_key=self.public)

    def test_envelope_span_is_bounded(self):
        with self.assertRaises(ChamberSafetyError):
            verify_signed_enrollment(
                _sign(_spec(temperature_min_c=-40.0, temperature_max_c=80.0), self.private),
                trusted_public_key=self.public)


class EnrollmentEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.private, self.public = _keypair()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.enrollment = self.root / "enrollment.json"
        self.enrollment.write_text(
            json.dumps(_sign(_spec(), self.private)), encoding="utf-8")
        self.enrollment.chmod(0o600)
        self.env = {
            ENROLLMENT_ENV: str(self.enrollment),
            TRUSTED_KEY_ENV: base64.b64encode(self.public).decode("ascii"),
            ACK_ENV: ACK,
        }

    def test_none_when_unconfigured(self):
        self.assertIsNone(emulator_authorization_from_env({}))

    def test_loader_verifies_signed_record(self):
        authorization = emulator_authorization_from_env(self.env)
        self.assertIsNotNone(authorization)
        self.assertEqual(authorization.enrollment_sha256, verify_signed_enrollment(
            json.loads(self.enrollment.read_text(encoding="utf-8")),
            trusted_public_key=self.public).enrollment_sha256)

    def test_loader_rejects_conflicting_physical_policy(self):
        env = dict(self.env, CHAMBER_HIL_ACK="SUPERVISED-PHYSICAL-HIL")
        with self.assertRaises(ChamberSafetyError):
            emulator_authorization_from_env(env)

    def test_loader_rejects_release_launch(self):
        env = dict(self.env, CHAMBER_RELEASE="1")
        with self.assertRaises(ChamberSafetyError):
            emulator_authorization_from_env(env)

    def test_loader_requires_exact_ack_and_trusted_key(self):
        with self.assertRaises(ChamberSafetyError):
            emulator_authorization_from_env(dict(self.env, **{ACK_ENV: "yes"}))
        with self.assertRaises(ChamberSafetyError):
            emulator_authorization_from_env(
                {ENROLLMENT_ENV: str(self.enrollment), ACK_ENV: ACK})


class EmulatorBackendTests(unittest.TestCase):
    def setUp(self):
        self.private, self.public = _keypair()
        self.authorization = verify_signed_enrollment(
            _sign(_spec(), self.private), trusted_public_key=self.public)
        self.driver = FakeEmulatorDriver()

    def _backend(self, authorization=None):
        return VotschBackend(
            "leo-emu", "192.168.31.146",
            emulator=authorization or self.authorization,
            emulator_driver_factory=lambda: self.driver)

    def test_backend_marks_identity_as_emulator_and_uses_envelope(self):
        backend = self._backend()
        backend.connect()
        self.addCleanup(backend.disconnect)
        identity = backend.identify()
        self.assertTrue(identity.is_emulator)
        self.assertFalse(identity.is_simulation)
        self.assertEqual(identity.backend_id, "votsch_emulator")
        self.assertEqual(identity.serial_number, "SIMLEO0001")
        self.assertTrue(backend.emulator_authorized)
        self.assertFalse(backend.physical_authorized)
        capabilities = backend.capabilities()
        self.assertEqual(capabilities.temperature_min_c, 15.0)
        self.assertEqual(capabilities.temperature_max_c, 35.0)
        self.assertEqual(capabilities.digital_outputs[0], (1, "output-1"))

    def test_backend_rejects_serial_or_model_mismatch(self):
        self.driver.serial_number = "SIMOTHER"
        with self.assertRaises(ChamberError):
            self._backend().connect()
        self.driver.serial_number = "SIMLEO0001"
        self.driver.test_system_type = "VT4011"
        with self.assertRaises(ChamberError):
            self._backend().connect()

    def test_backend_requires_matching_chamber_and_address(self):
        with self.assertRaises(ChamberSafetyError):
            VotschBackend("other", "192.168.31.146", emulator=self.authorization)
        with self.assertRaises(ChamberSafetyError):
            VotschBackend("leo-emu", "192.168.31.147", emulator=self.authorization)

    def test_backend_rejects_physical_and_emulator_together(self):
        class Hil:
            chamber_id = "leo-emu"
            address = "192.168.31.146"

        with self.assertRaises(ChamberSafetyError):
            VotschBackend("leo-emu", "192.168.31.146",
                          hil=Hil(), emulator=self.authorization)


class EmulatorControllerTests(unittest.TestCase):
    def test_controller_connects_and_verifies_emulator(self):
        private, public = _keypair()
        authorization = verify_signed_enrollment(
            _sign(_spec(), private), trusted_public_key=public)
        driver = FakeEmulatorDriver()
        config = ChamberConfig("leo-emu", "votsch_emulator", "192.168.31.146")

        def factory(cfg, allow_test_backend=False):
            self.assertEqual(cfg, config)
            return VotschBackend(cfg.chamber_id, cfg.address, emulator=authorization,
                                 emulator_driver_factory=lambda: driver)

        manager = ChamberManager([config], backend_factory=factory)
        manager.connect(config.chamber_id)
        self.addCleanup(manager.disconnect, config.chamber_id)
        health = manager.health(config.chamber_id)
        self.assertTrue(health.connected)
        self.assertEqual(health.state, "VERIFIED_STOPPED")
        self.assertTrue(manager.status(config.chamber_id).identity.is_emulator)


class EmulatorProfileControlTests(unittest.TestCase):
    """G06-facing per-step control is enabled for the emulator, not physical."""

    def setUp(self):
        private, public = _keypair()
        self.authorization = verify_signed_enrollment(
            _sign(_spec(), private), trusted_public_key=public)
        self.driver = FakeEmulatorDriver()
        self.config = ChamberConfig("leo-emu", "votsch_emulator", "192.168.31.146")

    def _manager(self, *, gradient_writes=False):
        def factory(cfg, allow_test_backend=False):
            self.assertEqual(cfg, self.config)
            return VotschBackend(
                cfg.chamber_id, cfg.address, emulator=self.authorization,
                emulator_driver_factory=lambda: self.driver,
                gradient_writes=gradient_writes)

        manager = ChamberManager(
            [self.config], backend_factory=factory,
            lease_directory=Path(tempfile.mkdtemp(prefix="emu-test-lease-")))
        manager.connect(self.config.chamber_id)
        self.addCleanup(manager.disconnect, self.config.chamber_id)
        if manager.health(self.config.chamber_id).state == "UNKNOWN":
            manager.reconcile_stop(self.config.chamber_id)
        return manager

    def test_per_step_run_and_verified_outputs(self):
        manager = self._manager()
        token = manager.claim_operator(self.config.chamber_id, "test")
        manager.set_profile_running(
            self.config.chamber_id, True, operator_token=token)
        self.assertTrue(self.driver.is_running)
        manager.set_profile_running(
            self.config.chamber_id, False, operator_token=token)
        self.assertFalse(self.driver.is_running)
        manager.set_digital_output(
            self.config.chamber_id, 2, True, operator_token=token)
        self.assertTrue(self.driver.outputs[2])
        with self.assertRaises(ChamberSafetyError):
            manager.set_digital_output(
                self.config.chamber_id, 1, True, operator_token=token)

    def test_emulator_gradient_capability_is_explicit(self):
        manager = self._manager(gradient_writes=True)
        caps = manager.capabilities(self.config.chamber_id)
        self.assertTrue(caps.supports_ramp_up)
        self.assertTrue(caps.supports_ramp_down)
        token = manager.claim_operator(self.config.chamber_id, "test")
        manager.set_ramp_up(self.config.chamber_id, 3.0, operator_token=token)
        manager.set_ramp_down(self.config.chamber_id, 1.5, operator_token=token)
        self.assertEqual(self.driver.gradient_up, 3.0)
        self.assertEqual(self.driver.gradient_down, 1.5)

    def test_g06_profile_and_g07_journal_complete_on_emulator(self):
        root = Path(tempfile.mkdtemp(prefix="emu-profile-test-"))
        manager = self._manager()
        security = SecurityStore(root / "auth")
        security.bootstrap_admin("admin", "UniqueEmulatorAdmin#123")
        admin = security.login("admin", "UniqueEmulatorAdmin#123")
        store = ProfileStore(root / "profiles.sqlite3")
        editor = ProfileEditorService(store, self.config.chamber_id)
        draft = editor.new_draft()
        for field, value in (
            ("target_temperature_c", "23"),
            ("tolerance_c", "0.2"),
            ("stabilize_s", "0"),
            ("dwell_s", "0"),
            ("reach_timeout_s", "10"),
            ("chamber_run", "ON"),
            ("digital_outputs", "2=ON"),
        ):
            draft = editor.edit_step(draft, 0, field, value)
        saved = editor.save(draft)
        runtime = ProfileRunRuntime(root / "runs")
        service = ProfileExecutionService(
            manager, store, security, self.config.chamber_id,
            simulation=False, emulator=True,
            manual_guard=AuthorizedChamber(manager, security),
            sink_factory=runtime.sink_factory,
            start_blocker=runtime.start_blocker,
            parameters=RunParameters(poll_s=0.05, max_gap_s=1, max_age_s=1),
        )
        snapshot = service.start(admin.session, admin.csrf, saved.profile_id, 1)
        for _ in range(200):
            state = service.runner.advance()
            if state in TERMINAL:
                break
            time.sleep(0.005)
        self.assertIs(state, RunState.COMPLETED)
        self.assertFalse(self.driver.is_running)
        self.assertTrue(self.driver.outputs[2])
        self.assertEqual(manager.health(self.config.chamber_id).state,
                         "VERIFIED_STOPPED")
        self.assertTrue(service.view(admin.session).emulator)
        record = runtime.store.get_run(self.config.chamber_id, snapshot.run_id)
        events = runtime.store.list_events(
            self.config.chamber_id, snapshot.run_id, limit=500)
        self.assertEqual(record["terminal_state"], "COMPLETED")
        self.assertTrue(any(event["kind"] == "OUTPUT_INTENT" for event in events))
        service.runner.close()


if __name__ == "__main__":
    unittest.main()
