"""H02-C: independent watchdog process, supervision host and STOP wiring.

No test here touches hardware: the child protocol tests speak to a real
watchdog subprocess over an authenticated loopback socket; host/runner/service
tests use mock backends, a stub supervisor or the real host process.
"""
from __future__ import annotations

import base64
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest

from multiprocessing.connection import (
    Connection, answer_challenge, deliver_challenge,
)

from chamber_web.adapters.fake import FakeBackend
from chamber_web.domain.chamber import OperationState, ReadingQuality
from chamber_web.domain.config import ChamberConfig
from chamber_web.domain.profile import ParsedProfile, ProfileStep
from chamber_web.execution.profile_runner import (
    TERMINAL, ProfileRunner, RunParameters, RunState, SupervisedRun, VirtualClock,
)
from chamber_web.hil import watchdog_protocol as wp
from chamber_web.hil.profile_admission import AdmissionDenied, H02WatchdogLimits
from chamber_web.hil.supervised_profile import (
    ENV_PERMIT_FILE, ENV_TRUSTED_KEY, SupervisedProfileRuntime,
    load_supervised_permit,
)
from chamber_web.hil.supervision import SupervisionHost
from chamber_web.hil.watchdog_process import AUTHKEY_ENV
from chamber_web.persistence.profiles import ProfileStore
from chamber_web.security.auth import SecurityStore
from chamber_web.services.chamber_manager import ChamberManager
from chamber_web.services.profile_execution import ProfileExecutionService

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
except ImportError:
    Ed25519PrivateKey = None

CHAMBER = "unit-chamber"
SERIAL = "SN-H02-C-1"
GUI_COMMIT = "b" * 40
DRIVER_COMMIT = "c" * 40
WITNESS = "witness-c1"
REPO_ROOT = Path(__file__).resolve().parents[1]


def fast_limits() -> H02WatchdogLimits:
    """One-second deadlines so fault paths run quickly but reliably."""
    return H02WatchdogLimits(
        1, 1.0, 1.0, 1.0, 1.0, 6.0, 1.0, 1.0, 1.0, 1.0, 1.0,
    )


def child_limits_dict() -> dict:
    return asdict(fast_limits())


def permit_limits_dict() -> dict:
    """Limits for permit-level service tests: the message-level child limits
    with generous whole-run/step deadlines so preflight budgets admit."""
    return {**child_limits_dict(),
            "profile_step_deadline_s": 120.0, "whole_profile_deadline_s": 300.0}


