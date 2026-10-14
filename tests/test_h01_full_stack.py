"""H01 extended cross-layer acceptance: G08 auth -> G04 -> G06 (SIMULATED ONLY).

These tests intentionally never import the vendor driver or open a chamber socket.
Browser UI is covered separately; no test-only HTTP mutation endpoint is added.
"""
from __future__ import annotations

import tempfile
import time
import unittest
from decimal import Decimal
from pathlib import Path

from chamber_web.adapters.fake import FakeBackend
from chamber_web.domain.chamber import ChamberSafetyError
from chamber_web.domain.config import ChamberConfig
from chamber_web.domain.profile import ParsedProfile, ProfileStep
from chamber_web.execution.profile_runner import ProfileRunner, RunState, VirtualClock
from chamber_web.persistence.profiles import ProfileStore
from chamber_web.security.auth import AuthenticationError, AuthorizationError, Role, SecurityStore
from chamber_web.security.guards import AuthorizedChamber
from chamber_web.services.chamber_manager import ChamberManager


DEVICE = "h01-e2e"


class TracedFake(FakeBackend):
    """Only in-memory effects; a successful command is observable separately."""
    def __init__(self, chamber_id):
        super().__init__(chamber_id)
        self.commands = []
        self.fail_stop = False
        self.fail_readback = False

    def set_temperature(self, value):
        self.commands.append(("set", value))
        return super().set_temperature(value)

    def start(self):
        self.commands.append(("start",))
        return super().start()

    def stop(self):
        self.commands.append(("stop",))
        if self.fail_stop:
            raise TimeoutError("Injected ambiguous simulated STOP")
        return super().stop()

    def read_status(self):
        if self.fail_readback:
            raise TimeoutError("Injected readback loss")
        return super().read_status()


class EventCapture:
    def __init__(self):
        self.snapshots = []
        self.events = []

    def prepare(self, snapshot):
        self.snapshots.append(snapshot)

    def emit(self, event):
        self.events.append(event)


