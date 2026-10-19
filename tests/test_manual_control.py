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

    def test_stop_without_claim_then_start_requires_no_admin_or_claim(self):
        """Stopping before any lease claim must not strand the operator."""
        service, manager, dashboard = self.make_service()
        chamber_id = service.chamber_id
        # These buttons are available without an operator lease.
        self.assertTrue(service.view(self.op.session, chamber_id).can_start)
        self.assertTrue(service.view(self.op.session, chamber_id).can_stop)
        result = self.send(service, self.op, "stop")
        self.assertEqual(result.state, ManualState.CONFIRMED)
        self.assertTrue(manager.health(chamber_id).stop_latched)
        asyncio.run(dashboard.poll_once())
        self.assertTrue(service.view(self.op.session, chamber_id).can_start)
        # Explicit operator intent claims the free lease and independently
        # verifies STOPPED through G04 before issuing any new START.
        result = self.send(service, self.op, "start")
        self.assertEqual(result.state, ManualState.CONFIRMED, result.message)
        self.assertFalse(manager.health(chamber_id).stop_latched)
        self.assertTrue(service.view(self.op.session, chamber_id).owned_by_actor)
        stopped = self.send(service, self.op, "stop")
        self.assertEqual(stopped.state, ManualState.CONFIRMED)
        self.assertFalse(manager.health(chamber_id).stop_latched)
        self.assertEqual(self.send(service, self.op, "start").state,
                         ManualState.CONFIRMED)

    def test_operator_start_auto_claims_without_admin(self):
        service, manager, dashboard = self.make_service()
        chamber_id = service.chamber_id
        self.assertIsNone(service.view(self.op.session, chamber_id).owner)
        self.assertTrue(service.view(self.op.session, chamber_id).can_start)
        self.assertEqual(self.send(service, self.op, "start").state,
                         ManualState.CONFIRMED)
        asyncio.run(dashboard.poll_once())
        state = service.view(self.op.session, chamber_id)
        self.assertTrue(state.owned_by_actor)
        self.assertTrue(state.can_stop)
        self.assertFalse(service.view(self.op2.session, chamber_id).can_start)
        self.assertEqual(self.send(service, self.op2, "start").state,
                         ManualState.REJECTED)

    def test_owned_verified_manual_stop_rearms_and_retains_lease(self):
        """One operator can START, STOP, START without Admin reconciliation."""
        service, manager, dashboard = self.make_service()
        chamber_id = service.chamber_id
        self.assertEqual(self.send(service, self.op, "claim").state, ManualState.CONFIRMED)
        for index in range(2):
            with self.subTest(cycle=index):
                self.assertEqual(self.send(service, self.op, "start").state,
                                 ManualState.CONFIRMED)
                stopped = self.send(service, self.op, "stop")
                self.assertEqual(stopped.state, ManualState.CONFIRMED)
                self.assertIn("controls ready", stopped.message)
                health = manager.health(chamber_id)
                self.assertEqual(health.state, "VERIFIED_STOPPED")
                self.assertFalse(health.stop_latched)
                asyncio.run(dashboard.poll_once())
                view = service.view(self.op.session, chamber_id)
                self.assertTrue(view.owned_by_actor)
                self.assertTrue(view.can_start)
                self.assertTrue(view.can_set_target)
        self.assertEqual(self.send(service, self.op, "release").state,
                         ManualState.CONFIRMED)

    def test_nonowner_stop_requires_explicit_start_to_reverify_and_rearm(self):
        service, manager, dashboard = self.make_service()
        cid = service.chamber_id
        self.assertEqual(self.send(service, self.op, "claim").state, ManualState.CONFIRMED)
        self.assertEqual(self.send(service, self.op, "start").state, ManualState.CONFIRMED)
        stopped = self.send(service, self.op2, "stop")
        self.assertEqual(stopped.state, ManualState.CONFIRMED)
        self.assertIn("explicit reconciliation", stopped.message)
        health = manager.health(cid)
        self.assertTrue(health.stop_latched)
        self.assertEqual(health.state, "VERIFIED_STOPPED")
        self.assertFalse(service._authorized.rearm_after_owned_verified_stop(
            self.op2.session, self.op2.csrf, cid,
            expected_generation=health.generation,
            expected_lease_revision=-1))
        asyncio.run(dashboard.poll_once())
        self.assertTrue(service.view(self.op.session, cid).can_start)
        # Another user cannot recover or start on the existing owner's lease.
        self.assertFalse(service.view(self.op2.session, cid).can_start)
        self.assertEqual(self.send(service, self.op2, "start").state,
                         ManualState.REJECTED)
        # The original lease owner makes a separate, explicit START request.
        # This performs fresh G04 STOPPED reconciliation before any start I/O.
        self.assertEqual(self.send(service, self.op, "start").state,
                         ManualState.CONFIRMED)
        self.assertFalse(manager.health(cid).stop_latched)
        self.assertTrue(service.view(self.op.session, cid).owned_by_actor)

    def test_rearm_requires_exact_stop_generation(self):
        service, manager, _ = self.make_service()
        cid = service.chamber_id
        self.assertEqual(self.send(service, self.op, "claim").state, ManualState.CONFIRMED)
        # A STOP from another operator always latches; an owner is not
        # authorized to reinterpret that earlier STOP as their normal STOP.
        before = manager.health(cid).generation
        self.assertEqual(self.send(service, self.op2, "stop").state, ManualState.CONFIRMED)
        generation = manager.health(cid).generation
        self.assertEqual(generation, before + 1)
        self.assertFalse(service._authorized.rearm_after_owned_verified_stop(
            self.op.session, self.op.csrf, cid,
            expected_generation=before,
            expected_lease_revision=service._authorized.owned_lease_revision_now(
                self.security.authenticate(self.op.session).user_id)))
        self.assertTrue(manager.health(cid).stop_latched)
        self.assertEqual(self.send(service, self.admin, "reconcile").state,
                         ManualState.CONFIRMED)

    def test_rearm_is_not_exposed_to_viewer_or_revoked_session(self):
        service, manager, _ = self.make_service()
        cid = service.chamber_id
        self.assertEqual(self.send(service, self.op, "claim").state, ManualState.CONFIRMED)
        self.assertEqual(self.send(service, self.op2, "stop").state, ManualState.CONFIRMED)
        generation = manager.health(cid).generation
        with self.assertRaises(AuthorizationError):
            service._authorized.rearm_after_owned_verified_stop(
                self.viewer.session, self.viewer.csrf, cid,
                expected_generation=generation,
                expected_lease_revision=-1)
        self.security.logout(self.op.session)
        with self.assertRaises(AuthenticationError):
            service._authorized.rearm_after_owned_verified_stop(
                self.op.session, self.op.csrf, cid,
                expected_generation=generation,
                expected_lease_revision=-1)
        self.assertTrue(manager.health(cid).stop_latched)

    def test_competing_stop_between_verification_and_rearm_stays_latched(self):
        service, manager, _ = self.make_service()
        cid = service.chamber_id
        self.assertEqual(self.send(service, self.op, "claim").state, ManualState.CONFIRMED)
        self.assertEqual(self.send(service, self.op, "start").state, ManualState.CONFIRMED)
        rearm = service._authorized.rearm_after_owned_verified_stop

        def inject_competing_stop(session, csrf, chamber_id, *,
                                  expected_generation, expected_lease_revision):
            service._authorized.stop(self.op2.session, self.op2.csrf, chamber_id)
            return rearm(session, csrf, chamber_id,
                         expected_generation=expected_generation,
                         expected_lease_revision=expected_lease_revision)

        service._authorized.rearm_after_owned_verified_stop = inject_competing_stop
        stopped = self.send(service, self.op, "stop")
        self.assertEqual(stopped.state, ManualState.CONFIRMED)
        self.assertIn("explicit reconciliation", stopped.message)
        self.assertTrue(manager.health(cid).stop_latched)
        # The interfering STOP must remain fenced during the earlier STOP
        # callback. A later deliberate START can reverify and recover.
        self.assertEqual(self.send(service, self.op, "start").state,
                         ManualState.CONFIRMED)
        self.assertFalse(manager.health(cid).stop_latched)

    def test_ambiguous_owned_stop_must_not_auto_rearm(self):
        class FailingStop(FakeBackend):
            def stop(self):
                raise TimeoutError("Injected STOP uncertainty")

        service, manager, _ = self.make_service(
            lambda cfg, allow_test_backend=False: FailingStop(cfg.chamber_id))
        cid = service.chamber_id
        self.assertEqual(self.send(service, self.op, "claim").state, ManualState.CONFIRMED)
        self.assertEqual(self.send(service, self.op, "start").state, ManualState.CONFIRMED)
        result = self.send(service, self.op, "stop")
        self.assertIn(result.state, (ManualState.UNKNOWN, ManualState.FAULT))
        self.assertTrue(manager.health(cid).stop_latched)
        self.assertIn(manager.health(cid).state, ("UNKNOWN", "FAULT"))
        # A command denied under uncertain hardware state must not be
        # mislabeled as an ordinary safe refusal.
        self.assertIn(self.send(service, self.op, "start").state,
                      (ManualState.UNKNOWN, ManualState.FAULT, ManualState.REJECTED))
        self.assertTrue(manager.health(cid).stop_latched)

    def test_concurrent_operator_claim_and_admin_handover(self):
        service, _, _ = self.make_service()
        barrier = threading.Barrier(3)
        results = []

        def attempt(tokens):
            barrier.wait()
            results.append((tokens, self.send(service, tokens, "claim").state))

        threads = [threading.Thread(target=attempt, args=(who,))
                   for who in (self.op, self.op2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=4)
            self.assertFalse(thread.is_alive())
        # Exactly one operator wins the lease. The winner's page result may be
        # conservatively downgraded to UNKNOWN ("superseded") when the losing
        # claim began before it finished; it must never be REJECTED, and the
        # authoritative lease view must show the winner (and only the winner).
        rejected = [who for who, state in results if state is ManualState.REJECTED]
        others = [(who, state) for who, state in results
                  if state is not ManualState.REJECTED]
        self.assertEqual(len(rejected), 1, results)
        self.assertEqual(len(others), 1, results)
        winner, winner_state = others[0]
        self.assertIn(winner_state, (ManualState.CONFIRMED, ManualState.UNKNOWN))
        self.assertTrue(service.view(winner.session, service.chamber_id).owned_by_actor)
        self.assertFalse(service.view(rejected[0].session, service.chamber_id).owned_by_actor)
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

    def test_later_denied_start_cannot_hide_pending_stop(self):
        service, _, _ = self.make_service()
        stop_serial = service._begin("stop")
        newer_start = service._begin("start")
        self.assertEqual(service.view(self.admin.session, service.chamber_id)
                         .last_command.state, ManualState.STOP_REQUESTED)
        service._finish(newer_start, "start", ManualState.REJECTED,
                        "Controller STOP latch prevents START")
        pending = service.view(self.admin.session, service.chamber_id).last_command
        self.assertEqual(pending.action, "stop")
        self.assertEqual(pending.state, ManualState.STOP_REQUESTED)
        service._finish(stop_serial, "stop", ManualState.CONFIRMED, "verified")
        completed = service.view(self.admin.session, service.chamber_id).last_command
        self.assertEqual(completed.action, "stop")
        self.assertEqual(completed.state, ManualState.CONFIRMED)

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

    def test_manual_and_g06_profile_runner_exclusive_ownership(self):
        # Independent simulated callers share G04; an authenticated manual
        # controller must not steal G06's lease, nor vice versa. Authorized
        # non-owner STOP is deliberately still available through G08.
        from decimal import Decimal
        from chamber_web.domain.profile import ParsedProfile, ProfileStep
        from chamber_web.execution.profile_runner import ProfileRunner, VirtualClock
        from chamber_web.persistence.profiles import ProfileStore

        service, manager, _ = self.make_service()
        chamber_id = service.chamber_id
        profiles = ProfileStore(self.root / "profile-ownership.sqlite3")
        step = ProfileStep(1, True, Decimal("25"), None, None,
                           Decimal("1"), Decimal("0"), Decimal("10"),
                           Decimal("30"), "manual-vs-profile")
        header = profiles.create_profile(chamber_id, ParsedProfile((step,)))
        runner = ProfileRunner(manager, profiles,
                               authorize=lambda action, cid: "G06-test-principal",
                               clock=VirtualClock())
        try:
            self.assertEqual(self.send(service, self.op, "claim").state,
                             ManualState.CONFIRMED)
            with self.assertRaises(ChamberSafetyError):
                runner.start(chamber_id, header.profile_id, revision=1)
            self.assertEqual(self.send(service, self.op, "release").state,
                             ManualState.CONFIRMED)
            runner.start(chamber_id, header.profile_id, revision=1)
            self.assertEqual(self.send(service, self.op, "claim").state,
                             ManualState.REJECTED)
            self.assertEqual(self.send(service, self.op2, "stop").state,
                             ManualState.CONFIRMED)
            self.assertTrue(manager.health(chamber_id).stop_latched)
            self.assertIn(self.send(service, self.op, "start").state,
                          (ManualState.UNKNOWN, ManualState.REJECTED))
            # External STOP is asynchronous relative to the G06 scheduler.
            # Drive its state machine to a terminal UNKNOWN, never force-close
            # an active run or infer that STOP readback completed G06 cleanup.
            from chamber_web.execution.profile_runner import RunState
            import time
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline and runner.state not in (
                RunState.COMPLETED, RunState.CANCELLED, RunState.FAULT, RunState.UNKNOWN
            ):
                runner.advance()
                time.sleep(.01)
            self.assertIn(runner.state, (RunState.UNKNOWN, RunState.FAULT,
                                         RunState.CANCELLED))
        finally:
            if runner.state in (RunState.COMPLETED, RunState.CANCELLED,
                                RunState.FAULT, RunState.UNKNOWN, None):
                runner.close()

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
