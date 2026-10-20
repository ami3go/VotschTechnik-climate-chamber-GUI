"""H02-C application-side supervision host for the independent watchdog.

The host owns one watchdog OS process per application launch (physical HIL
configuration only). It sends heartbeats derived from live G04/G07 state,
consumes the child's ACK/STOP_REQUEST messages over an authenticated loopback
connection and, on any watchdog fault:

1. notifies the G06 runner (``notify_supervisor_fault``), which commits the
   durable STOP intent and submits exactly one approved G04 STOP;
2. verifies a fresh GOOD STOPPED readback within ``stop_verification_timeout_s``;
3. keeps diagnostics in a JSONL timeline and, if STOP cannot be verified,
   writes a restart latch that refuses all further physical starts until an
   operator review clears it (``scripts/h02_watchdog_reset.py``).

A supervisor fault during an armed run disarms run deadlines but the child
process stays alive for ACK bookkeeping only after a verified STOP; an
unverified STOP or supervisor loss latches the host fail-closed.
"""
from __future__ import annotations

import base64
import json
from multiprocessing.connection import (
    Connection, answer_challenge, deliver_challenge,
)
from dataclasses import asdict
from datetime import datetime, timezone
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from chamber_web.domain.chamber import OperationState, ReadingQuality
from chamber_web.hil import watchdog_protocol as wp
from chamber_web.hil.profile_admission import AdmissionDenied, H02WatchdogLimits
from chamber_web.hil.watchdog_process import AUTHKEY_ENV


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _readable_age(sampled_at_utc) -> float | None:
    if sampled_at_utc is None or getattr(sampled_at_utc, "tzinfo", None) is None:
        return None
    return (datetime.now(timezone.utc) - sampled_at_utc).total_seconds()


