"""G07-A + merged G06-A integration, using two separate mock-only instances."""
from __future__ import annotations

import errno
import io
import time
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
from zipfile import ZipFile

from chamber_web.adapters.alternate_stub import AlternateStubBackend
from chamber_web.adapters.fake import FakeBackend
from chamber_web.domain.config import ChamberConfig
from chamber_web.domain.profile import ParsedProfile, ProfileStep
from chamber_web.execution.profile_runner import ProfileRunner, RunEvent, RunState, VirtualClock
from chamber_web.persistence.profiles import ProfileStore
from chamber_web.persistence.runs import RunIntegrityError, RunRecorder, RunStore
from chamber_web.services.chamber_manager import ChamberManager


class DistinctTimestamp:
    """Independent valid simulator timestamps even with coarse Windows clocks."""

    def read_status(self):
        value = super().read_status()
        if value.sampled_at_utc is None:
            return value
        previous = getattr(self, "_last_unique", None)
        when = value.sampled_at_utc
        if previous is not None and when <= previous:
            when = previous + timedelta(microseconds=1)
        self._last_unique = when
        return replace(value, sampled_at_utc=when)


class FakeChamber(DistinctTimestamp, FakeBackend):
    pass


class OtherChamber(DistinctTimestamp, AlternateStubBackend):
    pass


def profile_step(target: str) -> ProfileStep:
    return ProfileStep(
        1, True, Decimal(target), None, None, Decimal("1"),
        Decimal("0"), Decimal("0"), Decimal("30"), "integration",
    )


