"""Isolated-lab unattended mode: physical profile runs without the H02 permit.

No real chamber: the real Vötsch adapter, G04 controller, G05 manual control,
G06 runner and G07 journal run against scripts/vt4011_simulator.py.
"""
from __future__ import annotations

import json
import time
import unittest
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from chamber_web.adapters.votsch import VotschBackend
from chamber_web.bootstrap import create_demo_control_services
from chamber_web.domain.chamber import ChamberSafetyError, UnsupportedCapability
from chamber_web.domain.profile import ParsedProfile, ProfileStep
from chamber_web.execution.profile_runner import TERMINAL, RunParameters, RunState
from chamber_web.hil.lab_mode import LAB_ACKNOWLEDGEMENT, LabMode, lab_mode_from_env
from chamber_web.hil.physical import HilAuthorization
from chamber_web.persistence.profiles import ProfileStore
from chamber_web.security.auth import Role, SecurityStore
from chamber_web.security.deployment import DeploymentError, DeploymentPolicy
from chamber_web.services.manual_control import ManualState
from chamber_web.services.profile_execution import ProfileExecutionService
from chamber_web.services.profile_runtime import ProfileRunRuntime
from scripts import hil_lab_acceptance
from scripts.vt4011_simulator import SimulatedVT4011

SERIAL = "SIM4011"
ADDRESS = "192.168.0.11"
PASSWORD = "LongUniqueSecret#123"


def _hil(low=10.0, high=40.0) -> HilAuthorization:
    return HilAuthorization("hil-votsch", ADDRESS, SERIAL, low, high)


class LabModeConfigurationTests(unittest.TestCase):
    def test_disabled_without_the_variable(self):
        self.assertIsNone(lab_mode_from_env({}, hil_present=True))

    def test_defaults(self):
        lab = lab_mode_from_env({"CHAMBER_LAB_MODE": LAB_ACKNOWLEDGEMENT}, hil_present=True)
        self.assertEqual((lab.measured_margin_c, lab.gradients), (5.0, True))

    def test_options(self):
        lab = lab_mode_from_env({"CHAMBER_LAB_MODE": LAB_ACKNOWLEDGEMENT,
                                 "CHAMBER_LAB_MEASURED_MARGIN_C": "2.5",
                                 "CHAMBER_LAB_GRADIENTS": "off"}, hil_present=True)
        self.assertEqual((lab.measured_margin_c, lab.gradients), (2.5, False))

    def test_misconfiguration_fails_closed(self):
        ack = {"CHAMBER_LAB_MODE": LAB_ACKNOWLEDGEMENT}
        bad = {
            "wrong acknowledgement": ({"CHAMBER_LAB_MODE": "yes"}, True),
            "no chamber authorization": (ack, False),
            "with an H02 permit": ({**ack, "CHAMBER_H02_PERMIT_FILE": "p.json"}, True),
            "margin too large": ({**ack, "CHAMBER_LAB_MEASURED_MARGIN_C": "50"}, True),
            "margin not numeric": ({**ack, "CHAMBER_LAB_MEASURED_MARGIN_C": "lots"}, True),
            "bad gradient switch": ({**ack, "CHAMBER_LAB_GRADIENTS": "maybe"}, True),
            "option without mode": ({"CHAMBER_LAB_GRADIENTS": "on"}, True),
        }
        for name, (env, hil_present) in bad.items():
            with self.subTest(name), self.assertRaises(ChamberSafetyError):
                lab_mode_from_env(env, hil_present=hil_present)


