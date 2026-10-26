"""Vendor-neutral, single-device server-side controller (mock-only G04-A).

All backend calls execute on one daemon worker; commands are not retried.
STOP latches/fences synchronously and jumps ahead of queued control work.
A hung synchronous adapter CANNOT be preempted: an expired deadline means
UNKNOWN, not a physical guarantee, and its process lease remains held.
"""
from __future__ import annotations

import itertools
import math
import queue
import threading
import uuid
from concurrent.futures import Future, TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, TypeVar

from chamber_web.domain.chamber import (
    ChamberBackend, ChamberCapabilities, ChamberConnectionError, ChamberError,
    ChamberIdentity, ChamberProtocolError, ChamberSafetyError, ChamberTimeoutError,
    ChamberSnapshot, OperationState, ReadingQuality, finite_temperature,
    validate_chamber_id,
)
from chamber_web.domain.config import ChamberConfig
from chamber_web.services.ownership import DeviceLease

T = TypeVar("T")


@dataclass(frozen=True)
class ControllerHealth:
    chamber_id: str
    state: str
    generation: int
    connected: bool
    stop_latched: bool
    reason: str | None


@dataclass
class _Work:
    name: str
    action: Callable
    future: Future
    generation: int
    mutation: bool = False
    owner_generation: int = 0