class RecordingRunnerIntegration(unittest.TestCase):
    @staticmethod
    def exercise(backend_type, chamber_id, backend_id, target):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            backend = backend_type(chamber_id)
            manager = ChamberManager(
                [ChamberConfig(chamber_id, backend_id)],
                backend_factory=lambda config, **kwargs: backend,
                lease_directory=root / "ownership",
            )
            manager.connect(chamber_id)
            runner = None
            try:
                backend._measured = float(target)
                profiles = ProfileStore(root / "profiles.sqlite")
                header = profiles.create_profile(
                    chamber_id, ParsedProfile((profile_step(target),),
                                              name="integration-simulated"),
                )
                runs = RunStore(root)
                runner = ProfileRunner(
                    manager, profiles, authorize=lambda action, cid: "test-operator",
                    sink=RunRecorder(runs), clock=VirtualClock(),
                )
                frozen = runner.start(chamber_id, header.profile_id, revision=1)
                with runs._read() as db:
                    prepared = runs._find(db, chamber_id, frozen.run_id)
                    assert prepared["lifecycle"] == "PREPARED"
                    assert prepared["event_count"] == 1
                # These commands are simulated G04 I/O only. START_INTENT has
                # to commit before either the first setpoint or START dispatch.
                runner.advance()
                assert runs.get_run(chamber_id, frozen.run_id)["event_count"] >= 3
                runner.advance()
                for _ in range(150):
                    if runner.advance() in {
                        RunState.COMPLETED, RunState.CANCELLED,
                        RunState.UNKNOWN, RunState.FAULT,
                    }:
                        break
                    time.sleep(0.005)
                assert runner.state is RunState.COMPLETED, runner.reason
                evidence = runs.get_run(chamber_id, frozen.run_id)
                assert evidence["lifecycle"] == "COMPLETED"
                assert evidence["sample_count"] >= 1
                assert runs.verify_artifacts(chamber_id, frozen.run_id)["sample_count"] >= 1
                events = runs.list_events(chamber_id, frozen.run_id, limit=100)
                kinds = [row["kind"] for row in events]
                assert kinds[0] == "PREPARED"
                assert kinds.index("START_INTENT") < kinds.index("SETPOINT_INTENT")
                assert kinds.index("STOP_INTENT") < kinds.index("TERMINAL")
                assert runs.reconcile_startup() == []  # No fabricated recovery
                assert frozen.identity.is_simulation
                assert not backend._running
            finally:
                if runner is not None:
                    runner.close()
                manager.disconnect(chamber_id)

    def test_runner_fakebackend_event_sink(self):
        self.exercise(FakeChamber, "sim-1", "fake", "25")

    def test_runner_alternate_vendor_adapter_event_sink(self):
        self.exercise(OtherChamber, "other-1", "alternate_stub", "-5")

    def test_cancel_persists_stop_recovery_and_rejects_tamper(self):
        # One physical-controller simulation; never import or instantiate the
        # manufacturer adapter. Normal cancel verifies STOP, while a separate
        # committed STOP_INTENT lacking TERMINAL recovers conservatively.
        with TemporaryDirectory() as directory:
            root = Path(directory)
            chamber_id = "stop-recovery-sim"
            backend = FakeChamber(chamber_id)
            manager = ChamberManager(
                [ChamberConfig(chamber_id, "fake")],
                backend_factory=lambda config, **kwargs: backend,
                lease_directory=root / "ownership",
            )
            manager.connect(chamber_id)
            runner = None
            try:
                backend._measured = 25.0
                profiles = ProfileStore(root / "profiles.sqlite")
                header = profiles.create_profile(
                    chamber_id, ParsedProfile((profile_step("25"),), name="stop-test"),
                )
                store = RunStore(root)
                runner = ProfileRunner(
                    manager, profiles, authorize=lambda action, cid: "test-operator",
                    sink=RunRecorder(store), clock=VirtualClock(),
                )
                snapshot = runner.start(chamber_id, header.profile_id, revision=1)
                runner.advance()
                self.assertTrue(backend._running)
                self.assertEqual(store.list_events(chamber_id, snapshot.run_id)[0]["kind"], "PREPARED")
                runner.cancel(chamber_id)
                for _ in range(150):
                    if runner.advance() in {RunState.CANCELLED, RunState.UNKNOWN, RunState.FAULT}:
                        break
                    time.sleep(0.005)
                self.assertEqual(runner.state, RunState.CANCELLED, runner.reason)
                self.assertFalse(backend._running)
                self.assertEqual(store.get_run(chamber_id, snapshot.run_id)["terminal_state"], "ABORTED")
                events = store.list_events(chamber_id, snapshot.run_id, limit=100)
                kinds = [e["kind"] for e in events]
                self.assertLess(kinds.index("START_INTENT"), kinds.index("STOP_INTENT"))
                self.assertLess(kinds.index("STOP_INTENT"), kinds.index("TERMINAL"))
                evidence = store.read_zip(chamber_id, snapshot.run_id)
                with ZipFile(io.BytesIO(evidence)) as archive:
                    self.assertEqual(set(archive.namelist()),
                                     {"manifest.json", "snapshot.json", "events.csv", "samples.csv"})

                # A killed process after durable STOP_INTENT has *no* terminal
                # evidence. Reconciliation is journal-only; do not replay G04.
                incomplete = replace(snapshot, run_id=str(uuid4()))
                sink = RunRecorder(store)
                sink.prepare(incomplete)
                utc = datetime.now(timezone.utc).isoformat()
                for sequence, kind, state in (
                    (1, "PREPARED", RunState.PREPARING),
                    (2, "START_INTENT", RunState.PREPARING),
                    (3, "STOP_INTENT", RunState.STOP_REQUESTED),
                ):
                    sink.emit(RunEvent(incomplete.run_id, chamber_id, sequence,
                                      kind, state, float(sequence), 0,
                                      observed_at_utc=utc))
                reopened = RunStore(root)
                self.assertEqual(reopened.reconcile_startup(),
                                 [(chamber_id, incomplete.run_id, "UNKNOWN")])
                self.assertEqual(reopened.verify_artifacts(
                    chamber_id, incomplete.run_id)["terminal_state"], "UNKNOWN")
                self.assertEqual(reopened.reconcile_startup(), [])
                self.assertFalse(backend._running)  # Reconciliation never starts it.

                archive_dir = store._directory(chamber_id, snapshot.run_id)
                (archive_dir / "events.csv").write_bytes(b"tampered")
                with self.assertRaises(RunIntegrityError):
                    reopened.read_zip(chamber_id, snapshot.run_id)
            finally:
                if runner is not None:
                    runner.close()
                manager.disconnect(chamber_id)

    def test_intent_disk_failure_fences_first_device_mutation(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            backend = FakeChamber("sim-denial")
            manager = ChamberManager(
                [ChamberConfig("sim-denial", "fake")],
                backend_factory=lambda config, **kwargs: backend,
                lease_directory=root / "ownership",
            )
            manager.connect("sim-denial")
            runner = None
            try:
                profiles = ProfileStore(root / "profiles.sqlite")
                header = profiles.create_profile(
                    "sim-denial", ParsedProfile((profile_step("25"),)),
                )
                runs = RunStore(root)

                class FailingIntent(RunRecorder):
                    def emit(self, event):
                        if event.kind == "START_INTENT":
                            raise OSError(errno.ENOSPC, "injected disk full before command")
                        return super().emit(event)

                runner = ProfileRunner(
                    manager, profiles, authorize=lambda action, cid: "test",
                    sink=FailingIntent(runs), clock=VirtualClock(),
                )
                snapshot = runner.start("sim-denial", header.profile_id, revision=1)
                runner.advance()
                # G06 may request a STOP on failure, but must never have
                # written initial setpoint or dispatched chamber START.
                assert not backend._running
                events = runs.list_events("sim-denial", snapshot.run_id)
                assert "START_INTENT" not in [row["kind"] for row in events]
                for _ in range(150):
                    if runner.advance() in {
                        RunState.COMPLETED, RunState.CANCELLED,
                        RunState.UNKNOWN, RunState.FAULT,
                    }:
                        break
                    time.sleep(0.005)
                assert runner.state in (RunState.UNKNOWN, RunState.FAULT)
                assert not backend._running
            finally:
                if runner is not None:
                    runner.close()
                manager.disconnect("sim-denial")


if __name__ == "__main__":
    unittest.main()