class H01FullStackTests(unittest.TestCase):
    def setUp(self):
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        self.root = Path(root.name)
        self.backend = TracedFake(DEVICE)
        self.manager = ChamberManager(
            [ChamberConfig(DEVICE, "fake")],
            backend_factory=lambda config, **kwargs: self.backend,
            lease_directory=self.root / "leases",
            allow_test_backend=True,
        )
        self.manager.connect(DEVICE)
        self.addCleanup(self.manager.disconnect, DEVICE)
        if self.manager.health(DEVICE).stop_latched:
            self.manager.reconcile_stop(DEVICE)
        self.security = SecurityStore(self.root / "security")
        self.security.bootstrap_admin("admin_h01", "StrongAdminPassword#1")
        self.admin = self.security.login("admin_h01", "StrongAdminPassword#1")
        self.security.create_user(
            self.admin.session, self.admin.csrf,
            "operator_a", "StrongOperatorPassword#2", Role.OPERATOR)
        self.security.create_user(
            self.admin.session, self.admin.csrf,
            "operator_b", "StrongOperatorPassword#3", Role.OPERATOR)
        self.security.create_user(
            self.admin.session, self.admin.csrf,
            "viewer_h01", "StrongViewerPassword#4", Role.VIEWER)
        self.alice = self.security.login("operator_a", "StrongOperatorPassword#2")
        self.bob = self.security.login("operator_b", "StrongOperatorPassword#3")
        self.viewer = self.security.login("viewer_h01", "StrongViewerPassword#4")
        self.web = AuthorizedChamber(self.manager, self.security)

    def execute(self, tokens, command, *args, **kwargs):
        return self.web.execute(tokens.session, tokens.csrf, DEVICE, command, *args, **kwargs)

    def assert_no_commands(self):
        self.assertEqual(self.backend.commands, [], "Denied action reached chamber backend")

    def test_anonymous_and_viewer_control_denied_without_dispatch(self):
        for tokens in (None, self.viewer):
            for command in ("claim_operator", "set_temperature", "start", "stop"):
                with self.subTest(tokens=tokens, command=command):
                    session = tokens.session if tokens else None
                    csrf = tokens.csrf if tokens else None
                    with self.assertRaises((AuthorizationError, AuthenticationError)):
                        self.web.execute(session, csrf, DEVICE, command, 25 if command == "set_temperature" else None)
        self.assert_no_commands()

    def test_forged_csrf_refused_before_dispatch(self):
        with self.assertRaises((AuthorizationError, AuthenticationError)):
            self.web.execute(self.alice.session, "invalid-csrf", DEVICE, "stop")
        self.assert_no_commands()

    def test_unknown_command_denied_before_dispatch(self):
        with self.assertRaises(AuthorizationError):
            self.execute(self.admin, "__getattribute__", "stop")
        self.assert_no_commands()

    def test_wrong_chamber_and_invalid_setpoint_never_write(self):
        token = self.execute(self.alice, "claim_operator")
        with self.assertRaises(ChamberSafetyError):
            self.web.execute(self.alice.session, self.alice.csrf, "other", "start", operator_token=token)
        for value in (float("nan"), float("inf"), -9999, 9999, "30", True):
            with self.subTest(value=value):
                with self.assertRaises((ChamberSafetyError, ValueError, TypeError)):
                    self.execute(self.alice, "set_temperature", value, operator_token=token)
        self.assert_no_commands()

    def test_multi_operator_lease_and_authorized_non_owner_stop(self):
        token = self.execute(self.alice, "claim_operator")
        with self.assertRaises(ChamberSafetyError):
            self.execute(self.bob, "claim_operator")
        with self.assertRaises(AuthorizationError):
            self.execute(self.bob, "start", operator_token=token)
        self.execute(self.alice, "set_temperature", 27, operator_token=token)
        self.execute(self.alice, "start", operator_token=token)
        self.execute(self.bob, "stop")
        self.assertEqual(self.backend.commands, [("set", 27.0), ("start",), ("stop",)])
        self.assertEqual(self.manager.health(DEVICE).state, "VERIFIED_STOPPED")
        self.assertTrue(self.manager.health(DEVICE).stop_latched)
        with self.assertRaises(ChamberSafetyError):
            self.execute(self.alice, "set_temperature", 28, operator_token=token)
        self.assertEqual(len(self.backend.commands), 3)

    def test_expired_revoked_session_cannot_mutate(self):
        token = self.execute(self.alice, "claim_operator")
        self.security.logout(self.alice.session)
        with self.assertRaises(AuthenticationError):
            self.execute(self.alice, "start", operator_token=token)
        self.assert_no_commands()

    def test_ambiguous_stop_never_claims_stopped(self):
        token = self.execute(self.alice, "claim_operator")
        self.execute(self.alice, "start", operator_token=token)
        self.backend.fail_stop = True
        with self.assertRaises(Exception):
            self.execute(self.bob, "stop")
        self.assertTrue(self.manager.health(DEVICE).stop_latched)
        self.assertIn(self.manager.health(DEVICE).state, ("UNKNOWN", "FAULT"))
        self.assertNotEqual(self.manager.health(DEVICE).state, "VERIFIED_STOPPED")
        with self.assertRaises(ChamberSafetyError):
            self.execute(self.alice, "start", operator_token=token)
        self.assertEqual(self.backend.commands, [("start",), ("stop",)])

    def test_missing_readback_is_not_setpoint_success(self):
        token = self.execute(self.alice, "claim_operator")
        self.backend.fail_readback = True
        with self.assertRaises(Exception):
            self.execute(self.alice, "set_temperature", 28, operator_token=token)
        self.assertTrue(self.manager.health(DEVICE).stop_latched)
        self.assertNotEqual(self.manager.health(DEVICE).state, "VERIFIED_STOPPED")
        self.assertEqual(self.backend.commands, [("set", 28.0)])

    def test_profile_runner_via_manager_records_ordered_evidence(self):
        store = ProfileStore(self.root / "profiles.sqlite3")
        profile = ParsedProfile((ProfileStep(
            1, True, Decimal("25"), None, None,
            Decimal("1"), Decimal("0"), Decimal("0"), Decimal("20"), "H01",
        ),), name="H01 browser-equivalent run")
        revision = store.create_profile(DEVICE, profile)
        sink = EventCapture()
        clock = VirtualClock()
        # This authorizer is injected by the test only. Browser actions must use G08.
        runner = ProfileRunner(
            self.manager, store, authorize=lambda action, chamber_id: "test-operator",
            sink=sink, clock=clock,
        )
        self.addCleanup(runner.close)
        prepared = runner.start(DEVICE, revision.profile_id, revision=1)
        self.assertEqual(self.backend.commands, [], "PREPARED must not dispatch")
        for _ in range(120):
            runner.advance()
            if runner.state in (RunState.COMPLETED, RunState.CANCELLED, RunState.FAULT, RunState.UNKNOWN):
                break
            time.sleep(0.01)  # bounded async STOP worker
        self.assertEqual(runner.state, RunState.COMPLETED, runner.reason)
        self.assertEqual(prepared.run_id, sink.snapshots[0].run_id)
        kinds = [event.kind for event in sink.events]
        self.assertLess(kinds.index("START_INTENT"), kinds.index("SETPOINT_INTENT"))
        self.assertLess(kinds.index("START_INTENT"), kinds.index("STOP_INTENT"))
        self.assertEqual(kinds[-1], "TERMINAL")
        self.assertEqual([e.sequence for e in sink.events], list(range(1, len(sink.events) + 1)))
        self.assertEqual(self.backend.commands, [("set", 25.0), ("start",), ("stop",)])
        self.assertTrue(self.manager.health(DEVICE).stop_latched)
        self.assertFalse(self.backend._running)

    def test_nonsimulated_backend_refused_before_connect(self):
        # Independent controller object, not connected: inspect pre-I/O guard.
        from chamber_web.services.chamber_controller import ChamberController

        class Forbidden(TracedFake):
            simulation_only = False

            def connect(self):
                raise AssertionError("A physical connect was dispatched!")

        controller = ChamberController(
            ChamberConfig("forbidden", "fake"), Forbidden("forbidden"),
            lease_directory=self.root / "forbidden",
        )
        with self.assertRaisesRegex(ChamberSafetyError, "Physical hardware I/O DISABLED"):
            controller.connect("forbidden")


if __name__ == "__main__":
    unittest.main()