class SupervisionHost:
    """One independent watchdog process; fail-closed unless fully healthy."""

    def __init__(self, limits: H02WatchdogLimits, *, evidence_dir: Path,
                 chamber_id: str, serial_number: str):
        if not isinstance(chamber_id, str) or not chamber_id.strip():
            raise ValueError("Supervision requires an authoritative chamber id")
        if not isinstance(serial_number, str) or not serial_number.strip():
            raise ValueError("Supervision requires the authorized device serial")
        self._limits = limits
        self._limits_dict = asdict(limits)
        self._evidence_dir = Path(evidence_dir)
        self._timeline_path = self._evidence_dir / "watchdog-timeline.jsonl"
        self._latch_path = self._evidence_dir / "watchdog-latch.json"
        self._chamber_id = chamber_id
        self._serial_number = serial_number
        interval = max(0.05, min(
            limits.process_heartbeat_s, limits.supervisor_heartbeat_s,
            limits.max_telemetry_gap_s, limits.readback_deadline_s,
        ) / 3)
        self._interval = interval
        self._lock = threading.Lock()
        self._authkey: bytes | None = None
        self._server_socket: socket.socket | None = None
        self._connection = None
        self._process = None
        self._pump: threading.Thread | None = None
        self._shutdown = threading.Event()
        self._run: RunSupervision | None = None
        self._started = False
        self._connected = False
        self._failed = False
        self._latched = False
        self._seq = 0
        self._last_ack = 0.0
        self._error = ""

    @property
    def error(self) -> str:
        with self._lock:
            return self._error

    @property
    def latched(self) -> bool:
        return self._latched

    @property
    def latch_path(self) -> Path:
        return self._latch_path

    @property
    def timeline_path(self) -> Path:
        return self._timeline_path

    def evidence(self, event: str, **fields) -> None:
        record = {"at_utc": _utc_now(), "monotonic": time.monotonic(),
                  "event": event, **fields}
        try:
            self._evidence_dir.mkdir(parents=True, exist_ok=True)
            with self._timeline_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, sort_keys=True) + "\n")
        except OSError:
            pass

    def set_latch(self, reason: str) -> None:
        self._latched = True
        self._error = reason
        try:
            self._evidence_dir.mkdir(parents=True, exist_ok=True)
            self._latch_path.write_text(json.dumps(
                {"reason": reason, "at_utc": _utc_now()}, sort_keys=True),
                encoding="utf-8")
        except OSError as exc:
            self._error = reason + " (latch write failed: " + type(exc).__name__ + ")"
        self.evidence("LATCH_SET", reason=reason)

    def start(self) -> None:
        """Spawn the watchdog process unless a restart latch is present."""
        with self._lock:
            if self._started:
                return
            self._started = True
        if self._latch_path.exists():
            try:
                data = json.loads(self._latch_path.read_text(encoding="utf-8"))
            except Exception:
                data = {"reason": "unreadable latch"}
            self._latched = True
            self._error = "watchdog restart latch: " + str(data.get("reason", ""))
            self.evidence("LATCH_BLOCKED", reason=self._error)
            return
        try:
            self._evidence_dir.mkdir(parents=True, exist_ok=True)
            authkey = secrets.token_bytes(32)
            self._authkey = authkey
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            server.settimeout(0.2)
            self._server_socket = server
            port = server.getsockname()[1]
            child_log = str(self._evidence_dir / "watchdog-child.jsonl")
            config = {"limits": self._limits_dict, "chamber_id": self._chamber_id,
                      "serial_number": self._serial_number}
            environment = dict(os.environ)
            environment[AUTHKEY_ENV] = base64.b64encode(authkey).decode("ascii")
            self._process = subprocess.Popen(
                [sys.executable, "-m", "chamber_web.hil.watchdog_process",
                 "--port", str(port), "--evidence", child_log],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, env=environment,
                start_new_session=os.name != "nt",
                creationflags=(
                    getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                    if os.name == "nt" else 0
                ),
            )
            self._process.stdin.write(json.dumps(config).encode("utf-8"))
            self._process.stdin.close()
        except Exception as exc:
            self._failed = True
            self._error = "watchdog process failed to start: " + type(exc).__name__
            self.evidence("HOST_START_FAILED", error=self._error)
            return
        self.evidence("HOST_START", pid=self._process.pid,
                      chamber_id=self._chamber_id, serial_number=self._serial_number)
        self._pump = threading.Thread(
            target=self._pump_loop, name="h02-watchdog-pump", daemon=True,
        )
        self._pump.start()

    def alive(self) -> bool:
        with self._lock:
            if (not self._started or self._failed or self._latched or
                    not self._connected or self._shutdown.is_set()):
                return False
            if self._process is None or self._process.poll() is not None:
                return False
            return (time.monotonic() - self._last_ack) <= (
                self._limits.supervisor_heartbeat_s)

    def arm_run(self, *, run_id: str, permit_sha256: str, generation: int,
                manager, state_provider: Callable[[], Mapping[str, Any]],
                fault_notify: Callable[[str], None]) -> "RunSupervision":
        """Bind supervision to one exact run; refuses when not fully healthy."""
        if not self.alive():
            raise AdmissionDenied(
                "H02-C independent supervisor unavailable: " +
                (self.error or "no healthy watchdog heartbeat"))
        if type(generation) is not int or generation < 0:
            raise AdmissionDenied("Supervision requires a controller generation")
        with self._lock:
            if self._run is not None and not self._run.expired():
                raise AdmissionDenied("Watchdog supervision is already armed")
            run = RunSupervision(
                host=self, run_id=run_id, permit_sha256=permit_sha256,
                generation=generation, manager=manager,
                state_provider=state_provider, fault_notify=fault_notify,
            )
            self._run = run
        self.evidence("RUN_ARM", run_id=run_id, permit_sha256=permit_sha256,
                      generation=generation)
        return run

    def _fault_async(self, run: "RunSupervision", reason: str) -> None:
        """Fault off the pump thread so parent heartbeats keep flowing.

        STOP verification may take up to ``stop_verification_timeout_s``; the
        child's parent-heartbeat deadline must not expire meanwhile, or a
        successfully verified STOP would still latch the host.
        """
        threading.Thread(
            target=run.fault, args=(reason,), name="h02-watchdog-fault",
            daemon=True,
        ).start()

    def _current_run(self) -> "RunSupervision | None":
        expired = None
        with self._lock:
            run = self._run
            if run is not None and run.expired():
                self._run = None
                expired = run
                run = None
        if expired is not None:
            expired.disarm()
        return run

    def _fail(self, reason: str) -> None:
        with self._lock:
            if self._failed:
                return
            self._failed = True
            self._error = reason
        self.evidence("SUPERVISOR_LOST", reason=reason)
        run = self._current_run()
        if run is not None:
            run.fault(reason)
        self.set_latch(reason)
        self._terminate_child()

    def _terminate_child(self) -> None:
        process, connection = self._process, self._connection
        try:
            if connection is not None:
                connection.close()
        except OSError:
            pass
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=self._limits.cleanup_timeout_s)
            except subprocess.TimeoutExpired:
                process.kill()
                try:
                    process.wait(timeout=self._limits.cleanup_timeout_s)
                except subprocess.TimeoutExpired:
                    pass
        if self._server_socket is not None:
            try:
                self._server_socket.close()
            except OSError:
                pass

    def _accept_authenticated(self) -> Connection:
        """One authenticated accept step over the bounded loopback socket."""
        server, authkey = self._server_socket, self._authkey
        assert server is not None and authkey is not None
        raw, _ = server.accept()
        raw.settimeout(None)  # detached sockets must block for Connection I/O
        connection = Connection(raw.detach())
        deliver_challenge(connection, authkey)
        answer_challenge(connection, authkey)
        return connection

    def _pump_loop(self) -> None:
        startup_deadline = time.monotonic() + max(
            3.0, self._limits.process_heartbeat_s + 2.0,
        )
        connection = None
        while connection is None:
            if self._shutdown.is_set():
                return
            if (self._process is None or self._process.poll() is not None or
                    time.monotonic() > startup_deadline):
                self._fail("watchdog child never connected")
                return
            try:
                connection = self._accept_authenticated()
            except socket.timeout:
                continue
            except Exception as exc:
                self._fail("watchdog child never connected: " + type(exc).__name__)
                return
        try:
            if not connection.poll(max(1.0, self._limits.cleanup_timeout_s)):
                raise wp.WatchdogProtocolError("watchdog handshake timed out")
            ready = connection.recv()
            if (not isinstance(ready, dict) or ready.get("type") != wp.READY or
                    ready.get("protocol") != wp.PROTOCOL_VERSION):
                raise wp.WatchdogProtocolError("watchdog handshake failed")
            connection.send({
                "type": wp.CONFIG, "protocol": wp.PROTOCOL_VERSION,
                **self._limits_dict,
                "chamber_id": self._chamber_id,
                "serial_number": self._serial_number,
            })
            with self._lock:
                self._connection = connection
                self._connected = True
                self._last_ack = time.monotonic()
            self.evidence("CHILD_READY", child_pid=ready.get("pid"))
            self._heartbeat_loop(connection)
        except wp.WatchdogProtocolError as exc:
            self._fail("watchdog protocol error: " + str(exc))
        except (OSError, EOFError):
            if not self._shutdown.is_set():
                self._fail("watchdog connection lost")

    def _heartbeat_loop(self, connection) -> None:
        while not self._shutdown.is_set():
            run = self._current_run()
            message = {
                "type": wp.HEARTBEAT, "seq": self._seq,
                "state": wp.STATE_ARMED if run is not None else wp.STATE_IDLE,
                "run_id": None,
                "generation": None, "expected_generation": None,
                "step_index": None, "step_remaining_s": None,
                "whole_remaining_s": None, "telemetry_age_s": None,
                "owner_ok": None, "recorder_ok": None, "temp_ok": None,
                "stop_verified": None,
            }
            if run is not None:
                try:
                    fields = run.heartbeat_fields()
                    if fields.pop("stopping", False):
                        message["state"] = wp.STATE_STOPPING
                    message.update(fields)
                    message["run_id"] = run.run_id
                    message["expected_generation"] = run.generation
                except Exception as exc:
                    self.evidence("STATE_PROVIDER_FAILED",
                                  error=type(exc).__name__)
                    self._fault_async(run, "supervision state unavailable")
                    with self._lock:
                        if self._run is run:
                            self._run = None
                    run.done = True
                    run = None
            try:
                connection.send(message)
            except (OSError, EOFError):
                if not self._shutdown.is_set():
                    self._fail("watchdog connection lost while heartbeating")
                return
            self._seq += 1
            deadline = time.monotonic() + self._interval
            while time.monotonic() < deadline:
                try:
                    if connection.poll(min(0.05, self._interval)):
                        pending = connection.recv()
                        if not isinstance(pending, dict):
                            raise wp.WatchdogProtocolError("non-dict message")
                        self._handle(pending)
                except (OSError, EOFError):
                    if not self._shutdown.is_set():
                        self._fail("watchdog connection lost")
                    return
            if (time.monotonic() - self._last_ack) > self._limits.supervisor_heartbeat_s:
                self._fail("watchdog heartbeat lost")
                return

    def _handle(self, message: dict) -> None:
        kind = message.get("type")
        if kind == wp.ACK:
            with self._lock:
                self._last_ack = time.monotonic()
            return
        if kind == wp.STOP_REQUEST:
            reason = str(message.get("reason", "watchdog fault"))
            run = self._current_run()
            if run is not None:
                self._fault_async(run, reason)
            else:
                self._fail("idle supervisor fault: " + reason)
            return
        raise wp.WatchdogProtocolError("unexpected message: " + str(kind))

    def close(self) -> None:
        self._shutdown.set()
        connection = self._connection
        if connection is not None:
            try:
                connection.send({"type": wp.SHUTDOWN})
            except (OSError, EOFError):
                pass
        process = self._process
        if process is not None and process.poll() is None:
            try:
                process.wait(timeout=self._limits.cleanup_timeout_s)
            except subprocess.TimeoutExpired:
                pass
        self._terminate_child()
        if self._pump is not None:
            self._pump.join(timeout=self._limits.cleanup_timeout_s)
        self.evidence("HOST_STOP")