class LabNetworkModeTests(unittest.TestCase):
    def policy(self, **env):
        return DeploymentPolicy.from_env({"CHAMBER_NETWORK_MODE": "lab", **env})

    def test_specific_bind_is_plain_http_with_derived_origin(self):
        policy = self.policy(CHAMBER_BIND_HOST="192.168.10.5", CHAMBER_PORT="8090")
        self.assertTrue(policy.is_lab)
        self.assertFalse(policy.is_lan)  # no TLS, no https-only cookie
        self.assertIsNone(policy.certfile)
        self.assertIn("http://192.168.10.5:8090", policy.allowed_origins)
        self.assertIn("http://127.0.0.1:8090", policy.allowed_origins)
        self.assertTrue(policy.allows_client("192.168.10.77"))
        self.assertTrue(policy.allows_client("10.1.2.3"))
        self.assertFalse(policy.allows_client("8.8.8.8"))

    def test_all_interfaces_needs_the_address_the_laptop_opens(self):
        with self.assertRaises(DeploymentError):
            self.policy(CHAMBER_BIND_HOST="0.0.0.0")
        policy = self.policy(CHAMBER_BIND_HOST="0.0.0.0", CHAMBER_PORT="8090",
                             CHAMBER_PUBLIC_ORIGIN="http://192.168.10.5:8090,"
                                                   "http://10.0.0.2:8090")
        self.assertIn("http://10.0.0.2:8090", policy.allowed_origins)

    def test_unsafe_or_ambiguous_lab_configuration_refused(self):
        bad = {
            "public bind": {"CHAMBER_BIND_HOST": "8.8.8.8"},
            "https origin": {"CHAMBER_BIND_HOST": "0.0.0.0",
                             "CHAMBER_PUBLIC_ORIGIN": "https://192.168.10.5:8080"},
            "wrong port": {"CHAMBER_BIND_HOST": "0.0.0.0",
                           "CHAMBER_PUBLIC_ORIGIN": "http://192.168.10.5:9999"},
            "TLS in lab mode": {"CHAMBER_BIND_HOST": "192.168.10.5",
                                "CHAMBER_TLS_CERT": "c.pem", "CHAMBER_TLS_KEY": "k.pem"},
            "public client network": {"CHAMBER_BIND_HOST": "192.168.10.5",
                                      "CHAMBER_ALLOWED_CLIENT_CIDRS": "0.0.0.0/0"},
        }
        for name, env in bad.items():
            with self.subTest(name), self.assertRaises(DeploymentError):
                self.policy(**env)


class VotschGradientWriteTests(unittest.TestCase):
    def backend(self, **kwargs):
        driver = SimulatedVT4011(gradient_up=5.0, gradient_down=3.0)
        backend = VotschBackend("hil-votsch", ADDRESS, hil=_hil(),
                                hil_driver_factory=lambda: driver, **kwargs)
        backend.connect()
        return backend, driver

    def test_gradient_writes_disabled_by_default(self):
        backend, _ = self.backend()
        caps = backend.capabilities()
        self.assertFalse(caps.supports_ramp_up or caps.supports_ramp_down)
        with self.assertRaises(UnsupportedCapability):
            backend.set_ramp_up(1.0)

    def test_lab_gradient_writes_reach_driver_and_readback_ramp(self):
        backend, driver = self.backend(gradient_writes=True)
        caps = backend.capabilities()
        self.assertEqual(caps.ramp_up_range_c_per_min, (0.01, 5.0))
        self.assertEqual(caps.ramp_down_range_c_per_min, (0.01, 3.5))
        backend.set_ramp_up(1.5)
        backend.set_ramp_down(0.5)
        self.assertEqual((driver.gradient_up, driver.gradient_down), (1.5, 0.5))
        self.assertEqual(backend.capabilities().setpoint_readback_ramp_c_per_min, (1.5, 0.5))
        status = backend.read_status()
        self.assertEqual((status.gradient_up_c_per_min, status.gradient_down_c_per_min),
                         (1.5, 0.5))
        for bad in (0.0, 6.0, float("nan"), True):
            with self.subTest(bad), self.assertRaises(UnsupportedCapability):
                backend.set_ramp_up(bad)
        with self.assertRaises(UnsupportedCapability):
            backend.set_ramp_down(4.0)  # beyond the driver's 3.5 °C/min

    def test_gradient_writes_require_a_physical_authorization(self):
        with self.assertRaises(ChamberSafetyError):
            VotschBackend("hil-votsch", ADDRESS, gradient_writes=True)


