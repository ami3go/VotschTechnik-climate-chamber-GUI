"""Supervised physical HIL authorization: fail-closed config and gate wiring.

No hardware: a driver double mimics the external Vötsch ``ClimateChamber``
interface so CI covers the same code path the supervised HIL session uses.
"""
from __future__ import annotations

import asyncio
import tempfile
import threading
import unittest
from pathlib import Path

from chamber_web.adapters.votsch import VotschBackend
from chamber_web.domain.chamber import (
    ChamberIdentityMismatch, ChamberSafetyError, OperationState,
)
from chamber_web.domain.config import ChamberConfig
from chamber_web.hil.physical import (
    ACKNOWLEDGEMENT, HilAuthorization, hil_authorization_from_env,
)
from chamber_web.security.auth import Role, SecurityStore
from chamber_web.security.guards import AuthorizedChamber
from chamber_web.services.chamber_manager import ChamberManager
from chamber_web.services.dashboard import DashboardService
from chamber_web.services.manual_control import ManualControlService, ManualState

SERIAL = "58566207770010"


def _env(**overrides):
    env = {
        "CHAMBER_HIL_ADDRESS": "192.168.0.11",
        "CHAMBER_HIL_EXPECTED_SERIAL": SERIAL,
        "CHAMBER_HIL_TEMP_MIN_C": "18",
        "CHAMBER_HIL_TEMP_MAX_C": "30",
        "CHAMBER_HIL_ACK": ACKNOWLEDGEMENT,
    }
    env.update(overrides)
    return {key: value for key, value in env.items() if value is not None}


class DriverDouble:
    """Same attribute surface as VotschTechnikClimateChamber.ClimateChamber."""

    def __init__(self, serial=SERIAL, measured=24.6, setpoint=23.0):
        self.serial_number = serial
        self.test_system_type = "VT 4011"
        self.temperature_measured = measured
        self._setpoint = setpoint
        self._running = False
        self.calls = []
        self.disconnected = False
        self._lock = threading.Lock()

    @property
    def temperature_set_point(self):
        return self._setpoint

    @temperature_set_point.setter
    def temperature_set_point(self, value):
        with self._lock:
            self.calls.append(("set", value))
            self._setpoint = value

    @property
    def is_running(self):
        return self._running

    def start(self):
        self.calls.append(("start",))
        self._running = True

    def stop(self, verify_timeout=3.0):
        self.calls.append(("stop",))
        self._running = False

    def disconnect(self):
        self.disconnected = True


class HilConfigurationTests(unittest.TestCase):
    def test_no_hil_variables_means_simulation(self):
        self.assertIsNone(hil_authorization_from_env({}))
        self.assertIsNone(hil_authorization_from_env({"CHAMBER_PORT": "8080"}))

    def test_complete_configuration(self):
        hil = hil_authorization_from_env(_env())
        self.assertEqual((hil.address, hil.expected_serial, hil.temperature_min_c,
                          hil.temperature_max_c), ("192.168.0.11", SERIAL, 18.0, 30.0))

    def test_partial_or_invalid_configuration_fails_closed(self):
        bad = {
            "missing serial": _env(CHAMBER_HIL_EXPECTED_SERIAL=None),
            "missing ack": _env(CHAMBER_HIL_ACK=None),
            "wrong ack": _env(CHAMBER_HIL_ACK="yes"),
            "public address": _env(CHAMBER_HIL_ADDRESS="8.8.8.8"),
            "loopback address": _env(CHAMBER_HIL_ADDRESS="127.0.0.1"),
            "hostname": _env(CHAMBER_HIL_ADDRESS="chamber.local"),
            "ipv6": _env(CHAMBER_HIL_ADDRESS="fd00::1"),
            "inverted envelope": _env(CHAMBER_HIL_TEMP_MIN_C="30", CHAMBER_HIL_TEMP_MAX_C="18"),
            "too wide": _env(CHAMBER_HIL_TEMP_MIN_C="-40", CHAMBER_HIL_TEMP_MAX_C="80"),
            "beyond hard limit": _env(CHAMBER_HIL_TEMP_MIN_C="120", CHAMBER_HIL_TEMP_MAX_C="140"),
            "not a number": _env(CHAMBER_HIL_TEMP_MAX_C="nan"),
            "text": _env(CHAMBER_HIL_TEMP_MIN_C="cold"),
            "bad serial": _env(CHAMBER_HIL_EXPECTED_SERIAL="58 56;rm"),
        }
        for name, env in bad.items():
            with self.subTest(name), self.assertRaises(ChamberSafetyError):
                hil_authorization_from_env(env)


