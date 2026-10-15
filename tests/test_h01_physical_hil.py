"""Supervised physical HIL authorization: fail-closed config and gate wiring.

No hardware: a driver double mimics the external Vötsch ``ClimateChamber``
interface so CI covers the same code path the supervised HIL session uses.
"""
from __future__ import annotations

import asyncio
import tempfile
import threading
import time
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

    def __init__(self, serial=SERIAL, measured=24.6, setpoint=23.0, ramp_c_per_min=None,
                 ramp_goal_offset=0.0):
        self.serial_number = serial
        self.test_system_type = "VT 4011"
        self.temperature_measured = measured
        self._setpoint = setpoint
        # Like the VT 4011: 11002 readback ramps from the old value to the target.
        self._ramp = ramp_c_per_min
        self.gradient_up = self.gradient_down = ramp_c_per_min or 5.0
        self._ramp_from, self._ramp_t0, self._goal = setpoint, time.monotonic(), setpoint
        self._goal_offset = ramp_goal_offset
        self._running = False
        self.calls = []
        self.disconnected = False
        self._lock = threading.Lock()

    @property
    def temperature_set_point(self):
        if self._ramp is None:
            return self._setpoint
        elapsed = time.monotonic() - self._ramp_t0
        step = self._ramp / 60.0 * elapsed
        delta = self._goal - self._ramp_from
        return self._goal if abs(delta) <= step else self._ramp_from + step * (1 if delta > 0 else -1)

    @temperature_set_point.setter
    def temperature_set_point(self, value):
        with self._lock:
            self.calls.append(("set", value))
            self._ramp_from, self._ramp_t0 = self.temperature_set_point, time.monotonic()
            self._goal = value + self._goal_offset
            self._setpoint = value + self._goal_offset

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


class HilDeploymentTests(unittest.TestCase):
    """Loopback by default; LAN only behind an explicit narrow opt-in."""

    def policy(self, **kw):
        import ipaddress
        from types import SimpleNamespace

        base = dict(is_lan=True, bind_host="192.168.0.23", certfile=Path("c.pem"),
                    keyfile=Path("k.pem"),
                    client_networks=(ipaddress.ip_network("192.168.0.0/24"),))
        base.update(kw)
        return SimpleNamespace(**base)

    def test_loopback_and_simulation_need_no_opt_in(self):
        from chamber_web.hil.physical import check_hil_deployment

        hil = hil_authorization_from_env(_env())
        check_hil_deployment(hil, self.policy(is_lan=False), {})
        check_hil_deployment(None, self.policy(), {})

    def test_lan_requires_explicit_opt_in(self):
        from chamber_web.hil.physical import check_hil_deployment

        hil = hil_authorization_from_env(_env())
        for value in ("", "0", "yes", "true"):
            with self.subTest(value), self.assertRaises(ChamberSafetyError):
                check_hil_deployment(hil, self.policy(), {"CHAMBER_HIL_ALLOW_LAN": value})
        check_hil_deployment(hil, self.policy(), {"CHAMBER_HIL_ALLOW_LAN": "1"})

    def test_lan_hil_rejects_wildcard_bind_missing_tls_and_broad_networks(self):
        import ipaddress

        from chamber_web.hil.physical import check_hil_deployment

        hil = hil_authorization_from_env(_env())
        opt_in = {"CHAMBER_HIL_ALLOW_LAN": "1"}
        bad = {
            "wildcard bind": self.policy(bind_host="0.0.0.0"),
            "no tls": self.policy(certfile=None),
            "broad ipv4": self.policy(client_networks=(ipaddress.ip_network("192.168.0.0/16"),)),
            "broad ipv6": self.policy(client_networks=(ipaddress.ip_network("fd00::/48"),)),
        }
        for name, policy in bad.items():
            with self.subTest(name), self.assertRaises(ChamberSafetyError):
                check_hil_deployment(hil, policy, opt_in)
        check_hil_deployment(hil, self.policy(
            client_networks=(ipaddress.ip_network("192.168.0.42/32"),)), opt_in)


class HilNavigationLabelTests(unittest.TestCase):
    def test_sidebar_mode_follows_server_hil_flag(self):
        from chamber_web.ui_pages import NavigationContext

        self.assertEqual(NavigationContext(authenticated=True, role="ADMIN").label,
                         "Role: ADMIN · simulation only")
        self.assertEqual(
            NavigationContext(authenticated=True, role="ADMIN", physical_hil=True).label,
            "Role: ADMIN · supervised physical HIL")


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

    def test_device_ramp_reported_and_invalid_gradients_refused(self):
        backend = self.backend()
        backend.connect()
        self.assertEqual(backend.capabilities().setpoint_readback_ramp_c_per_min, (5.0, 5.0))
        for bad in (0.0, -1.0, float("nan"), 1000.0):
            driver = DriverDouble()
            driver.gradient_down = bad
            with self.subTest(bad), self.assertRaises(ChamberSafetyError):
                self.backend(driver).connect()
            self.assertTrue(driver.disconnected)

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

    driver_kwargs = {}

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
        self.driver = DriverDouble(**self.driver_kwargs)
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


class HilRampingSetpointTests(HilManualControlTests):
    """VT 4011 behaviour observed on hardware: the setpoint readback ramps."""

    driver_kwargs = {"ramp_c_per_min": 60.0}  # 1 °C/s keeps CI fast

    def test_ramped_setpoint_confirmed_only_after_convergence(self):
        self.assertEqual(self.send("claim").state, ManualState.CONFIRMED)
        started = time.monotonic()
        outcome = self.send("set_temperature", target_c=25.0)
        self.assertEqual(outcome.state, ManualState.CONFIRMED, outcome.message)
        self.assertGreaterEqual(time.monotonic() - started, 1.5)  # 2 °C at 1 °C/s
        self.assertAlmostEqual(self.driver.temperature_set_point, 25.0, delta=0.1)


class HilDivergingSetpointTests(HilManualControlTests):
    """A device that ramps to a different value must never be CONFIRMED."""

    driver_kwargs = {"ramp_c_per_min": 60.0, "ramp_goal_offset": 3.0}

    def test_claim_set_start_stop_on_authorized_physical_chamber(self):
        self.assertEqual(self.send("claim").state, ManualState.CONFIRMED)
        outcome = self.send("set_temperature", target_c=25.0)
        self.assertEqual(outcome.state, ManualState.UNKNOWN, outcome.message)
        self.assertEqual(self.driver.calls, [("set", 25.0)])


if __name__ == "__main__":
    unittest.main()