class LabStack:
    """The server's composition bound to one simulated VT 4011."""

    def __init__(self, root: Path, *, hil=None, lab: LabMode | None = LabMode(),
                 driver=None, journal=True):
        self.driver = driver or SimulatedVT4011(gradient_up=60.0, gradient_down=60.0,
                                                tau_s=1.0)
        self.hil = hil or _hil()
        security = SecurityStore(root / "auth")
        security.bootstrap_admin("test_admin", "StrongAdminPassword#1")
        self.admin = security.login("test_admin", "StrongAdminPassword#1")
        security.create_user(self.admin.session, self.admin.csrf, "test_operator",
                             PASSWORD, Role.OPERATOR)
        self.operator = security.login("test_operator", PASSWORD)
        self.dashboard, self.manual = create_demo_control_services(
            security, self.hil, hil_driver_factory=lambda: self.driver,
            lease_directory=root / "leases",
            gradient_writes=lab is not None and lab.gradients)
        self.manager = self.dashboard.manager
        self.chamber_id = self.manual.chamber_id
        self.store = ProfileStore(root / "profiles.sqlite3")
        runtime = ProfileRunRuntime(root / "runs") if journal else None
        self.runs = root / "runs"
        self.service = ProfileExecutionService(
            self.manager, self.store, security, self.chamber_id, simulation=False,
            sink_factory=runtime.sink_factory if runtime else None,
            start_blocker=runtime.start_blocker if runtime else None,
            parameters=RunParameters(poll_s=0.2, max_gap_s=2, max_age_s=2, step_margin_s=5),
            manual_guard=self.manual._authorized, lab=lab)

    def profile(self, *steps: dict) -> str:
        built = tuple(ProfileStep(
            step=index + 1, enabled=True,
            target_temperature_c=Decimal(str(step["target"])),
            ramp_up_c_per_min=(None if step.get("up") is None else Decimal(str(step["up"]))),
            ramp_down_c_per_min=(None if step.get("down") is None
                                 else Decimal(str(step["down"]))),
            tolerance_c=Decimal("0.5"), stabilize_s=Decimal("0"),
            dwell_s=Decimal(str(step.get("dwell", 1))),
            reach_timeout_s=Decimal(str(step.get("reach", 120))), notes="",
        ) for index, step in enumerate(steps))
        return self.store.create_profile(
            self.chamber_id, ParsedProfile(steps=built, name="lab test")).profile_id

    def start(self, profile_id: str):
        return self.service.start(self.operator.session, self.operator.csrf, profile_id, 1)

    def drain(self, limit_s: float = 120.0) -> RunState:
        runner = self.service.runner
        deadline = time.monotonic() + limit_s
        while time.monotonic() < deadline:
            state = runner.advance()
            if state in TERMINAL:
                return state
            time.sleep(0.05)
        raise AssertionError("run did not finish")

    def close(self):
        runner = self.service.runner
        if runner is not None and runner.state in TERMINAL:
            runner.close()
        self.manager.disconnect(self.chamber_id)


class LabProfileExecutionTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def stack(self, **kwargs) -> LabStack:
        stack = LabStack(self.root, **kwargs)
        self.addCleanup(stack.close)
        return stack

    def test_physical_profile_runs_without_permit_witness_or_confirmation(self):
        stack = self.stack()
        view = stack.service.view(stack.operator.session)
        self.assertTrue(view.lab and view.can_start)
        self.assertFalse(view.simulation or view.supervised)
        profile_id = stack.profile({"target": 35}, {"target": 15}, {"target": 23})
        stack.start(profile_id)
        self.assertEqual(stack.drain(), RunState.COMPLETED, stack.service.runner.reason)
        self.assertFalse(stack.driver.is_running)
        sets = [call[1] for call in stack.driver.calls if call[0] == "set"]
        self.assertEqual(sets, [35.0, 15.0, 23.0])
        self.assertEqual(sum(call == ("start",) for call in stack.driver.calls), 1)
        # Recorded in the G07 journal like any other run.
        self.assertTrue(any(self.root.joinpath("runs").rglob("*")))

    def test_lab_run_clears_restart_lock_after_fresh_stopped_read(self):
        """A restart leaves UNKNOWN/latched; explicit Run may reconcile it."""
        stack = self.stack()
        actual_health = stack.manager.health
        locked = replace(actual_health(stack.chamber_id),
                         state="UNKNOWN", stop_latched=True,
                         reason="restart uncertainty")
        state = {"reconciled": False}
        def health(chamber_id):
            return actual_health(chamber_id) if state["reconciled"] else locked
        def reconcile(_chamber_id):
            state["reconciled"] = True
        with (patch.object(stack.manager, "health", side_effect=health),
              patch.object(stack.manager, "reconcile_stop", side_effect=reconcile)):
            view = stack.service.view(stack.operator.session)
            self.assertTrue(view.can_start)
            self.assertEqual(view.controller_state, "UNKNOWN")
            stack.start(stack.profile({"target": 23}))
            self.assertTrue(state["reconciled"])
            self.assertEqual(stack.drain(), RunState.COMPLETED,
                             stack.service.runner.reason)

    def test_admin_override_bypasses_foreign_lease_and_stop_latch(self):
        stack = self.stack()
        claimed = stack.manual.command(
            stack.operator.session, stack.operator.csrf, stack.chamber_id, "claim")
        self.assertEqual(claimed.state, ManualState.CONFIRMED)
        stack.manager.stop(stack.chamber_id)
        self.assertTrue(stack.manager.health(stack.chamber_id).stop_latched)
        view = stack.service.view(stack.admin.session)
        self.assertTrue(view.admin_override)
        self.assertTrue(view.can_start)
        stack.service.start(
            stack.admin.session, stack.admin.csrf,
            stack.profile({"target": 23}), 1)
        self.assertFalse(stack.manager.health(stack.chamber_id).stop_latched)
        self.assertEqual(stack.drain(), RunState.COMPLETED,
                         stack.service.runner.reason)

    def test_admin_override_can_take_over_an_already_running_chamber(self):
        stack = self.stack()
        token = stack.manager.claim_operator(stack.chamber_id, "pre-admin")
        stack.manager.start(stack.chamber_id, operator_token=token)
        stack.manager.release_operator(stack.chamber_id, token)
        self.assertEqual(stack.manager.health(stack.chamber_id).state, "RUNNING")
        self.assertTrue(stack.service.view(stack.admin.session).can_start)
        stack.service.start(
            stack.admin.session, stack.admin.csrf,
            stack.profile({"target": 23}), 1)
        self.assertEqual(stack.drain(), RunState.COMPLETED,
                         stack.service.runner.reason)

    def test_operator_cannot_bypass_a_foreign_manual_lease(self):
        stack = self.stack()
        security = stack.service._security
        security.create_user(
            stack.admin.session, stack.admin.csrf, "other_operator",
            PASSWORD, Role.OPERATOR)
        other = security.login("other_operator", PASSWORD)
        claimed = stack.manual.command(
            other.session, other.csrf, stack.chamber_id, "claim")
        self.assertEqual(claimed.state, ManualState.CONFIRMED)
        self.assertFalse(stack.service.view(stack.operator.session).can_start)
        with self.assertRaises(ChamberSafetyError):
            stack.start(stack.profile({"target": 23}))

    def test_lab_run_does_not_reconcile_a_faulted_chamber(self):
        stack = self.stack()
        faulted = replace(stack.manager.health(stack.chamber_id),
                          state="FAULT", stop_latched=True, reason="backend fault")
        with (patch.object(stack.manager, "health", return_value=faulted),
              patch.object(stack.manager, "reconcile_stop") as reconcile):
            self.assertFalse(stack.service.view(stack.operator.session).can_start)
            with self.assertRaises(ChamberSafetyError):
                stack.start(stack.profile({"target": 23}))
            reconcile.assert_not_called()

    def test_without_lab_mode_physical_profiles_stay_disabled(self):
        stack = self.stack(lab=None)
        self.assertFalse(stack.service.view(stack.operator.session).can_start)
        with self.assertRaises(ChamberSafetyError):
            stack.start(stack.profile({"target": 30}))
        self.assertNotIn(("start",), stack.driver.calls)

    def test_declared_gradients_are_written_verified_and_journaled(self):
        stack = self.stack()
        stack.start(stack.profile({"target": 25, "up": 5.0, "down": 3.5, "reach": 60}))
        self.assertEqual(stack.drain(), RunState.COMPLETED, stack.service.runner.reason)
        self.assertIn(("gradient_up", 5.0), stack.driver.calls)
        self.assertIn(("gradient_down", 3.5), stack.driver.calls)
        kinds = [event.kind for event in stack.service.runner.events]
        self.assertIn("GRADIENT_INTENT", kinds)
        self.assertLess(kinds.index("GRADIENT_INTENT"), kinds.index("SETPOINT_INTENT"))

    def test_gradients_refused_when_lab_gradients_are_off(self):
        stack = self.stack(lab=LabMode(gradients=False))
        with self.assertRaises(ChamberSafetyError):
            stack.start(stack.profile({"target": 25, "up": 1.0}))
        self.assertNotIn(("start",), stack.driver.calls)

    def test_reach_timeout_shorter_than_the_chamber_ramp_is_refused_before_motion(self):
        driver = SimulatedVT4011(gradient_up=5.0, gradient_down=3.0)
        stack = self.stack(driver=driver, hil=_hil(-40, 130))
        # 23 -> 130 °C at 5 °C/min takes 1284 s; 600 s cannot work.
        with self.assertRaisesRegex(ChamberSafetyError, "needs at least 1284 s"):
            stack.start(stack.profile({"target": 130, "reach": 600}))
        self.assertEqual([c for c in driver.calls if c[0] in ("set", "start")], [])

    def test_measured_overshoot_within_the_lab_margin_does_not_abort(self):
        for margin, expected in ((0.0, RunState.UNKNOWN), (5.0, RunState.COMPLETED)):
            with self.subTest(margin=margin):
                root = self.root / f"margin-{margin}"
                root.mkdir()
                # Chamber air starts above the 40 °C envelope edge it will hold.
                driver = SimulatedVT4011(ambient_c=41.5, gradient_up=60.0,
                                         gradient_down=60.0, tau_s=3.0)
                driver.temperature_set_point = 40.0
                stack = LabStack(root, driver=driver, lab=LabMode(measured_margin_c=margin))
                try:
                    stack.start(stack.profile({"target": 40, "dwell": 1}))
                    self.assertEqual(stack.drain(), expected, stack.service.runner.reason)
                    self.assertFalse(driver.is_running)
                finally:
                    stack.close()

    def test_lost_connection_mid_run_stops_and_fails_closed(self):
        stack = self.stack(journal=False)
        stack.start(stack.profile({"target": 35, "dwell": 30}))
        runner = stack.service.runner
        for _ in range(40):
            runner.advance()
            time.sleep(0.05)
        stack.driver.offline = True
        state = stack.drain()
        self.assertIn(state, (RunState.UNKNOWN, RunState.FAULT))