class VotschHilBackendTests(unittest.TestCase):
    def setUp(self):
        self.hil = hil_authorization_from_env(_env())
        self.driver = DriverDouble()

    def backend(self, driver=None):
        return VotschBackend(self.hil.chamber_id, self.hil.address, hil=self.hil,
                             hil_driver_factory=lambda: driver or self.driver)

    def test_unauthorized_backend_stays_disabled(self):
        backend = VotschBackend("hil-votsch", "192.168.0.11")
        self.assertFalse(backend.physical_authorized)
        with self.assertRaises(ChamberSafetyError):
            backend.connect()

    def test_authorization_must_match_endpoint_and_mode(self):
        with self.assertRaises(ChamberSafetyError):
            VotschBackend(self.hil.chamber_id, "192.168.0.12", hil=self.hil)
        with self.assertRaises(ChamberSafetyError):
            VotschBackend(self.hil.chamber_id, self.hil.address, hil=self.hil,
                          mock_driver_factory=DriverDouble)
        with self.assertRaises(ChamberSafetyError):
            VotschBackend("hil-votsch", "192.168.0.11", hil_driver_factory=DriverDouble)

    def test_physical_identity_is_not_labelled_simulation(self):
        backend = self.backend()
        backend.connect()
        identity = backend.identify()
        self.assertFalse(identity.is_simulation)
        self.assertEqual((identity.model, identity.serial_number), ("VT 4011", SERIAL))
        self.assertFalse(backend.simulation_only)
        caps = backend.capabilities()
        self.assertEqual((caps.temperature_min_c, caps.temperature_max_c), (18.0, 30.0))
        snapshot = backend.read_status()
        self.assertEqual(snapshot.operation_state, OperationState.STOPPED)
        self.assertEqual(snapshot.measured_temperature_c, 24.6)

    def test_wrong_serial_refused_and_disconnected(self):
        other = DriverDouble(serial="99999999999999")
        with self.assertRaises(ChamberIdentityMismatch):
            self.backend(other).connect()
        self.assertTrue(other.disconnected)

    def test_serial_swap_during_session_refuses_reads(self):
        backend = self.backend()
        backend.connect()
        self.driver.serial_number = "99999999999999"
        with self.assertRaises(ChamberIdentityMismatch):
            backend.read_status()

    def test_setpoint_outside_envelope_never_reaches_driver(self):
        backend = self.backend()
        backend.connect()
        for target in (17.9, 30.1, float("nan")):
            with self.subTest(target), self.assertRaises(Exception):
                backend.set_temperature(target)
        self.assertEqual(self.driver.calls, [])


class HilManualControlTests(unittest.TestCase):
    """End-to-end through G04 controller, G08 authorization and G05 service."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.security = SecurityStore(root / "security")
        self.security.bootstrap_admin("admin_1", "StrongAdminPassword#1")
        self.admin = self.security.login("admin_1", "StrongAdminPassword#1")
        self.security.create_user(self.admin.session, self.admin.csrf, "operator_1",
                                  "StrongOperatorPassword#2", Role.OPERATOR)
        self.op = self.security.login("operator_1", "StrongOperatorPassword#2")
        self.hil = hil_authorization_from_env(_env())
        self.driver = DriverDouble()
        config = ChamberConfig(self.hil.chamber_id, "votsch", self.hil.address)
        self.manager = ChamberManager(
            [config], lease_directory=root / "lease", io_timeout_s=2.0,
            backend_factory=lambda cfg, allow_test_backend=False: VotschBackend(
                cfg.chamber_id, cfg.address, hil=self.hil,
                hil_driver_factory=lambda: self.driver))
        self.manager.connect(config.chamber_id)
        self.addCleanup(self.manager.disconnect, config.chamber_id)
        self.dashboard = DashboardService(self.manager, config.chamber_id)
        asyncio.run(self.dashboard.poll_once())
        self.service = ManualControlService(
            self.manager, self.dashboard, AuthorizedChamber(self.manager, self.security),
            self.security, config.chamber_id, physical_hil=self.hil)

    def send(self, action, **kw):
        return self.service.command(self.op.session, self.op.csrf,
                                    self.service.chamber_id, action, **kw)

    def test_claim_set_start_stop_on_authorized_physical_chamber(self):
        view = self.service.view(self.op.session, self.service.chamber_id)
        self.assertEqual(view.controller_state, "VERIFIED_STOPPED")
        self.assertEqual(view.presets_c, (23.0,))  # only presets inside 18..30 °C
        self.assertEqual(self.send("claim").state, ManualState.CONFIRMED)
        self.assertEqual(self.send("set_temperature", target_c=25.0).state,
                         ManualState.CONFIRMED)
        self.assertEqual(self.send("start").state, ManualState.CONFIRMED)
        self.assertEqual(self.send("stop").state, ManualState.CONFIRMED)
        self.assertEqual(self.driver.calls, [("set", 25.0), ("start",), ("stop",)])

    def test_out_of_envelope_target_rejected_without_device_write(self):
        self.assertEqual(self.send("claim").state, ManualState.CONFIRMED)
        self.assertNotEqual(self.send("set_temperature", target_c=40.0).state,
                            ManualState.CONFIRMED)
        self.assertEqual(self.driver.calls, [])

    def test_simulation_service_never_controls_physical_identity(self):
        unauthorized = ManualControlService(
            self.manager, self.dashboard, AuthorizedChamber(self.manager, self.security),
            self.security, self.service.chamber_id)
        view = unauthorized.view(self.op.session, unauthorized.chamber_id)
        self.assertFalse(view.can_start)
        self.assertEqual(unauthorized.command(self.op.session, self.op.csrf,
                                              unauthorized.chamber_id, "claim").state,
                         ManualState.REJECTED)
        self.assertEqual(self.driver.calls, [])

    def test_authorization_for_other_chamber_rejected(self):
        other = HilAuthorization("other-chamber", "192.168.0.11", SERIAL, 18.0, 30.0)
        with self.assertRaises(ChamberSafetyError):
            ManualControlService(
                self.manager, self.dashboard, AuthorizedChamber(self.manager, self.security),
                self.security, self.service.chamber_id, physical_hil=other)


if __name__ == "__main__":
    unittest.main()