class RunSupervision:
    """Per-run supervision handle; exactly one fault and one STOP request."""

    def __init__(self, *, host: SupervisionHost, run_id: str, permit_sha256: str,
                 generation: int, manager, state_provider, fault_notify):
        self._host = host
        self._run_id = run_id
        self._permit_sha256 = permit_sha256
        self.generation = generation
        self._manager = manager
        self._state_provider = state_provider
        self._fault_notify = fault_notify
        self._lock = threading.Lock()
        self._faulted = False
        self.done = False

    @property
    def run_id(self) -> str:
        return self._run_id

    def heartbeat_fields(self) -> dict:
        fields = dict(self._state_provider())
        fields.pop("terminal", None)
        return fields

    def expired(self) -> bool:
        if self.done:
            return True
        try:
            return bool(self._state_provider().get("terminal"))
        except Exception:
            return False

    def fault(self, reason: str) -> None:
        with self._lock:
            if self._faulted:
                return
            self._faulted = True
        self._host.evidence("STOP_REQUEST", run_id=self._run_id, reason=reason)
        try:
            self._fault_notify(reason)
        except Exception as exc:
            self._host.evidence("FAULT_NOTIFY_FAILED", run_id=self._run_id,
                                error=type(exc).__name__)
        self._verify_stop(reason)

    def _verify_stop(self, reason: str) -> None:
        deadline = time.monotonic() + self._host._limits.stop_verification_timeout_s
        while time.monotonic() <= deadline:
            try:
                status = self._manager.status(self._host._chamber_id)
                age = _readable_age(getattr(status, "sampled_at_utc", None))
                fresh = age is None or age <= self._host._limits.readback_deadline_s
                if (fresh and status.quality is ReadingQuality.GOOD and
                        status.operation_state is OperationState.STOPPED and
                        getattr(status, "measured_temperature_c", None) is not None):
                    self._host.evidence("STOP_VERIFIED", run_id=self._run_id,
                                        reason=reason)
                    return
            except Exception:
                pass
            time.sleep(0.05)
        self._host.evidence("STOP_UNVERIFIED", run_id=self._run_id, reason=reason)
        self._host.set_latch("STOP unverified after watchdog fault: " + reason)

    def disarm(self) -> None:
        with self._lock:
            if self.done:
                return
            self.done = True
        self._host.evidence("RUN_DISARM", run_id=self._run_id)