class ChamberController:
    """One controller, one worker, one process-exclusive lease, one backend.

    Server-side callers must supply the bound chamber ID. Operator ownership
    tokens provide conflict protection, not authentication (G08-min pending).
    """

    def __init__(
        self, config: ChamberConfig, backend: ChamberBackend, *,
        lease_directory: Path | None = None,
        io_timeout_s: float = 2.0, max_sample_age_s: float = 5.0,
    ):
        if not 0 < io_timeout_s <= 60 or not math.isfinite(io_timeout_s):
            raise ValueError("I/O timeout must be finite, >0 and <=60 s")
        if not 0 < max_sample_age_s <= 60 or not math.isfinite(max_sample_age_s):
            raise ValueError("Readback age must be finite, >0 and <=60 s")
        self.chamber_id = config.chamber_id
        self._backend = backend
        self._lease = DeviceLease(config.chamber_id, lease_directory)
        self._timeout = io_timeout_s
        self._max_age = max_sample_age_s
        self._state_lock = threading.RLock()
        self._queue: queue.PriorityQueue = queue.PriorityQueue()
        self._sequence = itertools.count()
        self._thread: threading.Thread | None = None
        self._poll_thread: threading.Thread | None = None
        self._poll_stop = threading.Event()
        self._generation = 0
        self._connected = False
        self._closed = False
        self._disconnecting = False
        self._stop_latched = True
        self._state = "DISCONNECTED"
        self._reason: str | None = None
        self._identity: ChamberIdentity | None = None
        self._capabilities: ChamberCapabilities | None = None
        self._last_snapshot: ChamberSnapshot | None = None
        self._operator_token: str | None = None
        self._operator_name: str | None = None
        self._operator_generation = 0

    def _check_id(self, chamber_id: str) -> None:
        validate_chamber_id(chamber_id)
        if chamber_id != self.chamber_id:
            raise ChamberSafetyError("Wrong/stale chamber_id: operation refused")

    @property
    def health(self) -> ControllerHealth:
        with self._state_lock:
            return ControllerHealth(
                self.chamber_id, self._state, self._generation,
                self._connected, self._stop_latched, self._reason,
            )

    @property
    def capabilities(self) -> ChamberCapabilities | None:
        with self._state_lock:
            return self._capabilities

    def claim_operator(self, chamber_id: str, owner: str) -> str:
        self._check_id(chamber_id)
        if not isinstance(owner, str) or not 1 <= len(owner.strip()) <= 128:
            raise ChamberSafetyError("Operator identity is required")
        with self._state_lock:
            if self._operator_token is not None:
                raise ChamberSafetyError("Another operator owns device commands")
            self._operator_token = uuid.uuid4().hex
            self._operator_generation += 1
            self._operator_name = owner.strip()
            return self._operator_token

    def release_operator(self, chamber_id: str, token: str) -> None:
        self._check_id(chamber_id)
        with self._state_lock:
            if not self._operator_token or token != self._operator_token:
                raise ChamberSafetyError("Operator lease token mismatch")
            self._operator_token = None
            self._operator_generation += 1
            self._operator_name = None

    def _check_operator(self, token: str | None) -> None:
        # Until G08-min, the no-token path is for trusted server code only.
        # G08-min MUST require authenticated identity at all external entrypoints.
        if ((token is None and self._operator_token is not None) or
                (token is not None and token != self._operator_token)):
            raise ChamberSafetyError("Operator lease owned by another caller")

    def _physical_authorized(self) -> bool:
        return (getattr(self._backend, "simulation_only", False) is not True and
                getattr(self._backend, "physical_authorized", False) is True)

    def connect(self, chamber_id: str) -> None:
        self._check_id(chamber_id)
        with self._state_lock:
            # Pre-connect marker is adapter-supplied, fail-closed, vendor-neutral:
            # a mock, or a backend carrying an explicit supervised HIL authorization.
            if not (getattr(self._backend, "simulation_only", False) is True or
                    self._physical_authorized()):
                raise ChamberSafetyError("Physical hardware I/O DISABLED without HIL authorization")
            if self._connected:
                return
            if self._closed or self._thread is not None:
                raise ChamberSafetyError("Controller cannot reconnect after failed/closed startup")
            self._lease.acquire()  # cross-process acquisition BEFORE any adapter I/O
            self._generation = self._lease.generation
            self._stop_latched = self._lease.needs_reconciliation
            self._state = "UNKNOWN" if self._stop_latched else "DISCONNECTED"
            self._thread = threading.Thread(
                target=self._worker, name="chamber-io-" + self.chamber_id, daemon=True,
            )
            self._thread.start()
        def initialize():
            self._backend.connect()
            identity = self._backend.identify()
            if identity.chamber_id != self.chamber_id or not (
                    identity.is_simulation or
                    (self._physical_authorized() and identity.serial_number)):
                raise ChamberSafetyError("Device identity mismatch / live hardware DISABLED")
            caps = self._backend.capabilities()
            try:
                snapshot = self._backend.read_status()
                if snapshot.operation_state is not OperationState.FAULT:
                    self._require_readback(snapshot, identity)
                elif snapshot.identity != identity:
                    raise ChamberSafetyError("Readback device identity mismatch")
            except Exception:
                # A connected mock with stale/failed telemetry is still
                # available for STOP but NEVER ready for ordinary writes.
                snapshot = None
            return identity, caps, snapshot
        identity, caps, snapshot = self._submit(
            "connect", initialize, priority=0,
        )
        with self._state_lock:
            self._identity, self._capabilities = identity, caps
            self._last_snapshot = snapshot
            self._connected = True
            if snapshot is None:
                self._trip("Initial telemetry unavailable")
            elif snapshot.operation_state is OperationState.FAULT:
                self._trip("Backend fault at connection", fault=True)
            elif snapshot.operation_state is not OperationState.STOPPED:
                self._trip("Chamber not verified stopped at connection")
            elif not self._stop_latched:
                self._state = "VERIFIED_STOPPED"

    def _worker(self) -> None:
        while True:
            _, _, work = self._queue.get()
            if work is None:
                return
            with self._state_lock:
                if (work.name not in ("stop", "disconnect") and
                    work.generation != self._generation) or (
                    work.mutation and (
                        self._stop_latched or
                        work.owner_generation != self._operator_generation
                    )
                ):
                    work.future.set_exception(
                        ChamberSafetyError("Queued command fenced by STOP/FAULT/ownership")
                    )
                    continue
                try:
                    self._lease.verify(
                        self._generation if work.name in ("stop", "disconnect")
                        else work.generation
                    )
                except Exception as exc:
                    work.future.set_exception(exc)
                    self._trip("Lease/generation verification failed", fault=True)
                    continue
            try:
                result = work.action()
            except Exception as exc:
                with self._state_lock:
                    self._trip("Backend " + work.name + " failed: " + type(exc).__name__)
                if isinstance(exc, ChamberError):
                    normalized = exc
                elif isinstance(exc, (ConnectionError, OSError)):
                    normalized = ChamberConnectionError(
                        "Backend " + work.name + " connection failed"
                    )
                elif isinstance(exc, TimeoutError):
                    normalized = ChamberTimeoutError(
                        "Backend " + work.name + " timed out"
                    )
                else:
                    normalized = ChamberProtocolError(
                        "Backend " + work.name + " failed"
                    )
                work.future.set_exception(normalized)
            else:
                work.future.set_result(result)

    def _submit(self, name: str, action: Callable[[], T], *, priority: int = 10,
                mutation: bool = False, timeout: float | None = None,
                operator_token: str | None = None) -> T:
        with self._state_lock:
            if self._closed or self._thread is None:
                raise ChamberSafetyError("Controller not active")
            generation = self._generation
            if mutation:
                self._check_operator(operator_token)
                if not self._connected or self._stop_latched:
                    raise ChamberSafetyError("Operation blocked: disconnected or STOP-latched")
            if name not in ("stop", "disconnect") and self._queue.qsize() >= 32:
                raise ChamberSafetyError("Device I/O queue full")
            request = _Work(
                name, action, Future(), generation, mutation,
                owner_generation=self._operator_generation,
            )
            self._queue.put((priority, next(self._sequence), request))
        try:
            return request.future.result(timeout=self._timeout if timeout is None else timeout)
        except FutureTimeout as exc:
            with self._state_lock:
                self._trip("Backend " + name + " exceeded deadline; effect unknown")
            raise ChamberTimeoutError("I/O timeout; device state UNKNOWN") from exc

    def _trip(self, reason: str, *, fault: bool = False) -> None:
        # Must hold state lock; fences queued old-generation actions.
        self._stop_latched = True
        self._reason = reason
        self._state = "FAULT" if fault else "UNKNOWN"
        try:
            self._generation = self._lease.fence()
        except Exception:
            self._state = "FAULT"
            self._reason = reason + "; persistent fencing unavailable"

    def _require_readback(
        self, snapshot: ChamberSnapshot, identity: ChamberIdentity | None = None,
    ) -> ChamberSnapshot:
        expected = identity if identity is not None else self._identity
        if expected is None or snapshot.identity != expected:
            raise ChamberSafetyError("Readback device identity mismatch")
        timestamp = snapshot.sampled_at_utc
        if snapshot.quality is not ReadingQuality.GOOD or timestamp is None or (
            timestamp.tzinfo is None
        ):
            raise ChamberSafetyError("Readback unavailable or stale")
        age = (datetime.now(timezone.utc) - timestamp).total_seconds()
        if not -1 <= age <= self._max_age:
            raise ChamberSafetyError("Readback outside freshness window")
        if snapshot.operation_state not in (OperationState.STOPPED, OperationState.RUNNING):
            raise ChamberSafetyError("Readback reports unknown/fault")
        target = snapshot.setpoint_temperature_c
        if target is not None and not math.isfinite(target):
            raise ChamberSafetyError("Readback setpoint must be finite")
        measured = snapshot.measured_temperature_c
        if measured is None or not math.isfinite(measured):
            raise ChamberSafetyError("Readback measurement must be finite")
        return snapshot

    def _verified_write(self, operation: Callable, *,
                        running: OperationState | None = None,
                        target: float | None = None) -> None:
        ramps = bool(target is not None and self._capabilities is not None and
                     self._capabilities.setpoint_readback_ramp_c_per_min)
        before = None
        if ramps:
            before = self._require_readback(self._backend.read_status()).setpoint_temperature_c
            if before is None or not math.isfinite(before):
                raise ChamberSafetyError("Setpoint readback unavailable before write")
        operation()
        snapshot = self._require_readback(self._backend.read_status())
        if running is not None and snapshot.operation_state is not running:
            raise ChamberSafetyError("State readback did not confirm command")
        if target is not None:
            readback = snapshot.setpoint_temperature_c
            if readback is None or not math.isfinite(readback):
                raise ChamberSafetyError("Setpoint readback did not confirm command")
            if ramps:
                # Device-side ramp: the readback must lie on the path from the
                # previous setpoint to the target. G05 awaits convergence via
                # separate fresh reads so STOP is never queued behind a ramp.
                low, high = min(before, target) - 0.1, max(before, target) + 0.1
                if not low <= readback <= high:
                    raise ChamberSafetyError("Setpoint readback is not ramping toward target")
            elif abs(readback - target) > 0.1:
                raise ChamberSafetyError("Setpoint readback did not confirm command")
        with self._state_lock:
            self._last_snapshot = snapshot

    def set_temperature(self, chamber_id: str, target_c: float,
                        *, operator_token: str | None = None) -> None:
        self._check_id(chamber_id)
        with self._state_lock:
            self._check_operator(operator_token)
            caps = self._capabilities
            if caps is None or not caps.supports_setpoint_readback:
                raise ChamberSafetyError("Cannot control without setpoint readback")
            target = finite_temperature(
                target_c, caps.temperature_min_c, caps.temperature_max_c,
            )
        self._submit("set_temperature",
                     lambda: self._verified_write(
                         lambda: self._backend.set_temperature(target), target=target),
                     mutation=True, operator_token=operator_token)
        with self._state_lock:
            if self._stop_latched:
                raise ChamberSafetyError("Setpoint result superseded by STOP/FAULT")

    def _verified_ramp_write(self, operation: Callable, direction: str,
                             expected: float) -> None:
        operation()
        snapshot = self._require_readback(self._backend.read_status())
        actual = (snapshot.gradient_up_c_per_min if direction == "up"
                  else snapshot.gradient_down_c_per_min)
        if actual is None or not math.isfinite(actual) or abs(actual - expected) > 0.01:
            raise ChamberSafetyError("Gradient readback did not confirm command")
        with self._state_lock:
            self._last_snapshot = snapshot

    def _check_ramp(self, direction: str, rate_c_per_min: float) -> float:
        caps = self._capabilities
        supported = (caps is not None and
                     getattr(caps, "supports_ramp_" + direction))
        limits = (getattr(caps, "ramp_" + direction + "_range_c_per_min", None)
                  if supported else None)
        if not supported or not limits:
            raise ChamberSafetyError(
                "Gradients are not supported/verified by this backend")
        if (isinstance(rate_c_per_min, bool) or
                not isinstance(rate_c_per_min, (int, float)) or
                not math.isfinite(rate_c_per_min)):
            raise ChamberSafetyError("Invalid gradient rate")
        low, high = limits
        if not low <= float(rate_c_per_min) <= high:
            raise ChamberSafetyError("Gradient outside supported range")
        return float(rate_c_per_min)

    def set_ramp_up(self, chamber_id: str, rate_c_per_min: float, *,
                    operator_token: str | None = None) -> None:
        self._check_id(chamber_id)
        with self._state_lock:
            self._check_operator(operator_token)
            rate = self._check_ramp("up", rate_c_per_min)
        self._submit("set_ramp_up",
                     lambda: self._verified_ramp_write(
                         lambda: self._backend.set_ramp_up(rate), "up", rate),
                     mutation=True, operator_token=operator_token)
        with self._state_lock:
            if self._stop_latched:
                raise ChamberSafetyError("Gradient result superseded by STOP/FAULT")

    def set_ramp_down(self, chamber_id: str, rate_c_per_min: float, *,
                      operator_token: str | None = None) -> None:
        self._check_id(chamber_id)
        with self._state_lock:
            self._check_operator(operator_token)
            rate = self._check_ramp("down", rate_c_per_min)
        self._submit("set_ramp_down",
                     lambda: self._verified_ramp_write(
                         lambda: self._backend.set_ramp_down(rate), "down", rate),
                     mutation=True, operator_token=operator_token)
        with self._state_lock:
            if self._stop_latched:
                raise ChamberSafetyError("Gradient result superseded by STOP/FAULT")

    def start(self, chamber_id: str, *, operator_token: str | None = None) -> None:
        self._check_id(chamber_id)
        with self._state_lock:
            self._check_operator(operator_token)
            caps = self._capabilities
            if caps is None or not caps.supports_start_stop or not caps.supports_running_readback:
                raise ChamberSafetyError("Backend cannot verify running state")
        self._submit("start",
                     lambda: self._verified_write(
                         self._backend.start, running=OperationState.RUNNING),
                     mutation=True, operator_token=operator_token)
        with self._state_lock:
            if self._stop_latched:
                raise ChamberSafetyError("START result superseded by STOP/FAULT")
            self._state = "RUNNING"

    def set_profile_running(self, chamber_id: str, running: bool, *,
                            operator_token: str | None = None) -> None:
        """Set simulated profile operation state without invoking safety STOP.

        Physical callers must continue to use the certified START and latched
        STOP paths. This method exists only so a simulated profile can contain
        an OFF dwell followed by a later ON step.
        """
        self._check_id(chamber_id)
        if type(running) is not bool:
            raise ChamberSafetyError("Profile run state must be boolean")
        with self._state_lock:
            self._check_operator(operator_token)
            caps = self._capabilities
            identity = self._identity
            if (identity is None or not identity.is_simulation or caps is None or
                    not caps.supports_start_stop or not caps.supports_running_readback):
                raise ChamberSafetyError(
                    "Per-step chamber run control is simulation-only"
                )
        expected = OperationState.RUNNING if running else OperationState.STOPPED
        operation = self._backend.start if running else self._backend.stop
        self._submit(
            "profile_run_on" if running else "profile_run_off",
            lambda: self._verified_write(operation, running=expected),
            mutation=True, operator_token=operator_token,
        )
        with self._state_lock:
            if self._stop_latched:
                raise ChamberSafetyError("Profile run result superseded by STOP/FAULT")
            self._state = "RUNNING" if running else "VERIFIED_STOPPED"

    def set_digital_output(self, chamber_id: str, number: int, state: bool, *,
                           operator_token: str | None = None) -> None:
        """Set and verify one explicitly advertised simulated output."""
        self._check_id(chamber_id)
        if type(number) is not int or type(state) is not bool:
            raise ChamberSafetyError("Digital output number/state invalid")
        with self._state_lock:
            self._check_operator(operator_token)
            identity = self._identity
            caps = self._capabilities
            available = {item[0] for item in caps.digital_outputs} if caps else set()
            if identity is None or not identity.is_simulation:
                raise ChamberSafetyError("Profile digital outputs are simulation-only")
            if number == 1 or number not in available:
                raise ChamberSafetyError("Digital output is not supported/verified")

        def write_and_verify() -> None:
            self._backend.set_digital_output(number, state)
            if self._backend.read_digital_output(number) is not state:
                raise ChamberSafetyError("Digital output readback did not confirm command")

        self._submit(
            "set_digital_output", write_and_verify,
            mutation=True, operator_token=operator_token,
        )
        with self._state_lock:
            if self._stop_latched:
                raise ChamberSafetyError("Digital output result superseded by STOP/FAULT")

    def stop(self, chamber_id: str) -> None:
        """STOP bypasses operator ownership; intent is synchronous and fenced."""
        self._check_id(chamber_id)
        with self._state_lock:
            self._stop_latched = True
            self._state = "STOP_REQUESTED"
            self._reason = "STOP requested; awaiting authoritative readback"
            if not self._connected and self._thread is None:
                self._state = "UNKNOWN"
                raise ChamberSafetyError("STOP cannot be verified: not connected")
            try:
                self._generation = self._lease.fence()
            except Exception as exc:
                self._state = "FAULT"
                raise ChamberSafetyError("STOP fencing could not be persisted") from exc
            intent_generation = self._generation
            if not self._connected:
                self._state = "UNKNOWN"
                raise ChamberSafetyError("STOP cannot be verified: not connected")
        def attempt_stop():
            self._backend.stop()  # no unapproved retries
            return self._require_readback(self._backend.read_status())
        try:
            snapshot = self._submit("stop", attempt_stop, priority=-100)
            if snapshot.operation_state is not OperationState.STOPPED:
                raise ChamberSafetyError("STOP readback still indicates RUNNING")
        except Exception:
            with self._state_lock:
                if intent_generation == self._generation and self._state != "FAULT":
                    self._trip("STOP effect unverified")
            raise
        with self._state_lock:
            if intent_generation != self._generation:
                raise ChamberSafetyError("STOP superseded by another fault or STOP")
            self._last_snapshot = snapshot
            self._state = "VERIFIED_STOPPED"
            self._reason = None
            # The fence deliberately remains latched until explicit reconciliation.

    def reconcile_stop(self, chamber_id: str) -> None:
        self._check_id(chamber_id)
        with self._state_lock:
            if not self._connected or not self._stop_latched:
                raise ChamberSafetyError("No STOP/UNKNOWN latch to reconcile")
            reconcile_generation = self._generation
        snapshot = self._submit(
            "reconcile", lambda: self._require_readback(self._backend.read_status()),
            priority=0,
        )
        with self._state_lock:
            if reconcile_generation != self._generation or not self._stop_latched:
                raise ChamberSafetyError("Reconciliation superseded by newer STOP/FAULT")
            if snapshot.operation_state is not OperationState.STOPPED:
                raise ChamberSafetyError("Manual reconciliation requires verified STOPPED")
            self._lease.reconcile()
            self._last_snapshot = snapshot
            self._stop_latched = False
            self._state = "VERIFIED_STOPPED"
            self._reason = None

    def status(self, chamber_id: str) -> ChamberSnapshot:
        self._check_id(chamber_id)
        try:
            snapshot = self._submit(
                "poll", lambda: self._require_readback(self._backend.read_status()),
                priority=20,
            )
            with self._state_lock:
                self._last_snapshot = snapshot
                if (self._state == "VERIFIED_STOPPED" and
                        snapshot.operation_state is OperationState.RUNNING):
                    self._trip("Unexpected RUNNING after verified STOP")
            return snapshot
        except Exception:
            with self._state_lock:
                identity = self._identity
            if identity is None:
                raise ChamberSafetyError("No verified chamber identity available")
            return ChamberSnapshot(
                identity, None, None, OperationState.UNKNOWN,
                ReadingQuality.ERROR, None,
            )

    def start_polling(self, chamber_id: str, *, interval_s: float = 2.0) -> None:
        self._check_id(chamber_id)
        if not math.isfinite(interval_s) or not 0.1 <= interval_s <= 3600:
            raise ValueError("Polling interval must be finite and 0.1..3600 s")
        with self._state_lock:
            if not self._connected:
                raise ChamberSafetyError("Cannot poll a disconnected device")
            if self._poll_thread is not None and self._poll_thread.is_alive():
                return
            self._poll_stop.clear()
            def loop():
                while not self._poll_stop.wait(interval_s):
                    # Avoid an unbounded queue of polls behind a hung driver.
                    if self._queue.qsize() == 0:
                        self.status(self.chamber_id)  # outside UI event loop
            self._poll_thread = threading.Thread(
                target=loop, daemon=True, name="chamber-poll-" + self.chamber_id,
            )
            self._poll_thread.start()

    def disconnect(self, chamber_id: str) -> None:
        """Fence queued control before any backend disconnect; no implicit STOP."""
        self._check_id(chamber_id)
        self._poll_stop.set()
        with self._state_lock:
            if self._closed:
                return
            if self._thread is None:
                self._closed = True
                return
            if self._disconnecting:
                raise ChamberSafetyError("Disconnect already in progress")
            self._disconnecting = True
            # Existing VERIFIED_STOPPED is not a durable fact unless the
            # authoritative GOOD snapshot is still fresh at shutdown.
            snapshot = self._last_snapshot
            fresh_stop = False
            if (self._connected and not self._stop_latched
                    and self._state == "VERIFIED_STOPPED"
                    and snapshot is not None
                    and snapshot.operation_state is OperationState.STOPPED
                    and snapshot.quality is ReadingQuality.GOOD
                    and snapshot.sampled_at_utc is not None
                    and snapshot.sampled_at_utc.tzinfo is not None):
                age = (datetime.now(timezone.utc) - snapshot.sampled_at_utc).total_seconds()
                fresh_stop = -1 <= age <= self._max_age
            # Quiesce all queued mutations BEFORE enqueueing disconnect.
            # Never mark physical STOP as verified just because disconnect ran.
            self._stop_latched = True
            self._state = "UNKNOWN"
            self._reason = "Disconnect requested; STOP not reverified"
            try:
                self._generation = self._lease.fence()
            except Exception as exc:
                self._state = "FAULT"
                raise ChamberSafetyError("Unable to persist disconnect fence") from exc
            disconnect_generation = self._generation
        # Verify again on the I/O worker AFTER every already-admitted action:
        # an in-flight START could have completed after the initial sample.
        # A failed readback must not prevent best-effort backend cleanup.
        def close_backend() -> bool:
            stopped_now = False
            try:
                observed = self._require_readback(self._backend.read_status())
                stopped_now = observed.operation_state is OperationState.STOPPED
            except Exception:
                pass  # uncertainty is preserved in the persistent lease
            self._backend.disconnect()
            return stopped_now

        # If an adapter hangs, retain the exclusive OS lock.
        final_stop_readback = self._submit(
            "disconnect", close_backend, priority=-50,
        )
        with self._state_lock:
            verified = (
                fresh_stop and final_stop_readback and
                disconnect_generation == self._generation
            )
            self._closed = True
            self._connected = False
            self._state = "DISCONNECTED"
            self._queue.put((100, next(self._sequence), None))
        self._thread.join(timeout=self._timeout)
        if self._thread.is_alive():
            raise ChamberSafetyError("Worker still active; process lock retained")
        self._lease.close(verified_stopped=verified)
