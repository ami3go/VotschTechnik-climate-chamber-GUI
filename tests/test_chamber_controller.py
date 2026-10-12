"""G04-A concurrency, STOP/fault fencing and mock-only regression tests."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from chamber_web.adapters.alternate_stub import AlternateStubBackend
from chamber_web.adapters.fake import FakeBackend
from chamber_web.adapters.votsch import VotschBackend
from chamber_web.domain.chamber import (
    ChamberConnectionError, ChamberError, ChamberSafetyError, ChamberSnapshot,
    OperationState, ReadingQuality,
)
from chamber_web.domain.config import ChamberConfig
from chamber_web.services.chamber_manager import ChamberManager


class CountingBackend(FakeBackend):
    def __init__(self, chamber_id):
        super().__init__(chamber_id)
        self.log = []

    def set_temperature(self, target):
        self.log.append(("set", target))
        super().set_temperature(target)

    def stop(self):
        self.log.append(("stop",))
        super().stop()


class SlowBackend(CountingBackend):
    def __init__(self, chamber_id):
        super().__init__(chamber_id)
        self.entered = threading.Event()
        self.release = threading.Event()

    def set_temperature(self, target):
        self.entered.set()
        if not self.release.wait(4):
            raise TimeoutError("Injected hung backend")
        super().set_temperature(target)


class LiesBackend(CountingBackend):
    def set_temperature(self, target):
        self.log.append(("ignored", target))


class FailingReadback(CountingBackend):
    def __init__(self, chamber_id):
        super().__init__(chamber_id)
        self.fail = False
        self.stale = False

    def read_status(self):
        snapshot = super().read_status()
        if self.fail:
            raise ConnectionError("Injected transport break")
        if self.stale:
            return ChamberSnapshot(
                snapshot.identity, snapshot.measured_temperature_c,
                snapshot.setpoint_temperature_c, snapshot.operation_state,
                ReadingQuality.GOOD, datetime.now(timezone.utc) - timedelta(minutes=2),
            )
        return snapshot


class PausedReadBackend(CountingBackend):
    def __init__(self, chamber_id):
        super().__init__(chamber_id)
        self.pause_reads = False
        self.entered = threading.Event()
        self.release = threading.Event()

    def read_status(self):
        if self.pause_reads:
            self.entered.set()
            if not self.release.wait(4):
                raise TimeoutError("Injected blocked status read")
        return super().read_status()


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)

    def manager(self, backend, *, timeout=1.0, backend_id="fake"):
        manager = ChamberManager(
            [ChamberConfig("device-1", backend_id)],
            backend_factory=lambda config, allow_test_backend=False: backend,
            lease_directory=self.directory,
            io_timeout_s=timeout,
            allow_test_backend=True,
        )
        self.addCleanup(self._cleanup_manager, manager)
        manager.connect("device-1")
        return manager

    @staticmethod
    def _cleanup_manager(manager):
        try:
            manager.disconnect("device-1")
        except ChamberError:
            pass

    def test_stop_invalidates_queued_setpoint_with_priority(self):
        backend = SlowBackend("device-1")
        manager = self.manager(backend, timeout=3.0)
        errors = []
        def setpoint(value):
            try:
                manager.set_temperature("device-1", value)
            except ChamberError as exc:
                errors.append(str(exc))

        first = threading.Thread(target=setpoint, args=(30,))
        second = threading.Thread(target=setpoint, args=(40,))
        first.start()
        self.assertTrue(backend.entered.wait(1))
        second.start()
        # Ensure second request is enqueued before the STOP intent.
        deadline = time.monotonic() + 2
        while manager._controller._queue.qsize() < 1 and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertEqual(manager._controller._queue.qsize(), 1)
        stopped = threading.Event()
        failures = []
        def stop():
            try:
                manager.stop("device-1")
            except Exception as exc:
                failures.append(exc)
            finally:
                stopped.set()
        stopping = threading.Thread(target=stop)
        stopping.start()
        deadline = time.monotonic() + 1
        while not manager.health("device-1").stop_latched and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertTrue(manager.health("device-1").stop_latched)
        with self.assertRaises(ChamberSafetyError):
            manager.start("device-1")
        backend.release.set()
        for thread in (first, second, stopping):
            thread.join(timeout=4)
            self.assertFalse(thread.is_alive())
        self.assertFalse(failures, str(failures))
        self.assertEqual(backend.log, [("set", 30.0), ("stop",)])
        self.assertTrue(errors)
        self.assertEqual(manager.health("device-1").state, "VERIFIED_STOPPED")
        self.assertTrue(manager.health("device-1").stop_latched)
        with self.assertRaises(ChamberSafetyError):
            manager.set_temperature("device-1", 60)
        manager.reconcile_stop("device-1")
        manager.set_temperature("device-1", 60)

    def test_mismatched_setpoint_latches_unknown_and_requires_manual_reconcile(self):
        backend = LiesBackend("device-1")
        manager = self.manager(backend)
        with self.assertRaisesRegex(ChamberSafetyError, "Setpoint readback"):
            manager.set_temperature("device-1", 31)
        self.assertEqual(manager.health("device-1").state, "UNKNOWN")
        with self.assertRaises(ChamberSafetyError):
            manager.start("device-1")
        manager.reconcile_stop("device-1")
        self.assertFalse(manager.health("device-1").stop_latched)

    def test_stop_transport_failure_is_not_verified(self):
        backend = FailingReadback("device-1")
        manager = self.manager(backend)
        manager.start("device-1")
        backend.fail = True
        with self.assertRaises(ChamberConnectionError):
            manager.stop("device-1")
        self.assertIn(manager.health("device-1").state, ("UNKNOWN", "FAULT"))
        self.assertTrue(manager.health("device-1").stop_latched)
        with self.assertRaises(ChamberConnectionError):
            manager.reconcile_stop("device-1")
        self.assertEqual(manager.status("device-1").operation_state, OperationState.UNKNOWN)
        self.assertNotEqual(manager.health("device-1").state, "VERIFIED_STOPPED")

    def test_expired_setpoint_does_not_release_lock_or_continue_queued_writes(self):
        backend = SlowBackend("device-1")
        manager = self.manager(backend, timeout=0.15)
        self.addCleanup(backend.release.set)
        errors = []
        def setpoint():
            try:
                manager.set_temperature("device-1", 33)
            except ChamberError as exc:
                errors.append(str(exc))
        thread = threading.Thread(target=setpoint)
        thread.start()
        self.assertTrue(backend.entered.wait(1))
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertTrue(errors)
        self.assertEqual(manager.health("device-1").state, "UNKNOWN")
        with self.assertRaises(ChamberSafetyError):
            self.manager(CountingBackend("device-1"), timeout=0.15)
        with self.assertRaises(ChamberSafetyError):
            manager.set_temperature("device-1", 40)
        backend.release.set()
        # A short command deadline is NOT a shutdown allowance for the
        # fault-injection worker once its test gate is released.
        manager._controller._timeout = 2.0
        manager.disconnect("device-1")

    def test_running_readback_after_verified_stop_is_unknown(self):
        backend = CountingBackend("device-1")
        manager = self.manager(backend)
        manager.stop("device-1")
        backend.start()  # unexpected external state change, mock only
        snapshot = manager.status("device-1")
        self.assertEqual(snapshot.operation_state, OperationState.RUNNING)
        self.assertEqual(manager.health("device-1").state, "UNKNOWN")
        self.assertTrue(manager.health("device-1").stop_latched)

    def test_concurrent_stop_cannot_be_cleared_by_delayed_reconcile(self):
        class PausedStatus(CountingBackend):
            def __init__(self, chamber_id):
                super().__init__(chamber_id)
                self.pause = False
                self.entered = threading.Event()
                self.release = threading.Event()

            def read_status(self):
                if self.pause:
                    self.entered.set()
                    if not self.release.wait(4):
                        raise TimeoutError("Injected delayed reconcile")
                return super().read_status()

        backend = PausedStatus("device-1")
        manager = self.manager(backend, timeout=3)
        manager.stop("device-1")
        initial_gen = manager.health("device-1").generation
        backend.pause = True
        failures = []

        def reconcile():
            try:
                manager.reconcile_stop("device-1")
            except ChamberSafetyError as exc:
                failures.append(str(exc))

        reconciling = threading.Thread(target=reconcile)
        reconciling.start()
        self.assertTrue(backend.entered.wait(1))
        backend.pause = False
        stopping = threading.Thread(target=lambda: manager.stop("device-1"))
        stopping.start()
        deadline = time.monotonic() + 2
        while manager.health("device-1").generation == initial_gen and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertGreater(manager.health("device-1").generation, initial_gen)
        backend.release.set()
        for thread in (reconciling, stopping):
            thread.join(timeout=4)
            self.assertFalse(thread.is_alive())
        self.assertTrue(failures, "Old reconciliation must not clear a new STOP fence")
        self.assertTrue(manager.health("device-1").stop_latched)
        self.assertEqual(manager.health("device-1").state, "VERIFIED_STOPPED")

    def test_unreconciled_stop_persists_across_restart(self):
        manager = self.manager(CountingBackend("device-1"))
        manager.stop("device-1")
        self.assertTrue(manager.health("device-1").stop_latched)
        manager.disconnect("device-1")
        other = self.manager(CountingBackend("device-1"))
        self.assertTrue(other.health("device-1").stop_latched)
        with self.assertRaises(ChamberSafetyError):
            other.start("device-1")
        other.reconcile_stop("device-1")
        other.start("device-1")

    def test_stale_readback_fences_writes(self):
        backend = FailingReadback("device-1")
        manager = self.manager(backend)
        backend.stale = True
        with self.assertRaises(ChamberSafetyError):
            manager.start("device-1")
        self.assertTrue(manager.health("device-1").stop_latched)
        self.assertEqual(manager.status("device-1").quality, ReadingQuality.ERROR)

    def test_operator_handover_fences_old_queued_write(self):
        backend = PausedReadBackend("device-1")
        manager = self.manager(backend, timeout=3.0)
        owner_a = manager.claim_operator("device-1", "alice")
        backend.pause_reads = True
        self.addCleanup(backend.release.set)
        poll = threading.Thread(target=lambda: manager.status("device-1"))
        poll.start()
        self.assertTrue(backend.entered.wait(1))
        errors = []
        def setpoint():
            try:
                manager.set_temperature("device-1", 40, operator_token=owner_a)
            except ChamberError as exc:
                errors.append(str(exc))
        queued = threading.Thread(target=setpoint)
        queued.start()
        deadline = time.monotonic() + 2
        while manager._controller._queue.qsize() < 1 and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertGreaterEqual(manager._controller._queue.qsize(), 1)
        manager.release_operator("device-1", owner_a)
        owner_b = manager.claim_operator("device-1", "bob")
        backend.pause_reads = False
        backend.release.set()
        for thread in (poll, queued):
            thread.join(timeout=4)
            self.assertFalse(thread.is_alive())
        self.assertEqual(backend.log, [])
        self.assertTrue(errors, "Old queued owner may not write after handover")
        manager.set_temperature("device-1", 41, operator_token=owner_b)
        self.assertEqual(backend.log, [("set", 41.0)])

    def test_disconnect_fences_queued_mutation_before_backend_io(self):
        backend = PausedReadBackend("device-1")
        manager = self.manager(backend, timeout=3.0)
        backend.pause_reads = True
        self.addCleanup(backend.release.set)
        poll = threading.Thread(target=lambda: manager.status("device-1"))
        poll.start()
        self.assertTrue(backend.entered.wait(1))
        errors = []
        def setpoint():
            try:
                manager.set_temperature("device-1", 42)
            except ChamberError as exc:
                errors.append(str(exc))
        queued = threading.Thread(target=setpoint)
        queued.start()
        deadline = time.monotonic() + 2
        while manager._controller._queue.qsize() < 1 and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertGreaterEqual(manager._controller._queue.qsize(), 1)
        shutdown = threading.Thread(target=lambda: manager.disconnect("device-1"))
        shutdown.start()
        deadline = time.monotonic() + 2
        while not manager._controller._disconnecting and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertTrue(manager._controller._disconnecting)
        backend.pause_reads = False
        backend.release.set()
        for thread in (poll, queued, shutdown):
            thread.join(timeout=4)
            self.assertFalse(thread.is_alive())
        self.assertEqual(backend.log, [], "No setpoint allowed after disconnect intent")
        self.assertTrue(errors)
        self.assertEqual(manager.health("device-1").state, "DISCONNECTED")

    def test_inflight_start_during_disconnect_preserves_restart_uncertainty(self):
        class BlockedStart(CountingBackend):
            def __init__(self, chamber_id):
                super().__init__(chamber_id)
                self.entered = threading.Event()
                self.release = threading.Event()

            def start(self):
                self.entered.set()
                if not self.release.wait(4):
                    raise TimeoutError("Injected in-flight START")
                super().start()

        backend = BlockedStart("device-1")
        manager = self.manager(backend, timeout=3.0)
        self.addCleanup(backend.release.set)
        errors = []

        def start():
            try:
                manager.start("device-1")
            except ChamberError as exc:
                errors.append(str(exc))

        starting = threading.Thread(target=start)
        starting.start()
        self.assertTrue(backend.entered.wait(1))
        shutdown = threading.Thread(target=lambda: manager.disconnect("device-1"))
        shutdown.start()
        deadline = time.monotonic() + 2
        while not manager._controller._disconnecting and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertTrue(manager._controller._disconnecting)
        backend.release.set()
        for thread in (starting, shutdown):
            thread.join(timeout=4)
            self.assertFalse(thread.is_alive())
        self.assertTrue(errors, "START cannot succeed after shutdown fence")
        self.assertFalse(backend._running, "Mock must be disconnected")
        recovered = self.manager(CountingBackend("device-1"))
        self.assertTrue(
            recovered.health("device-1").stop_latched,
            "An in-flight START after the prior sample must preserve uncertainty",
        )
        with self.assertRaises(ChamberSafetyError):
            recovered.start("device-1")
        recovered.reconcile_stop("device-1")
        recovered.start("device-1")

    def test_stale_pre_disconnect_readback_requires_reconciliation_after_restart(self):
        manager = self.manager(CountingBackend("device-1"))
        good = manager.status("device-1")
        manager._controller._last_snapshot = replace(
            good, sampled_at_utc=datetime.now(timezone.utc) - timedelta(minutes=2),
        )
        manager.disconnect("device-1")
        recovered = self.manager(CountingBackend("device-1"))
        self.assertTrue(recovered.health("device-1").stop_latched)
        with self.assertRaises(ChamberSafetyError):
            recovered.start("device-1")
        recovered.reconcile_stop("device-1")
        recovered.start("device-1")

    def test_operator_conflict_does_not_block_stop(self):
        backend = CountingBackend("device-1")
        manager = self.manager(backend)
        token = manager.claim_operator("device-1", "operator-a")
        with self.assertRaises(ChamberSafetyError):
            manager.set_temperature("device-1", 30)
        with self.assertRaises(ChamberSafetyError):
            manager.claim_operator("device-1", "operator-b")
        manager.start("device-1", operator_token=token)
        manager.stop("device-1")  # no owner token required
        self.assertIn(("stop",), backend.log)
        manager.release_operator("device-1", token)

    def test_v1_rejects_two_live_mock_controllers_even_with_distinct_ids(self):
        first = self.manager(CountingBackend("device-1"))
        other = ChamberManager(
            [ChamberConfig("device-2", "fake")],
            backend_factory=lambda cfg, **kwargs: CountingBackend(cfg.chamber_id),
            lease_directory=self.directory / "separate-lease-root",
        )
        with self.assertRaisesRegex(ChamberSafetyError, "one active controller"):
            other.connect("device-2")
        self.assertTrue(first.health("device-1").connected)

    def test_wrong_id_and_second_manager_never_touch_backend(self):
        backend = CountingBackend("device-1")
        manager = self.manager(backend)
        with self.assertRaises(ChamberSafetyError):
            manager.stop("another")
        with self.assertRaises(ChamberSafetyError):
            manager.start("another")
        with self.assertRaises(ChamberSafetyError):
            manager.set_temperature("another", 35)
        self.assertEqual(backend.log, [])
        with self.assertRaisesRegex(ChamberSafetyError, "already owned"):
            self.manager(CountingBackend("device-1"))

    def test_restart_after_uncertain_state_blocks_writes(self):
        backend = LiesBackend("device-1")
        manager = self.manager(backend)
        with self.assertRaises(ChamberSafetyError):
            manager.set_temperature("device-1", 45)
        manager.disconnect("device-1")
        other = self.manager(CountingBackend("device-1"))
        self.assertTrue(other.health("device-1").stop_latched)
        with self.assertRaises(ChamberSafetyError):
            other.start("device-1")
        other.reconcile_stop("device-1")
        other.start("device-1")

    def test_alternate_vendor_substitution_and_bounds(self):
        manager = self.manager(AlternateStubBackend("device-1"), backend_id="alternate_stub")
        with self.assertRaises(ChamberSafetyError):
            manager.set_temperature("device-1", 51)
        manager.set_temperature("device-1", 40)
        manager.start("device-1")
        manager.stop("device-1")

    def test_os_lock_excludes_a_second_process(self):
        script = (
            "import sys; from chamber_web.services.ownership import DeviceLease; "
            "from pathlib import Path; l=DeviceLease('device-1', Path(sys.argv[1])); "
            "l.acquire(); print('READY', flush=True); sys.stdin.readline(); l.close()"
        )
        proc = subprocess.Popen(
            [sys.executable, "-u", "-c", script, str(self.directory)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True,
        )
        try:
            self.assertEqual(proc.stdout.readline().strip(), "READY")
            with self.assertRaises(ChamberSafetyError):
                self.manager(CountingBackend("device-1"))
        finally:
            if proc.stdin:
                proc.stdin.write("\n")
                proc.stdin.flush()
            try:
                proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate(timeout=5)

    def test_votsch_mock_substitution_without_vendor_branches(self):
        class Driver:
            test_system_type = "VT4011-MOCK"
            serial_number = "MOCK-1"
            temperature_measured = 25.0
            temperature_set_point = 25.0
            is_running = False

            def disconnect(self):
                pass

            def start(self):
                self.is_running = True

            def stop(self):
                self.is_running = False

        mock = VotschBackend(
            "device-1", "example.invalid", mock_driver_factory=Driver,
        )
        manager = self.manager(mock, backend_id="votsch")
        manager.set_temperature("device-1", 26)
        manager.start("device-1")
        manager.stop("device-1")

    def test_physical_backend_denied_before_connect(self):
        class Physical:
            called = False
            def connect(self):
                self.called = True

        backend = Physical()
        manager = ChamberManager(
            [ChamberConfig("device-1", "votsch", "192.0.2.1")],
            backend_factory=lambda config, allow_test_backend=False: backend,
            lease_directory=self.directory,
        )
        with self.assertRaisesRegex(ChamberSafetyError, "DISABLED"):
            manager.connect("device-1")
        self.assertFalse(backend.called)


if __name__ == "__main__":
    unittest.main()