class ManualLongRampTests(unittest.TestCase):
    def test_full_range_manual_setpoint_confirms_while_ramping(self):
        with TemporaryDirectory() as tmp:
            driver = SimulatedVT4011(gradient_up=5.0, gradient_down=3.0)
            stack = LabStack(Path(tmp), driver=driver, hil=_hil(-40, 130))
            try:
                assert stack.manual.command(stack.operator.session, stack.operator.csrf,
                                            stack.chamber_id, "claim").state is (
                    ManualState.CONFIRMED)
                started = time.monotonic()
                outcome = stack.manual.command(
                    stack.operator.session, stack.operator.csrf, stack.chamber_id,
                    "set_temperature", target_c=-40.0)
                self.assertEqual(outcome.state, ManualState.CONFIRMED, outcome.message)
                self.assertIn("ramping toward -40", outcome.message)
                self.assertLess(time.monotonic() - started, 30)
                self.assertGreater(driver.temperature_set_point, -39.0)  # still ramping
            finally:
                stack.close()


class LabAcceptanceScriptTests(unittest.TestCase):
    def test_simulated_acceptance_passes_every_phase(self):
        with TemporaryDirectory() as tmp:
            evidence = Path(tmp) / "evidence"
            code = hil_lab_acceptance.main([
                "--simulate", "--sim-envelope", "15,35", "--evidence", str(evidence),
                "--gradient", "5", "--gradient-delta", "2", "--settle", "120",
                "--dwell", "2", "--stabilize", "2", "--manual-delta", "8"])
            summary = json.loads((evidence / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(code, 0, summary)
            self.assertEqual(
                {phase["name"]: phase["status"] for phase in summary["phases"]},
                dict.fromkeys(("identity", "guards", "manual", "cancel", "profile",
                               "gradient"), "PASSED"))
            self.assertEqual(summary["original"]["running"], False)
            self.assertTrue((evidence / "summary.md").is_file())

    def test_hardware_mode_refuses_without_lab_authorization(self):
        with TemporaryDirectory() as tmp:
            self.assertEqual(hil_lab_acceptance.main(["--evidence", tmp]), 2)



SERVER = r'''
import sys
from scripts.vt4011_simulator import SimulatedVT4011
from chamber_web.adapters import votsch

chamber = SimulatedVT4011()
votsch.VotschBackend._default_hil_driver = lambda self: chamber
from chamber_web import main
assert main.profile_execution_lab() is not None
from chamber_web.pages.profiles import get_profile_execution_service
assert get_profile_execution_service()._lab is not None
main.run()
'''


class LabServerBootTests(unittest.TestCase):
    def test_server_boots_in_lab_mode_over_plain_http(self):
        import os
        import socket
        import subprocess
        import sys
        import urllib.request

        root = Path(__file__).resolve().parents[1]
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        with TemporaryDirectory() as tmp:
            env = {k: v for k, v in os.environ.items()
                   if not k.startswith(("PYTEST", "NICEGUI_", "CHAMBER_"))}
            env.update({
                "HOME": tmp, "USERPROFILE": tmp, "PYTHONPATH": str(root),
                "CHAMBER_SECURITY_DIR": str(Path(tmp) / "security"),
                "CHAMBER_RUN_JOURNAL_DIR": str(Path(tmp) / "runs"),
                "CHAMBER_PORT": str(port), "CHAMBER_NETWORK_MODE": "lab",
                "CHAMBER_BIND_HOST": "127.0.0.1",
                "CHAMBER_HIL_ADDRESS": ADDRESS, "CHAMBER_HIL_EXPECTED_SERIAL": SERIAL,
                "CHAMBER_HIL_TEMP_MIN_C": "-40", "CHAMBER_HIL_TEMP_MAX_C": "130",
                "CHAMBER_HIL_ACK": "SUPERVISED-PHYSICAL-HIL",
                "CHAMBER_LAB_MODE": LAB_ACKNOWLEDGEMENT,
            })
            log = Path(tmp) / "server.log"
            with open(log, "w", encoding="utf-8") as output:
                server = subprocess.Popen([sys.executable, "-c", SERVER], cwd=root, env=env,
                                          stdout=output, stderr=subprocess.STDOUT)
                try:
                    body, deadline = "", time.monotonic() + 60
                    while time.monotonic() < deadline and server.poll() is None:
                        try:
                            with urllib.request.urlopen(
                                    f"http://127.0.0.1:{port}/login", timeout=2) as response:
                                body = response.read().decode("utf-8", "replace")
                            break
                        except Exception:
                            time.sleep(0.5)
                    self.assertIsNone(server.poll(), log.read_text(encoding="utf-8")[-3000:])
                    self.assertIn("isolated lab mode", body)
                finally:
                    server.terminate()
                    try:
                        server.wait(timeout=20)
                    except subprocess.TimeoutExpired:
                        server.kill()


if __name__ == "__main__":
    unittest.main()
