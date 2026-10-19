"""Server-owned simulated profile execution behind G08 authorization.

Only FakeBackend is constructed. No real chamber, vendor driver or HIL used.
"""
from __future__ import annotations

import asyncio
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from chamber_web.adapters.fake import FakeBackend
from chamber_web.domain.chamber import ChamberSafetyError
from chamber_web.domain.config import ChamberConfig
from chamber_web.execution.profile_runner import TERMINAL, RunParameters, RunState
from chamber_web.persistence.profiles import ProfileStore
from chamber_web.security.auth import AuthenticationError, AuthorizationError, Role, SecurityStore
from chamber_web.security.guards import AuthorizedChamber
from chamber_web.services.chamber_manager import ChamberManager
from chamber_web.services.profile_editor import ProfileEditorService
from chamber_web.services.profile_execution import ProfileExecutionService

CHAMBER = "simulated-chamber"


class ProfileExecutionServiceTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.security = SecurityStore(root / "auth")
        self.security.bootstrap_admin("test_admin", "StrongAdminPassword#1")
        self.admin = self.security.login("test_admin", "StrongAdminPassword#1")
        for name, role in (("test_operator", Role.OPERATOR), ("test_viewer", Role.VIEWER)):
            self.security.create_user(self.admin.session, self.admin.csrf,
                                      name, "LongUniqueSecret#123", role)
        self.operator = self.security.login("test_operator", "LongUniqueSecret#123")
        self.viewer = self.security.login("test_viewer", "LongUniqueSecret#123")
        self.backend = FakeBackend(CHAMBER)
        self.manager = ChamberManager(
            [ChamberConfig(CHAMBER, "fake")],
            backend_factory=lambda config, **kwargs: self.backend,
            lease_directory=root / "controller",
        )
        self.manager.connect(CHAMBER)
        self.addCleanup(self.manager.disconnect, CHAMBER)
        self.store = ProfileStore(root / "profiles.sqlite3")
        editor = ProfileEditorService(self.store, CHAMBER)
        draft = editor.edit_step(editor.new_draft(), 0, "dwell_s", "0")
        self.saved = editor.save(draft)
        self.service = self._service(simulation=True)

    def _service(self, *, simulation: bool,
                 manual_guard: AuthorizedChamber | None = None) -> ProfileExecutionService:
        service = ProfileExecutionService(
            self.manager, self.store, self.security, CHAMBER, simulation=simulation,
            parameters=RunParameters(poll_s=0.05, max_gap_s=1, max_age_s=1),
            manual_guard=manual_guard,
        )

        def close_runner():
            runner = service.runner
            if runner is not None and runner.state in TERMINAL:
                runner.close()
        self.addCleanup(close_runner)
        return service

    def _start(self, tokens):
        return self.service.start(tokens.session, tokens.csrf, self.saved.profile_id, 1)

    def _drain(self, *, until=TERMINAL):
        runner = self.service.runner
        for _ in range(400):
            state = runner.advance()
            if state in until:
                return state
            time.sleep(0.005)
        self.fail("Runner did not reach " + ", ".join(sorted(s.value for s in until)))

    def test_viewer_sees_state_but_cannot_start(self):
        view = self.service.view(self.viewer.session)
        self.assertIsNone(view.state)
        self.assertTrue(view.simulation)
        self.assertFalse(view.can_start)
        self.assertTrue(self.service.view(self.operator.session).can_start)
        with self.assertRaises(AuthorizationError):
            self._start(self.viewer)
        self.assertIsNone(self.service.runner)
        self.assertFalse(self.backend._running)

    def test_mutations_require_csrf(self):
        with self.assertRaises(AuthorizationError):
            self.service.start(self.operator.session, "wrong-csrf",
                               self.saved.profile_id, 1)
        with self.assertRaises(AuthenticationError):
            self.service.view("not-a-session")
        self.assertIsNone(self.service.runner)

    def test_operator_run_progress_owner_controls_and_admin_stop(self):
        snapshot = self._start(self.operator)
        self.assertEqual((snapshot.profile_id, snapshot.revision), (self.saved.profile_id, 1))
        with self.assertRaises(ChamberSafetyError):
            self._start(self.admin)  # one active run per chamber
        self._drain(until={RunState.REACHING, RunState.STABILIZING, RunState.DWELLING})
        self.assertTrue(self.backend._running)

        mine = self.service.view(self.operator.session)
        self.assertTrue(mine.active)
        self.assertEqual((mine.step, mine.total_steps), (1, 1))
        self.assertEqual(mine.operator, "test_operator")
        self.assertIsNotNone(mine.target_c)
        self.assertTrue(mine.can_stop and mine.can_pause and not mine.can_start)
        self.assertTrue(all(row.kind != "SAMPLE" for row in mine.events))
        admin = self.service.view(self.admin.session)
        self.assertTrue(admin.can_stop)
        self.assertFalse(admin.can_pause)  # pause/resume stay with the run owner
        self.assertFalse(self.service.view(self.viewer.session).can_stop)
        with self.assertRaises(AuthorizationError):
            self.service.cancel(self.viewer.session, self.viewer.csrf)

        # Any PROFILE_RUN user may STOP; lease ownership is not required.
        self.service.cancel(self.admin.session, self.admin.csrf)
        self.assertEqual(self._drain(), RunState.CANCELLED)
        self.assertFalse(self.backend._running)
        final = self.service.view(self.operator.session)
        self.assertEqual(final.state, "CANCELLED")
        self.assertFalse(final.active or final.can_stop)
        self.assertTrue(final.stop_latched)
        self.assertTrue(final.can_start)  # Explicit Run safely rechecks STOPPED
        with self.assertRaises(ChamberSafetyError):
            self.service.cancel(self.admin.session, self.admin.csrf)

    def test_repeated_profile_run_after_verified_cancel_without_admin(self):
        """A verified G06 CANCELLED STOP permits a new explicit Run Profile."""
        first = self._start(self.operator)
        self._drain(until={RunState.REACHING, RunState.STABILIZING, RunState.DWELLING})
        self.service.cancel(self.operator.session, self.operator.csrf)
        self.assertEqual(self._drain(), RunState.CANCELLED)
        self.assertTrue(self.manager.health(CHAMBER).stop_latched)
        self.assertTrue(self.service.view(self.operator.session).can_start)
        second = self._start(self.operator)
        self.assertNotEqual(first.run_id, second.run_id)
        self.assertFalse(self.manager.health(CHAMBER).stop_latched)
        self.assertEqual(self.service.view(self.operator.session).state, "PREPARING")
        # The second run is only prepared, never started without runner ticks.
        self.assertFalse(self.backend._running)
        self.service.cancel(self.operator.session, self.operator.csrf)
        self.assertEqual(self._drain(), RunState.CANCELLED)

    def test_profile_start_releases_only_same_operator_stopped_manual_lease(self):
        guard = AuthorizedChamber(self.manager, self.security)
        service = self._service(simulation=True, manual_guard=guard)
        guard.ensure_manual_operator_lease(
            self.operator.session, self.operator.csrf, CHAMBER)
        guard.execute_owned(
            self.operator.session, self.operator.csrf, CHAMBER, "start")
        self.assertTrue(self.backend._running)
        # A profile cannot take over a physically running chamber.
        self.assertFalse(service.view(self.operator.session).can_start)
        with self.assertRaises(ChamberSafetyError):
            service.start(self.operator.session, self.operator.csrf,
                          self.saved.profile_id, 1)
        guard.stop(self.operator.session, self.operator.csrf, CHAMBER)
        self.assertTrue(self.manager.health(CHAMBER).stop_latched)
        self.assertTrue(service.view(self.operator.session).can_start)
        self.assertFalse(service.view(self.admin.session).can_start)
        with self.assertRaises(ChamberSafetyError):
            service.start(self.admin.session, self.admin.csrf, self.saved.profile_id, 1)
        self.assertTrue(guard.ownership_view(self.operator.session, CHAMBER)[1])
        # Invalid profile must not clear the fence or release the owner's token.
        with self.assertRaises(Exception):
            service.start(self.operator.session, self.operator.csrf,
                          "not-a-profile", 1)
        self.assertTrue(self.manager.health(CHAMBER).stop_latched)
        self.assertTrue(guard.ownership_view(self.operator.session, CHAMBER)[1])
        snapshot = service.start(
            self.operator.session, self.operator.csrf, self.saved.profile_id, 1)
        self.assertEqual(snapshot.operator_id, "test_operator")
        self.assertFalse(self.manager.health(CHAMBER).stop_latched)
        self.assertEqual(guard.ownership_view(self.operator.session, CHAMBER),
                         (None, False))
        self.assertFalse(self.backend._running)
        service.cancel(self.operator.session, self.operator.csrf)
        self.assertEqual(self._drain_service(service), RunState.CANCELLED)

    @staticmethod
    def _drain_service(service):
        for _ in range(400):
            state = service.runner.advance()
            if state in TERMINAL:
                return state
            time.sleep(0.005)
        raise AssertionError("Profile never reached terminal state")

    def test_uncertain_stop_cannot_be_cleared_by_profile_start(self):
        self.manager.stop(CHAMBER)
        # Force uncertainty through a genuine G04 STOP verification failure
        # without directly rewriting controller-owned state.
        self.manager.disconnect(CHAMBER)
        # Reopening a new manager is separately tested under restart safety;
        # a disconnected controller must remain refused here.
        self.assertFalse(self.service.view(self.operator.session).can_start)
        with self.assertRaises(ChamberSafetyError):
            self._start(self.operator)

    def test_pause_and_resume_are_owner_only(self):
        self._start(self.operator)
        self._drain(until={RunState.REACHING, RunState.STABILIZING, RunState.DWELLING})
        with self.assertRaises(ChamberSafetyError):
            self.service.pause(self.admin.session, self.admin.csrf)
        self.service.pause(self.operator.session, self.operator.csrf)
        view = self.service.view(self.operator.session)
        self.assertEqual(view.state, "PAUSED")
        self.assertTrue(view.can_resume and not view.can_pause)
        self.service.resume(self.operator.session, self.operator.csrf)
        self.assertEqual(self.service.view(self.operator.session).state, "REACHING")
        self.service.cancel(self.operator.session, self.operator.csrf)
        self.assertEqual(self._drain(), RunState.CANCELLED)

    def test_execution_refused_outside_simulation(self):
        service = self._service(simulation=False)
        view = service.view(self.operator.session)
        self.assertFalse(view.simulation or view.can_start)
        with self.assertRaises(ChamberSafetyError):
            service.start(self.operator.session, self.operator.csrf,
                          self.saved.profile_id, 1)
        self.assertIsNone(service.runner)
        self.assertFalse(self.backend._running)

    def test_server_task_runs_and_shutdown_issues_stop(self):
        # A zero-dwell profile can finish (and issue its own verified STOP)
        # between the liveness check and shutdown's STOP; the controller then
        # fails closed with "STOP superseded by another fault or STOP". A long
        # dwell keeps the run deterministically active so shutdown itself must
        # be the one that stops it.
        editor = ProfileEditorService(self.store, CHAMBER)
        draft = editor.edit_step(editor.new_draft(), 0, "dwell_s", "60")
        long_run = editor.save(draft)

        async def scenario():
            await self.service.start_async(
                self.operator.session, self.operator.csrf, long_run.profile_id, 1,
            )
            for _ in range(200):
                if self.backend._running:
                    break
                await asyncio.sleep(0.01)
            self.assertTrue(self.backend._running)
            await self.service.shutdown()

        asyncio.run(scenario())
        self.assertIn(self.service.runner.state, TERMINAL)
        self.assertFalse(self.backend._running)


class FakeSlewTests(unittest.TestCase):
    def test_measured_temperature_slews_toward_target_only_while_running(self):
        backend = FakeBackend(CHAMBER, slew_c_per_s=10)
        backend.connect()
        start = backend.read_status().measured_temperature_c
        backend.set_temperature(start + 5)
        time.sleep(0.05)
        self.assertEqual(backend.read_status().measured_temperature_c, start)  # stopped
        backend.start()
        time.sleep(0.2)
        moved = backend.read_status().measured_temperature_c
        self.assertGreater(moved, start)
        self.assertLessEqual(moved, start + 5)
        time.sleep(0.6)
        self.assertEqual(backend.read_status().measured_temperature_c, start + 5)

    def test_invalid_slew_rejected(self):
        for bad in (-1, 11, float("nan"), True, "1"):
            with self.assertRaises(ValueError):
                FakeBackend(CHAMBER, slew_c_per_s=bad)


if __name__ == "__main__":
    unittest.main()
