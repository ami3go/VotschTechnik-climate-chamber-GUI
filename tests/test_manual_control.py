"""G05 manual-control simulation-only safety, authorization and concurrency tests."""
from __future__ import annotations

import asyncio
import tempfile
import threading
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from chamber_web.adapters.fake import FakeBackend
from chamber_web.adapters.alternate_stub import AlternateStubBackend
from chamber_web.adapters.votsch import VotschBackend
from chamber_web.domain.chamber import (
    ChamberCapabilities, ChamberSafetyError, ReadingQuality,
)
from chamber_web.domain.config import ChamberConfig
from chamber_web.security.auth import (
    AuthenticationError, AuthorizationError, Role, SecurityStore,
)
from chamber_web.security.guards import AuthorizedChamber
from chamber_web.services.chamber_manager import ChamberManager
from chamber_web.services.dashboard import DashboardService
from chamber_web.services.manual_control import ManualControlService, ManualState


class InjectedVotschDriver:
    test_system_type = "VT4011-INJECTED-NO-SOCKET"
    serial_number = "INJECTED-001"

    def __init__(self):
        self.temperature_measured = 23.0
        self.temperature_set_point = 23.0
        self.is_running = False

    def start(self):
        self.is_running = True

    def stop(self):
        self.is_running = False

    def disconnect(self):
        pass


class BlockingFakeBackend(FakeBackend):
    def __init__(self, chamber_id):
        super().__init__(chamber_id)
        self.entered = threading.Event()
        self.proceed = threading.Event()

    def set_temperature(self, target_c):
        self.entered.set()
        if not self.proceed.wait(3):
            raise TimeoutError("controlled test delay")
        super().set_temperature(target_c)


class UnconfirmedFakeBackend(FakeBackend):
    def set_temperature(self, target_c):
        # Write deliberately ignored: G04 must reject fake success.
        pass


class ManualControlTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.clock = [10_000.0]
        self.security = SecurityStore(
            self.root / "security", clock=lambda: self.clock[0],
            idle_timeout_s=60, absolute_timeout_s=600)
        self.security.bootstrap_admin("admin_1", "StrongAdminPassword#1")
        self.admin = self.security.login("admin_1", "StrongAdminPassword#1")
        self.security.create_user(
            self.admin.session, self.admin.csrf, "operator_1",
            "StrongOperatorPassword#2", Role.OPERATOR)
        self.security.create_user(
            self.admin.session, self.admin.csrf, "operator_2",
            "StrongOperatorPassword#2", Role.OPERATOR)
        self.security.create_user(
            self.admin.session, self.admin.csrf, "viewer_1",
            "StrongOperatorPassword#2", Role.VIEWER)
        self.op = self.security.login("operator_1", "StrongOperatorPassword#2")
        self.op2 = self.security.login("operator_2", "StrongOperatorPassword#2")
        self.viewer = self.security.login("viewer_1", "StrongOperatorPassword#2")
        self.managers = []

    def make_service(self, backend_factory=None, backend_id="fake", suffix="one"):
        chamber_id = "sim-" + suffix
        config = ChamberConfig(
            chamber_id, backend_id, "192.0.2.1" if backend_id == "votsch" else None)
        factory = backend_factory or (
            lambda cfg, allow_test_backend=False: FakeBackend(cfg.chamber_id))
        mgr = ChamberManager(
            [config], backend_factory=factory,
            lease_directory=self.root / ("lease-" + suffix), io_timeout_s=2.0)
        mgr.connect(chamber_id)
        self.managers.append(mgr)
        dashboard = DashboardService(mgr, chamber_id)
        asyncio.run(dashboard.poll_once())
        facade = AuthorizedChamber(mgr, self.security)
        service = ManualControlService(mgr, dashboard, facade,
                                       self.security, chamber_id)
        return service, mgr, dashboard

    def tearDown(self):
        for mgr in reversed(self.managers):
            try:
                mgr.disconnect(mgr.configured_ids()[0])
            except Exception:
                pass

    @staticmethod
    def send(service, tokens, action, **kwargs):
        return service.command(
            tokens.session, tokens.csrf, service.chamber_id, action, **kwargs)

    def test_sequential_three_backend_conformance(self):
        factories = (
            ("fake", lambda cfg, allow_test_backend=False: FakeBackend(cfg.chamber_id)),
            ("alternate_stub", lambda cfg, allow_test_backend=False:
             AlternateStubBackend(cfg.chamber_id)),
            ("votsch", lambda cfg, allow_test_backend=False:
             VotschBackend(cfg.chamber_id, cfg.address,
                           mock_driver_factory=InjectedVotschDriver)),
        )
        for index, (backend_id, factory) in enumerate(factories):
            with self.subTest(backend_id=backend_id):
                service, mgr, dash = self.make_service(
                    factory, backend_id=backend_id, suffix=str(index))
                self.assertTrue(service.view(self.viewer.session, service.chamber_id).dashboard.identity.is_simulation)
                self.assertEqual(self.send(service, self.op, "claim").state,
                                 ManualState.CONFIRMED)
                self.assertEqual(self.send(service, self.op, "set_temperature",
                                           target_c=40).state, ManualState.CONFIRMED)
                self.assertEqual(self.send(service, self.op, "start").state,
                                 ManualState.CONFIRMED)
                self.assertEqual(self.send(service, self.admin, "stop").state,
                                 ManualState.CONFIRMED)
                self.assertTrue(mgr.health(service.chamber_id).stop_latched)
                self.assertEqual(self.send(service, self.op, "start").state,
                                 ManualState.REJECTED)
                self.assertEqual(self.send(service, self.admin, "reconcile").state,
                                 ManualState.CONFIRMED)
                self.assertEqual(self.send(service, self.op, "release").state,
                                 ManualState.CONFIRMED)
                self.assertFalse(dash.view().identity is None)
                self.assertFalse(mgr.capabilities(service.chamber_id).supports_ramp_up)
                mgr.disconnect(service.chamber_id)
                self.managers.remove(mgr)

    def test_concurrent_operator_claim_and_admin_handover(self):
        service, _, _ = self.make_service()
        barrier = threading.Barrier(3)
        results = []

        def attempt(tokens):
            barrier.wait()
            results.append(self.send(service, tokens, "claim").state)

        threads = [threading.Thread(target=attempt, args=(who,))
                   for who in (self.op, self.op2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=4)
            self.assertFalse(thread.is_alive())
        self.assertEqual(results.count(ManualState.CONFIRMED), 1)
        self.assertEqual(results.count(ManualState.REJECTED), 1)
        with self.assertRaises(AuthorizationError):
            self.send(service, self.op, "handover")
        self.assertEqual(self.send(service, self.admin, "handover").state,
                         ManualState.CONFIRMED)
        self.assertTrue(service.view(self.admin.session, service.chamber_id).owned_by_actor)
        self.assertEqual(self.send(service, self.admin, "release").state,
                         ManualState.CONFIRMED)

    def test_admin_expiry_during_handover_preserves_existing_owner(self):
        service, _, _ = self.make_service()
        self.assertEqual(self.send(service, self.op, "claim").state,
                         ManualState.CONFIRMED)
        facade = service._authorized
        original_authorize = facade.authorize
        validated = [0]

        def expire_after_initial_handover_check(session, csrf, permission, *,
                                                 chamber_id=None):
            actor = original_authorize(session, csrf, permission,
                                       chamber_id=chamber_id)
            validated[0] += 1
            if validated[0] == 2:
                # Session expires after outer service + inner handover checks,
                # but before the G04 lease release/claim transition.
                self.clock[0] += 61
            return actor

        facade.authorize = expire_after_initial_handover_check
        outcome = self.send(service, self.admin, "handover")
        self.assertEqual(outcome.state, ManualState.REJECTED)
        self.assertIn("operator_1", facade._token_names.values())

    def test_anonymous_viewer_csrf_revoked_and_wrong_identity(self):
        service, _, _ = self.make_service()
        with self.assertRaises(AuthenticationError):
            service.command(None, None, service.chamber_id, "stop")
        with self.assertRaises(AuthorizationError):
            self.send(service, self.viewer, "claim")
        with self.assertRaises(AuthorizationError):
            self.send(service, self.viewer, "set_temperature", target_c=25)
        with self.assertRaises(AuthorizationError):
            self.send(service, self.viewer, "stop")
        with self.assertRaises(AuthorizationError):
            service.command(self.op.session, "forged", service.chamber_id, "stop")
        with self.assertRaises(ChamberSafetyError):
            service.command(self.op.session, self.op.csrf, "wrong-device", "stop")
        self.security.logout(self.op.session)
        with self.assertRaises(AuthenticationError):
            self.send(service, self.op, "claim")
        self.assertTrue(any(row[1] == "DENIED" for row in self.security.audit_records()))

    def test_bad_numbers_and_capability_rejection(self):
        service, mgr, _ = self.make_service()
        self.assertEqual(self.send(service, self.op, "claim").state,
                         ManualState.CONFIRMED)
        for value in (float("nan"), float("inf"), float("-inf"),
                      True, None, "25", -1000, 2000):
            with self.subTest(value=value):
                self.assertEqual(self.send(service, self.op, "set_temperature",
                                           target_c=value).state, ManualState.REJECTED)
        with self.assertRaises(ChamberSafetyError):
            service.unsupported_operation(
                self.op.session, self.op.csrf, service.chamber_id, "ramp_up")
        self.assertFalse(mgr.capabilities(service.chamber_id).supports_ramp_up)
        self.assertFalse(mgr.capabilities(service.chamber_id).supports_ramp_down)

    def test_missing_capabilities_disable_start_setpoint_and_presets(self):
        def factory(cfg, allow_test_backend=False):
            backend = FakeBackend(cfg.chamber_id)
            backend._caps = ChamberCapabilities(-10, 40, False, False, False)
            return backend

        service, mgr, dashboard = self.make_service(factory)
        asyncio.run(dashboard.poll_once())
        view = service.view(self.op.session, service.chamber_id)
        self.assertFalse(view.can_start)
        self.assertFalse(view.can_set_target)
        self.assertEqual(view.presets_c, (0.0, 23.0, 40.0))
        self.assertEqual(self.send(service, self.op, "claim").state,
                         ManualState.CONFIRMED)
        self.assertEqual(self.send(service, self.op, "set_temperature",
                                   target_c=24).state, ManualState.REJECTED)
        self.assertEqual(self.send(service, self.op, "start").state,
                         ManualState.REJECTED)
        self.assertEqual(mgr.health(service.chamber_id).state, "VERIFIED_STOPPED")

    def test_non_simulated_backend_is_rejected_before_connect(self):
        class NotSimulation(FakeBackend):
            simulation_only = False

        config = ChamberConfig("nonphysical", "fake")
        manager = ChamberManager(
            [config], backend_factory=lambda cfg, allow_test_backend=False:
            NotSimulation(cfg.chamber_id),
            lease_directory=self.root / "rejected-physical")
        with self.assertRaises(ChamberSafetyError):
            manager.connect(config.chamber_id)

    def test_revoked_or_expired_session_and_disconnected_backend(self):
        instances = []
        def factory(cfg, allow_test_backend=False):
            backend = FakeBackend(cfg.chamber_id)
            instances.append(backend)
            return backend

        service, manager, _ = self.make_service(factory)
        self.assertEqual(self.send(service, self.op, "claim").state,
                         ManualState.CONFIRMED)
        instances[0].disconnect()
        self.assertIn(self.send(service, self.op, "start").state,
                      (ManualState.UNKNOWN, ManualState.FAULT))
        self.assertTrue(manager.health(service.chamber_id).stop_latched)
        self.clock[0] += 61
        with self.assertRaises(AuthenticationError):
            self.send(service, self.op, "stop")

    def test_changed_device_identity_blocks_writes(self):
        instances = []
        def factory(cfg, allow_test_backend=False):
            backend = FakeBackend(cfg.chamber_id)
            instances.append(backend)
            return backend

        service, manager, _ = self.make_service(factory)
        self.assertEqual(self.send(service, self.op, "claim").state,
                         ManualState.CONFIRMED)
        instances[0]._identity = replace(instances[0]._identity, chamber_id="other")
        self.assertIn(self.send(service, self.op, "set_temperature",
                                target_c=24).state, (ManualState.UNKNOWN, ManualState.FAULT))
        self.assertTrue(manager.health(service.chamber_id).stop_latched)

    def test_readback_mismatch_transitions_unknown_and_stop_still_possible(self):
        service, mgr, _ = self.make_service(
            lambda cfg, allow_test_backend=False: UnconfirmedFakeBackend(cfg.chamber_id))
        self.assertEqual(self.send(service, self.op, "claim").state,
                         ManualState.CONFIRMED)
        result = self.send(service, self.op, "set_temperature", target_c=50)
        self.assertEqual(result.state, ManualState.UNKNOWN)
        self.assertTrue(mgr.health(service.chamber_id).stop_latched)
        self.assertEqual(self.send(service, self.op2, "stop").state,
                         ManualState.CONFIRMED)
        self.assertEqual(self.send(service, self.admin, "reconcile").state,
                         ManualState.CONFIRMED)

    def test_followup_readback_drift_is_unknown_not_success(self):
        class DriftFake(FakeBackend):
            def __init__(self, chamber_id):
                super().__init__(chamber_id)
                self.after_write = None
                self.reads_after_write = 0

            def set_temperature(self, target_c):
                super().set_temperature(target_c)
                self.after_write = target_c
                self.reads_after_write = 0

            def read_status(self):
                sample = super().read_status()
                if self.after_write is not None:
                    self.reads_after_write += 1
                    if self.reads_after_write >= 2:
                        return replace(sample, setpoint_temperature_c=25.0)
                return sample

        service, _, _ = self.make_service(
            lambda cfg, allow_test_backend=False: DriftFake(cfg.chamber_id))
        self.assertEqual(self.send(service, self.op, "claim").state,
                         ManualState.CONFIRMED)
        outcome = self.send(service, self.op, "set_temperature", target_c=40.0)
        self.assertEqual(outcome.state, ManualState.UNKNOWN)
        self.assertIn("unverified", outcome.message.lower())

    def test_post_dispatch_validation_failure_is_unknown_not_rejected(self):
        service, _, _ = self.make_service()
        self.assertEqual(self.send(service, self.op, "claim").state,
                         ManualState.CONFIRMED)
        original_fresh = service._fresh
        calls = [0]

        def fail_followup(chamber_id):
            calls[0] += 1
            if calls[0] == 2:
                raise ChamberSafetyError("post-write status missing")
            return original_fresh(chamber_id)

        service._fresh = fail_followup
        outcome = self.send(service, self.op, "set_temperature", target_c=41)
        self.assertEqual(outcome.state, ManualState.UNKNOWN)
        self.assertIn("not guaranteed", outcome.message)

    def test_unverified_post_stop_status_is_unknown_not_refused(self):
        service, mgr, _ = self.make_service()
        original_status = mgr.status

        def bad_followup(chamber_id):
            return replace(original_status(chamber_id), quality=ReadingQuality.STALE)

        mgr.status = bad_followup
        outcome = self.send(service, self.op, "stop")
        self.assertEqual(outcome.state, ManualState.UNKNOWN)
        self.assertTrue(mgr.health(service.chamber_id).stop_latched)

    def test_good_but_stale_post_stop_timestamp_is_unknown(self):
        service, mgr, _ = self.make_service()
        original_status = mgr.status

        def stale_good_status(chamber_id):
            return replace(original_status(chamber_id),
                           sampled_at_utc=datetime.now(timezone.utc) -
                           timedelta(seconds=60))

        mgr.status = stale_good_status
        outcome = self.send(service, self.op, "stop")
        self.assertEqual(outcome.state, ManualState.UNKNOWN)
        self.assertTrue(mgr.health(service.chamber_id).stop_latched)

    def test_older_confirmed_result_does_not_supersede_stop(self):
        service, _, _ = self.make_service()
        old = service._begin("start")
        service._begin("stop")
        outcome = service._finish(old, "start", ManualState.CONFIRMED, "done")
        self.assertEqual(outcome.state, ManualState.UNKNOWN)
        self.assertEqual(service.view(self.admin.session, service.chamber_id)
                         .last_command.state, ManualState.STOP_REQUESTED)

    def test_stale_disconnected_telemetry_denies_nonstop_commands(self):
        class StaleFake(FakeBackend):
            stale = False

            def read_status(self):
                sample = super().read_status()
                if self.stale:
                    return replace(sample, sampled_at_utc=(
                        datetime.now(timezone.utc) - timedelta(hours=1)))
                return sample

        instances = []
        def factory(cfg, allow_test_backend=False):
            backend = StaleFake(cfg.chamber_id)
            instances.append(backend)
            return backend

        service, _, dashboard = self.make_service(factory)
        self.assertEqual(self.send(service, self.op, "claim").state,
                         ManualState.CONFIRMED)
        instances[0].stale = True
        asyncio.run(dashboard.poll_once())
        self.assertIn(service.view(self.op.session, service.chamber_id).dashboard.quality,
                      (ReadingQuality.ERROR, ReadingQuality.STALE))
        self.assertIn(self.send(service, self.op, "set_temperature",
                                target_c=25).state, (ManualState.UNKNOWN, ManualState.FAULT))
        self.assertIn(self.send(service, self.admin, "stop").state,
                      (ManualState.UNKNOWN, ManualState.FAULT))
        self.assertNotEqual(service.view(self.op.session, service.chamber_id).controller_state,
                            "RUNNING")

    def test_stop_fences_queued_setpoint_without_lease(self):
        instances = []
        def factory(cfg, allow_test_backend=False):
            backend = BlockingFakeBackend(cfg.chamber_id)
            instances.append(backend)
            return backend

        service, mgr, _ = self.make_service(factory)
        self.assertEqual(self.send(service, self.op, "claim").state,
                         ManualState.CONFIRMED)
        backend = instances[0]
        results = {}

        def change():
            results["set"] = self.send(service, self.op, "set_temperature", target_c=33)

        def stop():
            results["stop"] = self.send(service, self.op2, "stop")

        setter = threading.Thread(target=change)
        stopper = threading.Thread(target=stop)
        setter.start()
        self.assertTrue(backend.entered.wait(timeout=2))
        stopper.start()
        backend.proceed.set()
        setter.join(timeout=5)
        stopper.join(timeout=5)
        self.assertFalse(setter.is_alive())
        self.assertFalse(stopper.is_alive())
        self.assertEqual(results["stop"].state, ManualState.CONFIRMED)
        self.assertEqual(mgr.health(service.chamber_id).state, "VERIFIED_STOPPED")
        self.assertTrue(mgr.health(service.chamber_id).stop_latched)
        self.assertEqual(service.view(self.admin.session, service.chamber_id).last_command.action,
                         "stop")

    def test_refresh_same_actor_separate_clients_and_restart_reconcile(self):
        service, mgr, dashboard = self.make_service()
        self.assertEqual(self.send(service, self.op, "claim").state,
                         ManualState.CONFIRMED)
        same_actor_second_browser = self.security.login(
            "operator_1", "StrongOperatorPassword#2")
        self.assertTrue(service.view(same_actor_second_browser.session,
                                     service.chamber_id).owned_by_actor)
        self.assertFalse(service.view(self.viewer.session, service.chamber_id).owned_by_actor)
        self.assertEqual(self.send(service, self.op, "start").state,
                         ManualState.CONFIRMED)
        mgr.disconnect(service.chamber_id)
        self.managers.remove(mgr)
        # New G04 process instance uses identical durable lease directory.
        new_service, new_mgr, _ = self.make_service(suffix="one")
        self.assertTrue(new_mgr.health(new_service.chamber_id).stop_latched)
        self.assertIn(self.send(new_service, self.op, "start").state,
                      (ManualState.UNKNOWN, ManualState.REJECTED))
        # Mock starts freshly STOPPED but controller must not implicitly clear
        # the durable latch. Only a G08-authorized administrator can reconcile.
        self.assertEqual(self.send(new_service, self.admin, "reconcile").state,
                         ManualState.CONFIRMED)
        self.assertEqual(self.send(new_service, self.op, "claim").state,
                         ManualState.CONFIRMED)


if __name__ == "__main__":
    unittest.main()
