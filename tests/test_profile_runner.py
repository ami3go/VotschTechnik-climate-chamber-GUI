"""G06-A virtual-clock, simulated-only state/timing/STOP/authorization tests."""
from __future__ import annotations

import threading
import time
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from chamber_web.adapters.alternate_stub import AlternateStubBackend
from chamber_web.adapters.fake import FakeBackend
from chamber_web.domain.chamber import (
    ChamberSafetyError, OperationState,
)
from chamber_web.domain.config import ChamberConfig
from chamber_web.domain.profile import ParsedProfile, ProfileStep
from chamber_web.execution.profile_runner import (
    ProfileRunner, RunParameters, RunState, VirtualClock,
)
from chamber_web.persistence.profiles import ProfileStore
from chamber_web.services.chamber_manager import ChamberManager


def step(target="25", *, stabilize="0", dwell="0", reach="20", up=None, down=None,
         chamber_run="ON", compressed_air="UNCHANGED", dryer="UNCHANGED", outputs=()):
    return ProfileStep(
        1, True, Decimal(target),
        Decimal(up) if up is not None else None,
        Decimal(down) if down is not None else None,
        Decimal("1"), Decimal(stabilize), Decimal(dwell),
        Decimal(reach), "test", chamber_run, compressed_air, dryer, outputs,
    )


class AdvancingSampleTime:
    """Windows clock granularity must not alias distinct simulated observations.

    Keep a separate cached-sample fixture to explicitly test equal timestamps.
    Unique timestamps are capped to microseconds ahead of current UTC so G04
    freshness checks remain active.
    """
    def read_status(self):
        sample = super().read_status()
        if sample.sampled_at_utc is None:
            return sample
        previous = getattr(self, "_last_test_sample_utc", None)
        stamped = sample.sampled_at_utc
        if previous is not None and stamped <= previous:
            stamped = previous + timedelta(microseconds=1)
        self._last_test_sample_utc = stamped
        return replace(sample, sampled_at_utc=stamped)


class DistinctFake(AdvancingSampleTime, FakeBackend):
    pass


class DistinctAlternate(AdvancingSampleTime, AlternateStubBackend):
    pass