def wait_for(predicate, timeout=8.0, interval=0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def read_jsonl(path) -> list[dict]:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return []
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def evidence_events(records) -> list[str]:
    return [record.get("event") for record in records]


def armed_heartbeat(**overrides) -> dict:
    message = {
        "type": wp.HEARTBEAT, "seq": 0, "state": wp.STATE_ARMED,
        "generation": 3, "expected_generation": 3,
        "step_index": 0, "step_remaining_s": 0.4, "whole_remaining_s": 3.0,
        "telemetry_age_s": 0.1, "owner_ok": True, "recorder_ok": True,
        "temp_ok": True,
    }
    message.update(overrides)
    return message


class ChildHarness:
    """Authenticated host side of one real watchdog subprocess."""

    def __init__(self, root: Path, *, limits: dict | None = None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.evidence = str(self.root / "child.jsonl")
        self.limits = limits or child_limits_dict()
        self.config = {
            "limits": self.limits, "chamber_id": CHAMBER, "serial_number": SERIAL,
        }
        self.authkey = secrets.token_bytes(32)
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(1)
        self.server.settimeout(15)
        port = self.server.getsockname()[1]
        environment = dict(os.environ)
        environment[AUTHKEY_ENV] = base64.b64encode(self.authkey).decode("ascii")
        environment["PYTHONPATH"] = os.pathsep.join(
            [str(REPO_ROOT), environment.get("PYTHONPATH", "")]).rstrip(os.pathsep)
        self.process = subprocess.Popen(
            [sys.executable, "-m", "chamber_web.hil.watchdog_process",
             "--port", str(port), "--evidence", self.evidence],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, env=environment, cwd=str(REPO_ROOT),
        )
        self.process.stdin.write(json.dumps(self.config).encode("utf-8"))
        self.process.stdin.close()
        self.connection: Connection | None = None

    def handshake(self) -> None:
        raw, _ = self.server.accept()
        raw.settimeout(None)
        connection = Connection(raw.detach())
        deliver_challenge(connection, self.authkey)
        answer_challenge(connection, self.authkey)
        self.connection = connection
        ready = self.receive()
        assert ready is not None and ready.get("type") == wp.READY, ready
        assert ready.get("protocol") == wp.PROTOCOL_VERSION, ready
        connection.send({
            "type": wp.CONFIG, "protocol": wp.PROTOCOL_VERSION,
            **self.limits, "chamber_id": CHAMBER, "serial_number": SERIAL,
        })
        ack = self.receive()
        assert ack is not None and ack.get("type") == wp.ACK, ack

    def send(self, message: dict) -> None:
        assert self.connection is not None
        self.connection.send(message)

    def receive(self, timeout: float = 5.0):
        connection = self.connection
        if connection is None or not connection.poll(timeout):
            return None
        return connection.recv()

    def collect(self, timeout: float = 2.0) -> list[dict]:
        messages = []
        while True:
            message = self.receive(timeout if not messages else 0.5)
            if message is None:
                return messages
            messages.append(message)

    def expect_exit(self, code: int, timeout: float = 10.0) -> None:
        self.process.wait(timeout=timeout)
        assert self.process.returncode == code, (
            self.process.returncode, read_jsonl(self.evidence))

    def close(self) -> None:
        try:
            if self.connection is not None:
                self.connection.close()
        except OSError:
            pass
        if self.process.poll() is None:
            self.process.kill()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        try:
            self.server.close()
        except OSError:
            pass


class WatchdogProtocolTests(unittest.TestCase):
    def test_limits_validation_matches_the_v1_schema(self):
        valid = child_limits_dict()
        wp.validate_limits(valid)
        for broken in (
            {**valid, "extra": 1.0},
            {key: value for key, value in valid.items() if key != "cleanup_timeout_s"},
            {**valid, "schema_version": 2},
            {**valid, "cleanup_timeout_s": 0},
            {**valid, "cleanup_timeout_s": -1.0},
            {**valid, "cleanup_timeout_s": True},
            {**valid, "cleanup_timeout_s": "1.0"},
            {**valid, "readback_deadline_s": 5.5},
            {**valid, "max_telemetry_gap_s": 5.5},
            {**valid, "profile_step_deadline_s": 7.0},
        ):
            with self.subTest(broken=broken), self.assertRaises(
                    wp.WatchdogProtocolError):
                wp.validate_limits(broken)

    def test_invalid_launch_config_exits_four_without_connecting(self):
        with TemporaryDirectory() as tmp:
            evidence = str(Path(tmp) / "child.jsonl")
            environment = dict(os.environ)
            environment[AUTHKEY_ENV] = base64.b64encode(bytes(32)).decode()
            environment["PYTHONPATH"] = str(REPO_ROOT)
            process = subprocess.Popen(
                [sys.executable, "-m", "chamber_web.hil.watchdog_process",
                 "--port", "1", "--evidence", evidence],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, env=environment, cwd=str(REPO_ROOT),
            )
            process.stdin.write(json.dumps({
                "limits": {"schema_version": 2},
                "chamber_id": CHAMBER, "serial_number": SERIAL,
            }).encode("utf-8"))
            process.stdin.close()
            process.wait(timeout=15)
            self.assertEqual(process.returncode, wp.EXIT_CONFIG_INVALID)
            self.assertIn("CONFIG_INVALID", evidence_events(read_jsonl(evidence)))


class WatchdogChildTests(unittest.TestCase):
    """Protocol, fault-detection and exit-code behavior of the child process."""

    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self._sequence = 0

    def _harness(self, *, limits=None) -> ChildHarness:
        self._sequence += 1
        harness = ChildHarness(self.root / f"child-{self._sequence}", limits=limits)
        self.addCleanup(harness.close)
        harness.handshake()
        return harness

    def _stop_reasons(self, harness: ChildHarness) -> list[str]:
        return [record["reason"] for record in read_jsonl(harness.evidence)
                if record.get("event") == "FAULT"]

    def test_handshake_heartbeat_and_clean_shutdown(self):
        harness = self._harness()
        harness.send(armed_heartbeat(seq=0, state=wp.STATE_IDLE))
        ack = harness.receive()
        self.assertEqual(ack, {"type": wp.ACK, "seq": 0})
        harness.send({"type": wp.SHUTDOWN})
        harness.expect_exit(0)
        events = evidence_events(read_jsonl(harness.evidence))
        self.assertIn("CHILD_START", events)
        self.assertIn("CHILD_READY", events)
        self.assertIn("CONFIG_CONFIRMED", events)
        self.assertIn("SHUTDOWN", events)

    def test_sequence_gap_requests_exactly_one_stop(self):
        harness = self._harness()
        harness.send(armed_heartbeat(seq=0))
        self.assertEqual(harness.receive(), {"type": wp.ACK, "seq": 0})
        harness.send(armed_heartbeat(seq=5))
        messages = harness.collect()
        self.assertIn({"type": wp.ACK, "seq": 5}, messages)
        stops = [m for m in messages if m.get("type") == wp.STOP_REQUEST]
        self.assertEqual(len(stops), 1)
        self.assertIn("sequence gap", stops[0]["reason"])
        harness.send(armed_heartbeat(seq=6))
        followup = harness.collect()
        self.assertNotIn(wp.STOP_REQUEST, [m.get("type") for m in followup])
        harness.send({"type": wp.SHUTDOWN})
        harness.expect_exit(0)
        self.assertEqual(len(self._stop_reasons(harness)), 1)

    def test_run_fault_matrix_requests_stop_with_reason(self):
        cases = (
            ({"generation": 4}, "generation changed"),
            ({"owner_ok": False}, "lease lost"),
            ({"recorder_ok": False}, "recorder unhealthy"),
            ({"temp_ok": False}, "temperature outside"),
            ({"telemetry_age_s": 9.0}, "stale telemetry"),
            ({"whole_remaining_s": 50.0}, "whole-run deadline exceeded"),
            ({"whole_remaining_s": 3.6}, "whole-run budget moved backwards"),
        )
        for overrides, expected in cases:
            with self.subTest(overrides=overrides):
                harness = self._harness()
                harness.send(armed_heartbeat(seq=0))
                self.assertEqual(harness.receive(), {"type": wp.ACK, "seq": 0})
                harness.send(armed_heartbeat(seq=1, **overrides))
                messages = harness.collect()
                stops = [m for m in messages if m.get("type") == wp.STOP_REQUEST]
                self.assertEqual(len(stops), 1, messages)
                self.assertIn(expected, stops[0]["reason"])
                reasons = self._stop_reasons(harness)
                self.assertEqual(len(reasons), 1)
                self.assertIn(expected, reasons[0])
                harness.send({"type": wp.SHUTDOWN})
                harness.expect_exit(0)

    def test_step_budget_violations_are_enforced(self):
        first = self._harness()
        first.send(armed_heartbeat(seq=0, step_remaining_s=5.0))
        messages = first.collect()
        stops = [m for m in messages if m.get("type") == wp.STOP_REQUEST]
        self.assertEqual(len(stops), 1)
        self.assertIn("step deadline exceeds the approved maximum",
                      stops[0]["reason"])
        first.send({"type": wp.SHUTDOWN})
        first.expect_exit(0)

        backwards = self._harness()
        backwards.send(armed_heartbeat(seq=0))
        self.assertEqual(backwards.receive(), {"type": wp.ACK, "seq": 0})
        backwards.send(armed_heartbeat(seq=1, step_remaining_s=1.1))
        stops = [m for m in backwards.collect()
                 if m.get("type") == wp.STOP_REQUEST]
        self.assertEqual(len(stops), 1)
        self.assertIn("step budget moved backwards", stops[0]["reason"])
        backwards.send({"type": wp.SHUTDOWN})
        backwards.expect_exit(0)

        expired = self._harness()
        expired.send(armed_heartbeat(seq=0))
        self.assertEqual(expired.receive(), {"type": wp.ACK, "seq": 0})
        expired.send(armed_heartbeat(seq=1, step_remaining_s=-0.5))
        stops = [m for m in expired.collect()
                 if m.get("type") == wp.STOP_REQUEST]
        self.assertEqual(len(stops), 1)
        self.assertIn("step deadline exceeded", stops[0]["reason"])
        expired.send({"type": wp.SHUTDOWN})
        expired.expect_exit(0)

    def test_parent_loss_exits_three(self):
        harness = self._harness()
        harness.expect_exit(wp.EXIT_PARENT_LOST, timeout=10)
        self.assertIn("PARENT_LOST", evidence_events(read_jsonl(harness.evidence)))

    def test_unknown_message_exits_five(self):
        harness = self._harness()
        harness.send({"type": "PING"})
        harness.expect_exit(wp.EXIT_PROTOCOL_ERROR)
        self.assertIn("PROTOCOL_ERROR", evidence_events(read_jsonl(harness.evidence)))


class SupervisionHostTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.hosts: list[SupervisionHost] = []

    def _host(self, directory="wd") -> SupervisionHost:
        host = SupervisionHost(
            fast_limits(), evidence_dir=self.root / directory,
            chamber_id=CHAMBER, serial_number=SERIAL,
        )
        self.hosts.append(host)
        self.addCleanup(host.close)
        return host

    def _started(self, directory="wd") -> SupervisionHost:
        host = self._host(directory)
        host.start()
        self.assertTrue(wait_for(host.alive), host.error)
        return host

    def test_lifecycle_produces_evidence_and_clean_stop(self):
        host = self._started()
        timeline = read_jsonl(host.timeline_path)
        self.assertIn("HOST_START", evidence_events(timeline))
        self.assertIn("CHILD_READY", evidence_events(timeline))
        host.close()
        self.assertFalse(host.alive())
        child = read_jsonl(host.timeline_path.with_name("watchdog-child.jsonl"))
        events = evidence_events(child)
        self.assertIn("CONFIG_CONFIRMED", events)
        self.assertIn("SHUTDOWN", events)
        self.assertFalse(host.latch_path.exists())

    def test_restart_latch_blocks_start_without_spawning(self):
        host = self._host()
        host.latch_path.parent.mkdir(parents=True, exist_ok=True)
        host.latch_path.write_text(
            json.dumps({"reason": "review pending"}), encoding="utf-8")
        host.start()
        self.assertFalse(host.alive())
        self.assertTrue(host.latched)
        self.assertIn("watchdog restart latch", host.error)
        self.assertIn("LATCH_BLOCKED", evidence_events(read_jsonl(host.timeline_path)))
        self.assertFalse(host.timeline_path.with_name("watchdog-child.jsonl").exists())

    def test_child_death_latches_the_host(self):
        host = self._started()
        host._process.kill()
        self.assertTrue(wait_for(lambda: host.latched), host.error)
        self.assertFalse(host.alive())
        self.assertTrue(host.latch_path.exists())
        events = evidence_events(read_jsonl(host.timeline_path))
        self.assertIn("SUPERVISOR_LOST", events)
        self.assertIn("LATCH_SET", events)

    def test_failed_spawn_fails_closed_and_close_is_safe(self):
        from unittest import mock
        host = self._host()
        with mock.patch(
            "chamber_web.hil.supervision.subprocess.Popen",
            side_effect=OSError("boom"),
        ):
            host.start()
        self.assertFalse(host.alive())
        self.assertIn("failed to start", host.error)
        host.close()
        events = evidence_events(read_jsonl(host.timeline_path))
        self.assertIn("HOST_START_FAILED", events)

    def test_reset_script_clears_latch_and_allows_restart(self):
        host = self._host()
        host.set_latch("test latch")
        self.assertTrue(host.latch_path.exists())
        script = REPO_ROOT / "scripts" / "h02_watchdog_reset.py"
        refused = subprocess.run(
            [sys.executable, str(script), "--evidence-dir",
             str(host.latch_path.parent), "--reviewed-by", "reviewer"],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(refused.returncode, 2)
        self.assertTrue(host.latch_path.exists())
        cleared = subprocess.run(
            [sys.executable, str(script), "--evidence-dir",
             str(host.latch_path.parent), "--reviewed-by", "reviewer",
             "--confirm-clear"],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(cleared.returncode, 0, cleared.stderr)
        self.assertFalse(host.latch_path.exists())
        preserved = json.loads(
            host.latch_path.with_name("watchdog-latch-cleared.json")
            .read_text(encoding="utf-8"))
        self.assertEqual(preserved["reason"], "test latch")
        cleared_events = [record for record in read_jsonl(host.timeline_path)
                          if record.get("event") == "LATCH_CLEARED"]
        self.assertEqual(cleared_events[0]["reviewed_by"], "reviewer")
        fresh = self._float_host(host.latch_path.parent)
        fresh.start()
        self.assertTrue(wait_for(fresh.alive), fresh.error)

    def _float_host(self, directory: Path) -> SupervisionHost:
        host = SupervisionHost(
            fast_limits(), evidence_dir=directory,
            chamber_id=CHAMBER, serial_number=SERIAL,
        )
        self.hosts.append(host)
        self.addCleanup(host.close)
        return host

    class _Status:
        def __init__(self, *, state, quality=ReadingQuality.GOOD,
                     measured=25.0):
            self.operation_state = state
            self.quality = quality
            self.measured_temperature_c = measured
            self.sampled_at_utc = datetime.now(timezone.utc)

    class _Manager:
        def __init__(self, status):
            self.status_value = status

        def status(self, chamber_id):
            return self.status_value

    def _armed_run(self, host: SupervisionHost, *, state,
                   temp_ok=True, notified: list | None = None):
        notified = notified if notified is not None else []

        def provider():
            return {
                "terminal": False, "generation": 3, "step_index": 0,
                "step_remaining_s": 0.5, "whole_remaining_s": 4.0,
                "telemetry_age_s": 0.05, "owner_ok": True,
                "recorder_ok": True, "temp_ok": temp_ok,
            }

        run = host.arm_run(
            run_id="run-1", permit_sha256="a" * 64, generation=3,
            manager=self._Manager(self._Status(state=state)),
            state_provider=provider, fault_notify=notified.append,
        )
        return run, notified

    def test_armed_run_fault_routes_through_one_stop_and_verifies(self):
        host = self._started()
        run, notified = self._armed_run(host, state=OperationState.STOPPED,
                                        temp_ok=False)
        self.assertTrue(wait_for(lambda: notified), host.error)
        self.assertIn("temperature outside the approved envelope", notified[0])
        self.assertTrue(wait_for(
            lambda: "STOP_VERIFIED" in evidence_events(
                read_jsonl(host.timeline_path)), timeout=6.0), host.error)
        self.assertFalse(host.latched)
        self.assertTrue(host.alive())
        run.disarm()

    def test_unverified_stop_latches_the_host(self):
        host = self._started()
        run, notified = self._armed_run(host, state=OperationState.RUNNING,
                                        temp_ok=False)
        self.assertTrue(wait_for(lambda: notified, timeout=6.0), host.error)
        self.assertTrue(wait_for(lambda: host.latched, timeout=6.0), host.error)
        self.assertFalse(host.alive())
        self.assertTrue(host.latch_path.exists())
        events = evidence_events(read_jsonl(host.timeline_path))
        self.assertIn("STOP_UNVERIFIED", events)
        self.assertIn("LATCH_SET", events)
        run.disarm()

    def test_arm_matrix_refuses_unhealthy_or_duplicate_bindings(self):
        host = self._started()
        with self.assertRaises(AdmissionDenied):
            host.arm_run(
                run_id="r", permit_sha256="a" * 64, generation=-1,
                manager=self._Manager(self._Status(state=OperationState.STOPPED)),
                state_provider=lambda: {}, fault_notify=lambda reason: None,
            )
        with self.assertRaises(AdmissionDenied):
            host.arm_run(
                run_id="r", permit_sha256="a" * 64, generation=True,
                manager=self._Manager(self._Status(state=OperationState.STOPPED)),
                state_provider=lambda: {}, fault_notify=lambda reason: None,
            )
        run, _ = self._armed_run(host, state=OperationState.STOPPED)
        with self.assertRaises(AdmissionDenied):
            self._armed_run(host, state=OperationState.STOPPED)
        run.disarm()
        second, _ = self._armed_run(host, state=OperationState.STOPPED)
        second.disarm()

    def test_unhealthy_host_refuses_arming(self):
        host = self._host()
        host.latch_path.parent.mkdir(parents=True, exist_ok=True)
        host.latch_path.write_text(
            json.dumps({"reason": "review pending"}), encoding="utf-8")
        host.start()
        self.assertFalse(host.alive())
        with self.assertRaises(AdmissionDenied):
            self._armed_run(host, state=OperationState.STOPPED)


def profile_step(target="25"):
    return ProfileStep(
        1, True, Decimal(target), None, None, Decimal("1"),
        Decimal("0"), Decimal("0"), Decimal("20"), "test",
        "ON", "UNCHANGED", "UNCHANGED", (),
    )


class CaptureSink:
    def __init__(self):
        self.prepared = []
        self.events = []

    def prepare(self, snapshot):
        self.prepared.append(snapshot)

    def emit(self, event):
        self.events.append(event)


class PhysicalLikeFake(FakeBackend):
    simulation_only = False
    physical_authorized = True

    def __init__(self, chamber_id, **kwargs):
        super().__init__(chamber_id, **kwargs)
        self.commands = []
        self._identity = replace(self._identity, backend_id="votsch",
                                 serial_number=SERIAL, is_simulation=False)

    def start(self):
        self.commands.append("start")
        return super().start()


class SupervisedDispatchTests(unittest.TestCase):
    """Runner-level H02-C gates; mock physical backend, no watchdog process."""

    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.backend = PhysicalLikeFake(CHAMBER)
        self.manager = ChamberManager(
            [ChamberConfig(CHAMBER, "fake")],
            backend_factory=lambda config, **kwargs: self.backend,
            lease_directory=self.root / "ownership",
        )
        self.addCleanup(self.manager.disconnect, CHAMBER)
        self.manager.connect(CHAMBER)
        self.store = ProfileStore(self.root / "profiles.sqlite")
        self.sink = CaptureSink()

    def _runner(self, supervised) -> ProfileRunner:
        runner = ProfileRunner(
            self.manager, self.store,
            authorize=lambda action, chamber: "test-operator",
            sink=self.sink, clock=VirtualClock(), supervised=supervised,
        )
        self.addCleanup(runner.close)
        return runner

    def _profile(self):
        return self.store.create_profile(
            CHAMBER, ParsedProfile((profile_step(),), name="watchdog")).profile_id

    def _drain(self, runner):
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            if runner.advance() in TERMINAL:
                break
            time.sleep(0.005)
        return runner.state

    def test_dead_supervisor_blocks_dispatch(self):
        context = SupervisedRun(
            "b" * 64, "test-operator", lambda: None,
            supervisor_alive=lambda: False,
        )
        runner = self._runner(context)
        runner.start(CHAMBER, self._profile(), revision=1)
        self.assertEqual(self._drain(runner), RunState.UNKNOWN)
        self.assertEqual(self.backend.commands, [])
        self.assertIn("Supervisor heartbeat lost", runner.reason)
        self.assertTrue(self.manager.health(CHAMBER).stop_latched)

    def test_notified_fault_stops_before_dispatch_without_replay(self):
        context = SupervisedRun(
            "b" * 64, "test-operator", lambda: None,
            supervisor_alive=lambda: True,
        )
        runner = self._runner(context)
        runner.start(CHAMBER, self._profile(), revision=1)
        runner.notify_supervisor_fault("watchdog alarm")
        self.assertEqual(self._drain(runner), RunState.UNKNOWN)
        self.assertEqual(self.backend.commands, [])
        self.assertIn("Watchdog fault: watchdog alarm", runner.reason)


class RealHostIntegrationTests(unittest.TestCase):
    """Runner supervised by the real watchdog process; mock backend only."""

    def test_child_fault_stops_the_runner_before_dispatch(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        backend = PhysicalLikeFake(CHAMBER)
        manager = ChamberManager(
            [ChamberConfig(CHAMBER, "fake")],
            backend_factory=lambda config, **kwargs: backend,
            lease_directory=root / "ownership",
        )
        self.addCleanup(manager.disconnect, CHAMBER)
        manager.connect(CHAMBER)
        store = ProfileStore(root / "profiles.sqlite")
        profile_id = store.create_profile(
            CHAMBER, ParsedProfile((profile_step(),), name="watchdog")).profile_id
        host = SupervisionHost(
            fast_limits(), evidence_dir=root / "watchdog",
            chamber_id=CHAMBER, serial_number=SERIAL,
        )
        self.addCleanup(host.close)
        host.start()
        self.assertTrue(wait_for(host.alive), host.error)
        context = SupervisedRun(
            "c" * 64, "test-operator", lambda: None,
            supervisor_alive=host.alive,
        )
        runner = ProfileRunner(
            manager, store,
            authorize=lambda action, chamber: "test-operator",
            sink=CaptureSink(), clock=VirtualClock(), supervised=context,
        )
        self.addCleanup(runner.close)
        snapshot = runner.start(CHAMBER, profile_id, revision=1)
        health = manager.health(CHAMBER)

        def state_provider():
            return {
                **runner.supervision_state(),
                "generation": health.generation,
                "telemetry_age_s": 0.05,
                "owner_ok": True, "recorder_ok": True, "temp_ok": False,
            }

        host.arm_run(
            run_id=snapshot.run_id, permit_sha256="d" * 64,
            generation=snapshot.controller_generation,
            manager=manager, state_provider=state_provider,
            fault_notify=runner.notify_supervisor_fault,
        )
        self.assertTrue(wait_for(
            lambda: runner.state is not None and
            "Watchdog fault:" in (runner.reason or "")), host.error)
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline and runner.state not in TERMINAL:
            runner.advance()
            time.sleep(0.005)
        self.assertEqual(runner.state, RunState.UNKNOWN)
        self.assertIn("temperature outside the approved envelope", runner.reason)
        self.assertEqual(backend.commands, [])
        self.assertTrue(manager.health(CHAMBER).stop_latched)
        events = evidence_events(read_jsonl(host.timeline_path))
        self.assertIn("STOP_REQUEST", events)
        self.assertIn("STOP_VERIFIED", events)
        self.assertFalse(host.latched)


class StubSupervisionHost:
    def __init__(self, *, fail_arm=False):
        self.alive_flag = False
        self.fail_arm = fail_arm
        self.arms: list[dict] = []

    def alive(self) -> bool:
        return self.alive_flag

    def arm_run(self, **kwargs):
        if self.fail_arm:
            raise RuntimeError("arm failed")
        self.arms.append(kwargs)


class SignedPermitFixture:
    def __init__(self, store, *, profile=None, operator="test_admin"):
        self.store = store
        self.private = Ed25519PrivateKey.generate()
        self.public = self.private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        header = store.create_profile(
            CHAMBER, profile or ParsedProfile((profile_step(),), name="supervised"))
        self.profile_id = header.profile_id
        self.revision_sha = store.get_revision(
            CHAMBER, self.profile_id, revision=1).sha256
        now = datetime.now(timezone.utc)
        self.permit = {
            "schema_version": 1,
            "scope": "H02_SUPERVISED_PHYSICAL_PROFILE",
            "site_method": "SITE-H02-01", "approval_reference": "SIGNED-SITE-H02-01",
            "chamber_id": CHAMBER, "serial_number": SERIAL,
            "profile_id": self.profile_id,
            "profile_revision_sha256": self.revision_sha,
            "gui_commit": GUI_COMMIT, "driver_commit": DRIVER_COMMIT,
            "operator": operator, "witness": WITNESS,
            "specimen_restrictions": "Empty chamber, witness present",
            "temperature_min_c": 22.0, "temperature_max_c": 27.0,
            "valid_from_utc": (now - timedelta(minutes=2)).isoformat(),
            "valid_until_utc": (now + timedelta(hours=1)).isoformat(),
            "watchdog": permit_limits_dict(),
        }

    def load(self, directory: Path):
        payload = json.dumps(self.permit, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode("utf-8")
        path = directory / "h02-permit.json"
        path.write_text(json.dumps({
            "permit": self.permit,
            "signature_base64": base64.b64encode(
                self.private.sign(payload)).decode("ascii"),
        }), encoding="utf-8")
        loaded = load_supervised_permit({
            ENV_PERMIT_FILE: str(path),
            ENV_TRUSTED_KEY: base64.b64encode(self.public).decode("ascii"),
        })
        assert loaded is not None
        return loaded


@unittest.skipUnless(Ed25519PrivateKey is not None,
                     "cryptography is unavailable; fail closed")
class SupervisedServiceWatchdogTests(unittest.TestCase):
    """Service-visible H02-C gates with a stub supervisor (mock backend)."""

    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.security = SecurityStore(self.root / "auth")
        self.security.bootstrap_admin("test_admin", "StrongAdminPassword#1")
        self.operator = self.security.login("test_admin", "StrongAdminPassword#1")
        self.backend = PhysicalLikeFake(CHAMBER)
        self.manager = ChamberManager(
            [ChamberConfig(CHAMBER, "fake")],
            backend_factory=lambda config, **kwargs: self.backend,
            lease_directory=self.root / "ownership",
        )
        self.addCleanup(self.manager.disconnect, CHAMBER)
        self.manager.connect(CHAMBER)
        self.store = ProfileStore(self.root / "profiles.sqlite")
        self.fixture = SignedPermitFixture(self.store)
        self.permit = self.fixture.load(self.root)

    def _runtime(self, *, supervision, supervisor_alive=lambda: True):
        return SupervisedProfileRuntime(
            permit=self.permit, witness=WITNESS, hil_acknowledged=True,
            supervisor_alive=supervisor_alive, gui_commit=GUI_COMMIT,
            driver_commit=DRIVER_COMMIT, supervision=supervision,
        )

    def _service(self, runtime):
        service = ProfileExecutionService(
            self.manager, self.store, self.security, CHAMBER,
            simulation=False, supervised=runtime,
            parameters=RunParameters(poll_s=0.05, max_gap_s=1, max_age_s=1),
        )

        def close_runner():
            runner = service.runner
            if runner is not None and runner.state in TERMINAL:
                runner.close()
        self.addCleanup(close_runner)
        return service

    def _drain(self, runner):
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            if runner.advance() in TERMINAL:
                break
            time.sleep(0.005)
        return runner.state

    def test_missing_supervision_host_keeps_physical_starts_disabled(self):
        service = self._service(self._runtime(supervision=None))
        view = service.view(self.operator.session)
        self.assertFalse(view.can_start)
        with self.assertRaises(AdmissionDenied) as caught:
            service.start(self.operator.session, self.operator.csrf,
                          self.fixture.profile_id, 1)
        self.assertIn("independent supervisor is not configured",
                      str(caught.exception))
        self.assertIsNone(service.runner)
        self.assertEqual(self.backend.commands, [])

    def test_view_gates_on_supervisor_liveness_and_arms_after_start(self):
        stub = StubSupervisionHost()
        service = self._service(self._runtime(supervision=stub))
        self.assertFalse(service.view(self.operator.session).can_start)
        stub.alive_flag = True
        self.assertTrue(service.view(self.operator.session).can_start)
        snapshot = service.start(self.operator.session, self.operator.csrf,
                                 self.fixture.profile_id, 1)
        self.assertEqual(len(stub.arms), 1)
        arm = stub.arms[0]
        self.assertEqual(arm["run_id"], snapshot.run_id)
        self.assertEqual(arm["generation"], snapshot.controller_generation)
        self.assertEqual(arm["permit_sha256"], self.permit.sha256)
        self.assertEqual(arm["fault_notify"].__self__, service.runner)
        state = arm["state_provider"]()
        for key in ("step_index", "step_remaining_s", "whole_remaining_s",
                    "generation", "telemetry_age_s", "owner_ok", "recorder_ok",
                    "temp_ok"):
            self.assertIn(key, state)
        self.assertEqual(self._drain(service.runner), RunState.COMPLETED)
        self.assertEqual(self.backend.commands, ["start"])

    def test_failed_arming_aborts_the_started_run(self):
        stub = StubSupervisionHost(fail_arm=True)
        stub.alive_flag = True
        service = self._service(self._runtime(supervision=stub))
        with self.assertRaises(RuntimeError):
            service.start(self.operator.session, self.operator.csrf,
                          self.fixture.profile_id, 1)
        self.assertIsNone(service.runner)
        self.assertEqual(self.backend.commands, [])
        self.assertTrue(self.manager.health(CHAMBER).stop_latched)


if __name__ == "__main__":
    unittest.main()
