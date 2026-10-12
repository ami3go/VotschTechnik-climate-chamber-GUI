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
    ChamberBackend, ChamberCapabilities, ChamberIdentity, ChamberSafetyError,
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


class ChamberController:
    """One controller, one worker, one process-exclusive lease, one backend.

    Server-side callers must supply the bound chamber ID. Operator ownership
    tokens provide conflict protection, not authentication (G08-min pending).
    """

    def __init__(
        self, config: ChamberConfig, backend: ChamberBackend, *,
        lease_directory: Path | None = None,
        io_timeout_s: float = 2.0, max_sample_age_s: float = 5.0,
        allow_mock_vendor_backend: bool = False,
    ):
        if not 0 < io_timeout_s <= 60 or not math.isfinite(io_timeout_s):
            raise ValueError("I/O timeout must be finite, >0 and <=60 s")
        if not 0 < max_sample_age_s <= 60 or not math.isfinite(max_sample_age_s):
            raise ValueError("Readback age must be finite, >0 and <=60 s")
        # The real vendor adapter is not activated by this release. Only a
        # separately injected mock may exercise its protocol translation.
        self._mock_vendor_allowed = allow_mock_vendor_backend
        self._backend_id = config.backend_id
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
        self._stop_latched = True
        self._state = "DISCONNECTED"
        self._reason: str | None = None
        self._identity: ChamberIdentity | None = None
        self._capabilities: ChamberCapabilities | None = None
        self._last_snapshot: ChamberSnapshot | None = None
        self._operator_token: str | None = None
        self._operator_name: str | None = None

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
            self._operator_name = owner.strip()
            return self._operator_token

    def release_operator(self, chamber_id: str, token: str) -> None:
        self._check_id(chamber_id)
        with self._state_lock:
            if not self._operator_token or token != self._operator_token:
                raise ChamberSafetyError("Operator lease token mismatch")
            self._operator_token = None
            self._operator_name = None

    def _check_operator(self, token: str | None) -> None:
        # Until G08-min, the no-token path is for trusted server code only.
        # G08-min MUST require authenticated identity at all external entrypoints.
        if self._operator_token is not None and token != self._operator_token:
            raise ChamberSafetyError("Operator lease owned by another caller")

    def connect(self, chamber_id: str) -> None:
        self._check_id(chamber_id)
        with self._state_lock:
            if self._backend_id not in ("fake", "alternate_stub") and not (
                self._backend_id == "votsch" and self._mock_vendor_allowed
            ):
                raise ChamberSafetyError("Physical hardware I/O DISABLED; mock backends only")
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
            if identity.chamber_id != self.chamber_id or not identity.is_simulation:
                raise ChamberSafetyError("Device identity mismatch / live hardware DISABLED")
            caps = self._backend.capabilities()
            snapshot = self._backend.read_status()
            self._require_readback(snapshot, identity)
            return identity, caps, snapshot
        identity, caps, snapshot = self._submit(
            "connect", initialize, priority=0,
        )
        with self._state_lock:
            self._identity, self._capabilities = identity, caps
            self._last_snapshot = snapshot
            self._connected = True
            if snapshot.operation_state is OperationState.FAULT:
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
                if (work.name != "stop" and work.generation != self._generation) or (
                    work.mutation and self._stop_latched
                ):
                    work.future.set_exception(
                        ChamberSafetyError("Queued command fenced by STOP/FAULT")
                    )
                    continue
                try:
                    self._lease.verify(self._generation if work.name == "stop" else work.generation)
                except Exception as exc:
                    work.future.set_exception(exc)
                    self._trip("Lease/generation verification failed", fault=True)
                    continue
            try:
                result = work.action()
            except Exception as exc:
                with self._state_lock:
                    self._trip("Backend " + work.name + " failed: " + type(exc).__name__)
                work.future.set_exception(exc)
            else:
                work.future.set_result(result)

    def _submit(self, name: str, action: Callable[[], T], *, priority: int = 10,
                mutation: bool = False, timeout: float | None = None) -> T:
        with self._state_lock:
            if self._closed or self._thread is None:
                raise ChamberSafetyError("Controller not active")
            generation = self._generation
            if mutation and (not self._connected or self._stop_latched):
                raise ChamberSafetyError("Operation blocked: disconnected or STOP-latched")
            request = _Work(name, action, Future(), generation, mutation)
            self._queue.put((priority, next(self._sequence), request))
        try:
            return request.future.result(timeout=self._timeout if timeout is None else timeout)
        except FutureTimeout as exc:
            with self._state_lock:
                self._trip("Backend " + name + " exceeded deadline; effect unknown")
            raise ChamberSafetyError("I/O timeout; device state UNKNOWN") from exc

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
        if snapshot.operation_state in (OperationState.UNKNOWN, OperationState.FAULT):
            raise ChamberSafetyError("Readback reports unknown/fault")
        return snapshot

    def _verified_write(self, operation: Callable, *,
                        running: OperationState | None = None,
                        target: float | None = None) -> None:
        operation()
        snapshot = self._require_readback(self._backend.read_status())
        if running is not None and snapshot.operation_state is not running:
            raise ChamberSafetyError("State readback did not confirm command")
        if target is not None and (
            snapshot.setpoint_temperature_c is None or
            not math.isfinite(snapshot.setpoint_temperature_c) or
            abs(snapshot.setpoint_temperature_c - target) > 0.1
        ):
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
                     mutation=True)

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
                     mutation=True)
        with self._state_lock:
            if not self._stop_latched:
                self._state = "RUNNING"

    def stop(self, chamber_id: str) -> None:
        """STOP bypasses operator ownership; intent is synchronous and fenced."""
        self._check_id(chamber_id)
        with self._state_lock:
            self._stop_latched = True
            self._state = "STOP_REQUESTED"
            self._reason = "STOP requested; awaiting authoritative readback"
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
                if self._state != "FAULT":
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
        snapshot = self._submit(
            "reconcile", lambda: self._require_readback(self._backend.read_status()),
            priority=0,
        )
        if snapshot.operation_state is not OperationState.STOPPED:
            raise ChamberSafetyError("Manual reconciliation requires verified STOPPED")
        with self._state_lock:
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
                    self.status(self.chamber_id)  # bounded, queued, never in UI loop
            self._poll_thread = threading.Thread(
                target=loop, daemon=True, name="chamber-poll-" + self.chamber_id,
            )
            self._poll_thread.start()

    def disconnect(self, chamber_id: str) -> None:
        self._check_id(chamber_id)
        self._poll_stop.set()
        with self._state_lock:
            if self._closed:
                return
            if self._thread is None:
                self._closed = True
                return
        # Do not unlock the device if a timed-out adapter thread still runs.
        self._submit("disconnect", self._backend.disconnect, priority=0)
        with self._state_lock:
            verified = (
                self._last_snapshot is not None
                and self._last_snapshot.operation_state is OperationState.STOPPED
                and self._state == "VERIFIED_STOPPED"
            )
            self._closed = True
            self._connected = False
            self._stop_latched = True
            self._state = "DISCONNECTED"
            self._queue.put((100, next(self._sequence), None))
        self._thread.join(timeout=self._timeout)
        if self._thread.is_alive():
            raise ChamberSafetyError("Worker still active; process lock retained")
        self._lease.close(verified_stopped=verified)