class CaptureSink:
    def __init__(self):
        self.events = []
        self.prepared = []

    def prepare(self, snapshot):
        self.prepared.append(snapshot)

    def emit(self, event):
        self.events.append(event)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.clock = VirtualClock()
        self.backend = DistinctFake("unit-chamber")
        self.sink = CaptureSink()
        self.manager = ChamberManager(
            [ChamberConfig("unit-chamber", "fake")],
            backend_factory=lambda config, **kwargs: self.backend,
            lease_directory=self.root / "lease",
        )
        self.manager.connect("unit-chamber")
        self.addCleanup(self.manager.disconnect, "unit-chamber")
        self.store = ProfileStore(self.root / "profiles.sqlite")
        self.runner = ProfileRunner(
            self.manager, self.store, authorize=lambda action, chamber: "test-operator",
            sink=self.sink, clock=self.clock,
        )
        self.addCleanup(self.runner.close)

    def prepare(self, profile_step=None, *, profile=None, params=None):
        profile = profile or ParsedProfile((profile_step or step(),), name="simulated")
        header = self.store.create_profile("unit-chamber", profile)
        snapshot = self.runner.start(
            "unit-chamber", header.profile_id, revision=1, parameters=params,
        )
        self.assertEqual(snapshot.chamber_id, "unit-chamber")
        self.assertEqual(snapshot.identity.backend_id, "fake")
        self.assertEqual(snapshot.revision_sha256.__len__(), 64)
        self.assertEqual(self.runner.state, RunState.PREPARING)
        return snapshot

    def terminal(self, expected):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            state = self.runner.advance()
            if state in (RunState.COMPLETED, RunState.CANCELLED, RunState.FAULT, RunState.UNKNOWN):
                break
            time.sleep(.005)
        self.assertEqual(self.runner.state, expected, self.runner.reason)
        self.assertTrue(self.manager.health("unit-chamber").stop_latched)
        return self.runner.state

    def test_default_auth_denied_no_device_mutation(self):
        noauth = ProfileRunner(self.manager, self.store)
        self.addCleanup(noauth.close)
        header = self.store.create_profile("unit-chamber", ParsedProfile((step(),)))
        with self.assertRaisesRegex(ChamberSafetyError, "authorization"):
            noauth.start("unit-chamber", header.profile_id, revision=1)
        with self.assertRaises(ChamberSafetyError):
            noauth.cancel("unit-chamber")
        self.assertFalse(self.backend._running)

    def test_run_zero_dwell_stops_and_fences(self):
        snapshot = self.prepare()
        self.runner.advance()
        self.assertEqual(self.runner.state, RunState.REACHING)
        self.runner.advance()
        self.terminal(RunState.COMPLETED)
        kinds = [e.kind for e in self.sink.events]
        self.assertEqual(kinds[0], "PREPARED")
        self.assertEqual(self.sink.prepared, [snapshot])
        self.assertLess(kinds.index("START_INTENT"), kinds.index("SETPOINT_INTENT"))
        self.assertLess(kinds.index("START_INTENT"), kinds.index("STOP_INTENT"))
        self.assertEqual(kinds[-1], "TERMINAL")
        self.assertEqual(self.runner.snapshot, snapshot)
        self.assertEqual([e.sequence for e in self.sink.events],
                         list(range(1, len(self.sink.events) + 1)))
        samples = [e for e in self.sink.events if e.kind == "SAMPLE"]
        self.assertTrue(samples)
        self.assertEqual([e.sample_index for e in samples],
                         list(range(1, len(samples) + 1)))
        for event in self.sink.events:
            self.assertIsNotNone(datetime.fromisoformat(event.observed_at_utc).tzinfo)
            if event.kind == "SAMPLE":
                self.assertIsNotNone(
                    datetime.fromisoformat(event.source_sampled_at_utc).tzinfo,
                )
            else:
                self.assertIsNone(event.sample_index)
        self.assertFalse(self.backend._running)
        with self.assertRaises(ChamberSafetyError):
            self.manager.start("unit-chamber")

    def test_per_step_run_and_digital_outputs_are_verified_in_simulation(self):
        first = step(compressed_air="ON", outputs=((2, True),))
        second = replace(
            step(chamber_run="OFF", dryer="ON", outputs=((2, False),)), step=2,
        )
        self.prepare(profile=ParsedProfile((first, second), name="output cycle"))

        self.runner.advance()
        self.assertTrue(self.backend._running)
        self.assertTrue(self.backend.read_digital_output(2))
        self.assertTrue(self.backend.read_digital_output(7))
        self.runner.advance()
        self.assertEqual(self.runner.state, RunState.TRANSITIONING)

        self.runner.advance()
        self.assertFalse(self.backend._running)
        self.assertFalse(self.backend.read_digital_output(2))
        self.assertTrue(self.backend.read_digital_output(8))
        self.runner.advance()
        self.terminal(RunState.COMPLETED)
        self.assertIn("OUTPUT_INTENT", [event.kind for event in self.sink.events])
        # STOP does not invent an auxiliary-output policy; explicit step values remain.
        self.assertTrue(self.backend.read_digital_output(7))
        self.assertTrue(self.backend.read_digital_output(8))

    def test_unsupported_profile_output_is_rejected_before_lease_or_mutation(self):
        with self.assertRaisesRegex(ChamberSafetyError, "unsupported"):
            self.prepare(step(outputs=((20, True),)))
        self.assertFalse(self.backend._running)

    def test_digital_output_readback_mismatch_fails_closed_and_stops(self):
        self.prepare(step(compressed_air="ON"))
        actual_read = self.backend.read_digital_output
        self.backend.read_digital_output = lambda number: not actual_read(number)
        self.runner.advance()
        self.assertEqual(self.runner.state, RunState.STOP_REQUESTED)
        self.terminal(RunState.UNKNOWN)
        self.assertFalse(self.backend._running)

    def test_stabilization_requires_two_distinct_good_samples(self):
        self.prepare(step(stabilize="4", dwell="0"))
        self.runner.advance()
        self.runner.advance()
        self.assertEqual(self.runner.state, RunState.STABILIZING)
        self.runner.advance()  # same monotonic instant is not a second sample
        self.assertEqual(self.runner.state, RunState.STABILIZING)
        self.clock.advance(2)
        self.runner.advance()
        self.assertEqual(self.runner.state, RunState.STABILIZING)
        self.clock.advance(2)
        self.runner.advance()
        self.terminal(RunState.COMPLETED)

    def test_cached_sample_cannot_qualify_stabilization(self):
        self.prepare(step(stabilize="4"))
        self.runner.advance()
        cached = self.backend.read_status()
        original = self.backend.read_status
        self.backend.read_status = lambda: cached
        self.runner.advance()
        self.assertEqual(self.runner.state, RunState.STABILIZING)
        self.clock.advance(4)
        self.runner.advance()
        self.assertEqual(self.runner.state, RunState.STABILIZING)
        self.backend.read_status = original
        self.clock.advance(1)
        self.runner.advance()
        self.terminal(RunState.COMPLETED)

    def test_cached_sample_cannot_credit_dwell(self):
        self.prepare(step(dwell="4"))
        self.runner.advance()
        original = self.backend.read_status
        cached = original()
        self.backend.read_status = lambda: cached
        self.runner.advance()
        self.assertEqual(self.runner.state, RunState.DWELLING)
        self.clock.advance(4)
        self.runner.advance()
        self.assertEqual(self.runner.state, RunState.DWELLING)
        self.backend.read_status = original  # Restore truthful STOP readback.
        self.runner.cancel("unit-chamber")
        self.terminal(RunState.CANCELLED)

    def test_dwell_bracketed_and_inclusive_tolerance(self):
        self.prepare(step(dwell="4"))
        self.runner.advance()
        self.backend._measured = 26.0  # inclusive 25 ±1
        self.runner.advance()
        self.assertEqual(self.runner.state, RunState.DWELLING)
        self.runner.advance()
        self.assertEqual(self.runner.state, RunState.DWELLING)
        self.clock.advance(2)
        self.runner.advance()
        self.assertEqual(self.runner.state, RunState.DWELLING)
        self.clock.advance(2)
        self.runner.advance()
        self.terminal(RunState.COMPLETED)

    def test_excursion_and_gap_reset_dwell(self):
        self.prepare(step(dwell="4", reach="25"))
        self.runner.advance()
        self.runner.advance()
        self.clock.advance(2)
        self.runner.advance()  # 2 credited
        self.backend._measured = 26.01
        self.clock.advance(1)
        self.runner.advance()
        self.assertEqual(self.runner.state, RunState.REACHING)
        self.backend._measured = 25
        self.clock.advance(1)
        self.runner.advance()
        self.assertEqual(self.runner.state, RunState.DWELLING)
        self.clock.advance(5.01)
        self.runner.advance()
        self.assertEqual(self.runner.state, RunState.DWELLING)
        self.clock.advance(2)
        self.runner.advance()
        self.assertEqual(self.runner.state, RunState.DWELLING)
        self.clock.advance(2)
        self.runner.advance()
        self.terminal(RunState.COMPLETED)

    def test_pause_resume_resets_credit_and_watchdog_continues(self):
        self.prepare(step(dwell="4", reach="20"))
        self.runner.advance()
        self.runner.advance()
        self.clock.advance(2)
        self.runner.advance()
        self.runner.pause("unit-chamber")
        self.assertEqual(self.runner.state, RunState.PAUSED)
        self.clock.advance(2)
        self.runner.advance()
        self.runner.resume("unit-chamber")
        self.assertEqual(self.runner.state, RunState.REACHING)
        self.runner.advance()
        self.assertEqual(self.runner.state, RunState.DWELLING)
        self.clock.advance(4)
        self.runner.advance()
        self.terminal(RunState.COMPLETED)

    def test_pause_resume_with_stopped_chamber_step(self):
        """A v2 OFF step is resumable without silently starting the chamber."""
        self.prepare(step(chamber_run="OFF", dwell="6"))
        self.runner.advance()
        self.assertEqual(self.runner.state, RunState.REACHING)
        self.assertFalse(self.backend._running)
        self.runner.advance()
        self.assertEqual(self.runner.state, RunState.DWELLING)
        self.runner.pause("unit-chamber")
        self.assertEqual(self.runner.state, RunState.PAUSED)
        self.clock.advance(1)
        self.runner.advance()  # Paused OFF-state telemetry remains valid.
        self.assertEqual(self.runner.state, RunState.PAUSED)
        self.runner.resume("unit-chamber")
        self.assertEqual(self.runner.state, RunState.REACHING)
        self.assertFalse(self.backend._running)
        self.runner.advance()
        self.assertEqual(self.runner.state, RunState.DWELLING)
        # Qualification requires continuous samples with gaps <= max_gap_s (5 s).
        # A single 6-second leap correctly resets dwell instead of completing it.
        self.clock.advance(3)
        self.runner.advance()
        self.assertEqual(self.runner.state, RunState.DWELLING)
        self.clock.advance(3)
        self.runner.advance()
        self.terminal(RunState.COMPLETED)
        self.assertFalse(self.backend._running)

    def test_pause_does_not_extend_whole_run_deadline(self):
        self.prepare(step(dwell="10", reach="20"),
                     params=RunParameters(max_run_s=3))
        self.runner.advance()
        self.runner.advance()
        self.runner.pause("unit-chamber")
        self.clock.advance(3.01)
        self.runner.advance()
        self.terminal(RunState.FAULT)

    def test_repeat_count_uses_frozen_schedule(self):
        profile = ParsedProfile((step(),), name="repeat", repeat_count=2)
        self.prepare(profile=profile)
        self.runner.advance()
        self.runner.advance()
        self.assertEqual(self.runner.state, RunState.TRANSITIONING)
        self.runner.advance()
        self.runner.advance()
        self.terminal(RunState.COMPLETED)
        self.assertEqual(sum(e.kind == "STEP_COMPLETED" for e in self.sink.events), 2)

    def test_paused_out_of_envelope_temperature_is_unknown(self):
        self.prepare(step(dwell="20"))
        self.runner.advance()
        self.runner.advance()
        self.runner.pause("unit-chamber")
        self.backend._measured = 1000
        self.runner.advance()
        self.terminal(RunState.UNKNOWN)

    def test_stricter_sample_age_policy_is_enforced(self):
        self.prepare(step(dwell="5"), params=RunParameters(max_age_s=0.1))
        self.runner.advance()
        original = self.backend.read_status
        self.backend.read_status = lambda: replace(
            original(), sampled_at_utc=datetime.now(timezone.utc) -
            timedelta(seconds=1),
        )
        self.runner.advance()
        self.terminal(RunState.UNKNOWN)

    def test_reach_timeout_and_boundary_equality(self):
        self.prepare(step(target="30", reach="4"))
        self.runner.advance()
        self.clock.advance(4)
        self.backend._measured = 30
        self.runner.advance()  # equality succeeds
        self.terminal(RunState.COMPLETED)

    def test_reach_exceeded_fails(self):
        self.prepare(step(target="30", reach="4"))
        self.runner.advance()
        self.clock.advance(4.01)
        self.runner.advance()
        self.terminal(RunState.FAULT)

    def test_run_deadline_cannot_be_extended_by_skipped_ticks(self):
        self.prepare(step(dwell="20"), params=RunParameters(max_run_s=1))
        self.runner.advance()
        self.clock.advance(2)
        self.runner.advance()
        self.terminal(RunState.FAULT)

    def test_unsupported_gradient_preflight_without_write(self):
        header = self.store.create_profile(
            "unit-chamber", ParsedProfile((step(up="2"),)),
        )
        with self.assertRaisesRegex(ChamberSafetyError, "gradients unsupported"):
            self.runner.start("unit-chamber", header.profile_id, revision=1)
        self.assertFalse(self.backend._running)
        self.assertEqual(self.backend._target, 25)

    def test_simulated_negative_setpoint_is_valid(self):
        self.prepare(step(target="-5"))
        self.runner.advance()
        self.assertEqual(self.backend._target, -5)
        self.backend._measured = -5
        self.runner.advance()
        self.terminal(RunState.COMPLETED)

    def test_wrong_chamber_rejected_before_any_mutation(self):
        header = self.store.create_profile("unit-chamber", ParsedProfile((step(),)))
        with self.assertRaises(ChamberSafetyError):
            self.runner.start("wrong", header.profile_id, revision=1)
        self.assertFalse(self.backend._running)

    def test_concurrent_starts_only_one_reservation(self):
        header = self.store.create_profile("unit-chamber", ParsedProfile((step(),)))
        barrier = threading.Barrier(3)
        outcomes = []

        def attempt():
            barrier.wait()
            try:
                self.runner.start("unit-chamber", header.profile_id, revision=1)
                outcomes.append("OK")
            except ChamberSafetyError:
                outcomes.append("DENIED")

        threads = [threading.Thread(target=attempt) for _ in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=3)
            self.assertFalse(thread.is_alive())
        self.assertCountEqual(outcomes, ["OK", "DENIED"])
        self.runner.cancel("unit-chamber")
        self.terminal(RunState.CANCELLED)

    def test_cancel_from_pause_and_repeated_cancel_one_stop(self):
        self.prepare(step(dwell="10"))
        self.runner.advance()
        self.runner.advance()
        self.runner.pause("unit-chamber")
        self.runner.cancel("unit-chamber")
        self.runner.cancel("unit-chamber")
        self.terminal(RunState.CANCELLED)
        self.assertFalse(self.backend._running)

    def test_stale_sample_is_unknown_not_completed(self):
        self.prepare(step(dwell="2"))
        self.runner.advance()
        original = self.backend.read_status

        def stale():
            return replace(original(), sampled_at_utc=datetime.now(timezone.utc) -
                           timedelta(seconds=30))
        self.backend.read_status = stale
        self.runner.advance()
        self.terminal(RunState.UNKNOWN)

    def test_readback_mismatch_is_unknown(self):
        # A frozen wrong setpoint is no ramp: after consecutive unchanged
        # fresh samples the runner fails closed instead of never converging.
        self.prepare()
        self.runner.advance()
        original = self.backend.read_status

        def mismatch():
            return replace(original(), setpoint_temperature_c=44.0)
        self.backend.read_status = mismatch
        self.runner.advance()
        self.terminal(RunState.UNKNOWN)

    def test_mid_ramp_setpoint_readback_converges_and_completes(self):
        self.prepare()
        self.runner.advance()
        original = self.backend.read_status
        ramp = [44.0, 40.0, 30.0, 25.6]

        def ramping():
            observed = ramp.pop(0) if ramp else 25.0
            return replace(original(), setpoint_temperature_c=observed)

        self.backend.read_status = ramping
        self.terminal(RunState.COMPLETED)
        samples = [event for event in self.sink.events if event.kind == "SAMPLE"]
        self.assertTrue(samples)
        self.assertEqual(samples[-1].setpoint_temperature_c, 25.0)
        generation = self.runner.snapshot.controller_generation
        self.assertTrue(all(event.setpoint_temperature_c is not None
                            for event in samples))
        self.assertTrue(all(event.controller_generation == generation
                            for event in samples))

    def test_setpoint_readback_moving_away_is_unknown(self):
        self.prepare()
        self.runner.advance()
        original = self.backend.read_status
        values = [40.0, 44.0]

        def diverging():
            observed = values.pop(0) if values else 44.0
            return replace(original(), setpoint_temperature_c=observed)

        self.backend.read_status = diverging
        self.runner.advance()  # first intermediate readback is a valid ramp
        self.assertEqual(self.runner.state, RunState.REACHING)
        self.runner.advance()  # moving away from the target never qualifies
        self.terminal(RunState.UNKNOWN)

    def test_fault_and_invalid_measured_temperature(self):
        self.prepare()
        self.runner.advance()
        original = self.backend.read_status
        self.backend.read_status = lambda: replace(
            original(), measured_temperature_c=float("nan"),
            operation_state=OperationState.FAULT,
        )
        self.runner.advance()
        self.terminal(RunState.UNKNOWN)

    def test_disconnect_latches_uncertainty(self):
        self.prepare(step(dwell="10"))
        self.runner.advance()
        self.manager.disconnect("unit-chamber")
        self.runner.advance()
        self.terminal(RunState.UNKNOWN)

    def test_cancel_fences_while_advance_blocked_in_controller(self):
        entered = threading.Event()
        release = threading.Event()
        self.addCleanup(release.set)
        self.prepare(step(target="30", dwell="10"))
        self.runner.advance()
        original = self.backend.read_status

        def blocking():
            entered.set()
            if not release.wait(2):
                raise TimeoutError("Injected blocked poll")
            return original()

        self.backend.read_status = blocking
        worker = threading.Thread(target=lambda: self.runner.advance())
        worker.start()
        self.assertTrue(entered.wait(1))
        started = time.monotonic()
        self.runner.cancel("unit-chamber")
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, .3, "Cancel may not wait for synchronous I/O tick")
        release.set()
        worker.join(timeout=3)
        self.assertFalse(worker.is_alive())
        self.terminal(RunState.CANCELLED)
        self.assertFalse(self.backend._running)

    def test_prepared_revision_is_immutable_after_editor_save(self):
        snapshot = self.prepare()
        self.store.save_revision(
            "unit-chamber", snapshot.profile_id,
            ParsedProfile((step(target="40"),), name="edited"),
            expected_revision=1,
        )
        self.runner.advance()
        self.assertEqual(self.backend._target, 25)
        self.assertEqual(snapshot.revision, 1)
        self.runner.cancel("unit-chamber")
        self.terminal(RunState.CANCELLED)

    def test_foreign_operator_cannot_pause_but_can_authorize_cancel(self):
        self.prepare(step(dwell="20"))
        self.runner.advance()
        self.runner.advance()
        self.runner._authorize = lambda action, chamber: "another-operator"
        with self.assertRaisesRegex(ChamberSafetyError, "current operator"):
            self.runner.pause("unit-chamber")
        self.runner.cancel("unit-chamber")  # STOP independent of lease ownership
        self.terminal(RunState.CANCELLED)

    def test_first_step_transition_does_not_issue_setpoint_after_cancel(self):
        second = replace(step(target="30", dwell="2"), step=2)
        profile = ParsedProfile((step(), second), name="two steps")
        self.prepare(profile=profile)
        self.runner.advance()
        self.runner.advance()
        self.assertEqual(self.runner.state, RunState.TRANSITIONING)
        self.runner.cancel("unit-chamber")
        self.terminal(RunState.CANCELLED)
        self.assertEqual(self.backend._target, 25)

    def test_budget_resets_only_when_step_index_advances(self):
        second = replace(step(target="26"), step=2)
        self.prepare(profile=ParsedProfile((step(), second), name="two steps"))

        prepared = self.runner.budget_state()
        self.assertEqual(prepared["step_index"], 0)
        self.assertGreater(prepared["step_remaining_s"], 0)

        self.runner.advance()  # dispatch step 1 without extending its budget
        dispatched_first = self.runner.budget_state()
        self.assertEqual(dispatched_first["step_index"], 0)
        self.assertLessEqual(
            dispatched_first["step_remaining_s"], prepared["step_remaining_s"],
        )

        self.runner.advance()  # complete step 1 and allocate step 2 atomically
        started_second = self.runner.budget_state()
        self.assertEqual(started_second["step_index"], 1)
        self.assertGreater(started_second["step_remaining_s"], 0)

        self.runner.advance()  # dispatch step 2 without extending its budget
        dispatched_second = self.runner.budget_state()
        self.assertEqual(dispatched_second["step_index"], 1)
        self.assertLessEqual(
            dispatched_second["step_remaining_s"], started_second["step_remaining_s"],
        )
        self.runner.cancel("unit-chamber")
        stopping = self.runner.budget_state()
        self.assertTrue(stopping["stopping"])
        self.assertFalse(stopping["terminal"])
        self.terminal(RunState.CANCELLED)

    def test_cancel_cannot_overtake_durable_prepared_snapshot(self):
        entered = threading.Event()
        release = threading.Event()
        self.addCleanup(release.set)

        class PausedPrepare(CaptureSink):
            def prepare(self, snapshot):
                entered.set()
                if not release.wait(3):
                    raise TimeoutError("Injected journal stall")
                super().prepare(snapshot)

        self.runner._sink = PausedPrepare()
        header = self.store.create_profile("unit-chamber", ParsedProfile((step(),)))
        failures = []

        def start():
            try:
                self.runner.start("unit-chamber", header.profile_id, revision=1)
            except Exception as exc:
                failures.append(exc)

        worker = threading.Thread(target=start)
        worker.start()
        self.assertTrue(entered.wait(1))
        with self.assertRaisesRegex(ChamberSafetyError, "fully prepared"):
            self.runner.cancel("unit-chamber")
        self.assertFalse(self.backend._running)
        release.set()
        worker.join(timeout=3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(failures, [])
        self.runner.cancel("unit-chamber")
        self.terminal(RunState.CANCELLED)

    def test_prepared_sink_failure_prevents_all_commands(self):
        class FailingSink:
            def prepare(self, snapshot):
                raise OSError("Injected durable recorder failure")

            def emit(self, event):
                raise AssertionError("No events after failed prepare")

        self.runner._sink = FailingSink()
        header = self.store.create_profile("unit-chamber", ParsedProfile((step(),)))
        with self.assertRaises(OSError):
            self.runner.start("unit-chamber", header.profile_id, revision=1)
        self.assertIsNone(self.runner.state)
        self.assertFalse(self.backend._running)
        self.assertFalse(self.manager.health("unit-chamber").stop_latched)

    def test_repeated_poll_does_not_qualify_sparse_stabilization(self):
        self.prepare(step(stabilize="4"))
        self.runner.advance()
        self.runner.advance()
        self.clock.advance(6)
        self.runner.advance()
        self.assertEqual(self.runner.state, RunState.STABILIZING)
        self.clock.advance(3)
        self.runner.advance()
        self.assertEqual(self.runner.state, RunState.STABILIZING)
        self.clock.advance(1)
        self.runner.advance()
        self.terminal(RunState.COMPLETED)

    def test_closed_runner_rejects_new_starts(self):
        snapshot = self.prepare()
        self.runner.cancel("unit-chamber")
        self.terminal(RunState.CANCELLED)
        self.runner.close()
        with self.assertRaisesRegex(ChamberSafetyError, "Runner is closed"):
            self.runner.start("unit-chamber", snapshot.profile_id, revision=1)

    def test_post_stop_requires_explicit_reconciliation(self):
        self.prepare()
        self.runner.advance()
        self.runner.advance()
        self.terminal(RunState.COMPLETED)
        with self.assertRaises(ChamberSafetyError):
            self.manager.set_temperature("unit-chamber", 25)
        self.manager.reconcile_stop("unit-chamber")
        self.manager.set_temperature("unit-chamber", 25)


class AlternateFixtureTests(unittest.TestCase):
    def test_alternate_manufacturer_limits_and_same_runner_logic(self):
        with TemporaryDirectory() as directory:
            manager = ChamberManager(
                [ChamberConfig("alternate", "alternate_stub")],
                backend_factory=lambda config, **kwargs: DistinctAlternate("alternate"),
                lease_directory=Path(directory) / "lease",
            )
            manager.connect("alternate")
            try:
                store = ProfileStore(Path(directory) / "profiles.sqlite")
                profile = ParsedProfile((step(target="-5"),))
                record = store.create_profile("alternate", profile)
                backend = manager._controller._backend  # test fixture only
                backend._measured = -5
                runner = ProfileRunner(
                    manager, store, authorize=lambda action, chamber: "test",
                    clock=VirtualClock(),
                )
                try:
                    runner.start("alternate", record.profile_id, revision=1)
                    runner.advance()
                    runner.advance()
                    # G04 STOP confirmation is asynchronous. Poll until an
                    # explicit bounded wall-clock deadline, rather than relying
                    # on 0.5 s of runner scheduling under loaded Windows CI.
                    deadline = time.monotonic() + 10.0
                    while time.monotonic() < deadline:
                        if runner.advance() in (RunState.COMPLETED, RunState.UNKNOWN,
                                                RunState.FAULT):
                            break
                        time.sleep(.01)
                    self.assertEqual(runner.state, RunState.COMPLETED, runner.reason)
                    self.assertEqual(runner.snapshot.identity.backend_id, "alternate_stub")
                finally:
                    runner.close()
            finally:
                manager.disconnect("alternate")


if __name__ == "__main__":
    unittest.main()

class RampRunnerTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.clock = VirtualClock()
        self.backend = DistinctFake("unit-chamber",
                                    ramp_range_c_per_min=(0.5, 10.0))
        self.sink = CaptureSink()
        self.manager = ChamberManager(
            [ChamberConfig("unit-chamber", "fake")],
            backend_factory=lambda config, **kwargs: self.backend,
            lease_directory=self.root / "lease",
        )
        self.manager.connect("unit-chamber")
        self.addCleanup(self.manager.disconnect, "unit-chamber")
        self.store = ProfileStore(self.root / "profiles.sqlite")
        self.runner = ProfileRunner(
            self.manager, self.store, authorize=lambda action, chamber: "test-operator",
            sink=self.sink, clock=self.clock,
        )
        self.addCleanup(self.runner.close)

    def test_simulated_gradient_profile_dispatches_and_completes(self):
        header = self.store.create_profile(
            "unit-chamber", ParsedProfile((step(target="30", up="5", reach="600"),)),
        )
        self.runner.start("unit-chamber", header.profile_id, revision=1)
        self.runner.advance()
        self.assertEqual(self.backend._gradient_up, 5.0)
        self.assertIn("GRADIENT_INTENT", [event.kind for event in self.sink.events])
        self.backend._measured = 30
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if self.runner.advance() in (RunState.COMPLETED, RunState.FAULT,
                                         RunState.UNKNOWN):
                break
            time.sleep(0.005)
        self.assertEqual(self.runner.state, RunState.COMPLETED, self.runner.reason)

    def test_gradient_readback_mismatch_fails_closed(self):
        token = self.manager.claim_operator("unit-chamber", "test-operator")
        self.addCleanup(self.manager.release_operator, "unit-chamber", token)
        self.backend.set_ramp_up = lambda rate: None
        with self.assertRaises(ChamberSafetyError):
            self.manager.set_ramp_up("unit-chamber", 2.0, operator_token=token)

    def test_gradient_outside_declared_range_is_rejected(self):
        header = self.store.create_profile(
            "unit-chamber", ParsedProfile((step(target="30", up="20", reach="600"),)),
        )
        with self.assertRaises(ValueError):
            self.runner.start("unit-chamber", header.profile_id, revision=1)
        self.assertFalse(self.backend._running)
        self.assertIsNone(self.backend._gradient_up)


class SimulatedRampRegistryTests(unittest.TestCase):
    def test_simulated_gradients_are_opt_in(self):
        from unittest import mock
        from chamber_web.adapters.registry import make_backend

        with mock.patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("CHAMBER_SIM_RAMP_C_PER_MIN", None)
            default = make_backend(ChamberConfig("sim", "fake"))
            self.assertFalse(default.capabilities().supports_ramp_up)
            os.environ["CHAMBER_SIM_RAMP_C_PER_MIN"] = "0.1,10"
            ramp = make_backend(ChamberConfig("sim", "fake"))
            caps = ramp.capabilities()
            self.assertTrue(caps.supports_ramp_up and caps.supports_ramp_down)
            self.assertEqual(caps.ramp_up_range_c_per_min, (0.1, 10.0))
            os.environ["CHAMBER_SIM_RAMP_C_PER_MIN"] = "10,0.1"
            with self.assertRaises(ChamberSafetyError):
                make_backend(ChamberConfig("sim", "fake"))
