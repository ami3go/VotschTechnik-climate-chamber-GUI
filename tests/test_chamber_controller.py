"""G04-A concurrency, STOP/fault fencing and mock-only regression tests."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from chamber_web.adapters.alternate_stub import AlternateStubBackend
from chamber_web.adapters.fake import FakeBackend
from chamber_web.adapters.votsch import VotschBackend
from chamber_web.domain.chamber import (
    ChamberSafetyError, ChamberSnapshot, OperationState, ReadingQuality,
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
        except ChamberSafetyError:
            pass

    def test_stop_invalidates_queued_setpoint_with_priority(self):
        backend = SlowBackend("device-1")
        manager = self.manager(backend, timeout=3.0)
        errors = []
        def setpoint(value):
            try:
                manager.set_temperature("device-1", value)
            except ChamberSafetyError as exc:
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
        with self.assertRaises(ConnectionError):
            manager.stop("device-1")
        self.assertIn(manager.health("device-1").state, ("UNKNOWN", "FAULT"))
        self.assertTrue(manager.health("device-1").stop_latched)
        with self.assertRaises(ChamberSafetyError):
            manager.reconcile_stop("device-1")
        self.assertEqual(manager.status("device-1").operation_state, OperationState.UNKNOWN)
        self.assertNotEqual(manager.health("device-1").state, "VERIFIED_STOPPED")

    def test_expired_setpoint_does_not_release_lock_or_continue_queued_writes(self):
        backend = SlowBackend("device-1")
        manager = self.manager(backend, timeout=0.15)
        errors = []
        def setpoint():
            try:
                manager.set_temperature("device-1", 33)
            except ChamberSafetyError as exc:
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

    def test_stale_readback_fences_writes(self):
        backend = FailingReadback("device-1")
        manager = self.manager(backend)
        backend.stale = True
        with self.assertRaises(ChamberSafetyError):
            manager.start("device-1")
        self.assertTrue(manager.health("device-1").stop_latched)
        self.assertEqual(manager.status("device-1").quality, ReadingQuality.ERROR)

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
