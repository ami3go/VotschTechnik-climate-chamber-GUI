"""G06-A: single-device simulated execution through the G04 ChamberManager.

Physical execution exists only through the narrowly-scoped SupervisedRun
context: an H02 signed-permit admission whose revalidation runs before every
dispatch tick; steps are restricted to chamber_run=ON without output or
gradient mutations and START uses the certified G04 start path once.

Every public mutation requires a server-injected G08 authorization decision.
Synchronous entrypoints must be called off the NiceGUI event loop; async
wrappers use asyncio.to_thread. STOP remains owned/fenced by G04, not by this
scheduler.
"""
from __future__ import annotations

import asyncio
import math
from collections import deque
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Protocol
from uuid import uuid4

from chamber_web.domain.chamber import (
    ChamberCapabilities, ChamberIdentity, ChamberSafetyError, OperationState,
    ReadingQuality, finite_temperature, validate_chamber_id,
)
from chamber_web.domain.profile import ProfileStep
from chamber_web.persistence.profiles import ProfileRevision, ProfileStore
from chamber_web.services.chamber_manager import ChamberManager


class RunState(str, Enum):
    PREPARING = "PREPARING"
    REACHING = "REACHING"
    STABILIZING = "STABILIZING"
    DWELLING = "DWELLING"
    TRANSITIONING = "TRANSITIONING"
    PAUSED = "PAUSED"
    STOP_REQUESTED = "STOP_REQUESTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAULT = "FAULT"
    UNKNOWN = "UNKNOWN"


TERMINAL = frozenset({
    RunState.COMPLETED, RunState.CANCELLED, RunState.FAULT, RunState.UNKNOWN,
})


class Clock(Protocol):
    def monotonic(self) -> float: ...


class RealClock:
    def monotonic(self) -> float:
        return time.monotonic()


class VirtualClock:
    """Test-only injectable monotonic clock; no scheduler or sleeping."""
    def __init__(self, start: float = 0.0):
        if not math.isfinite(start):
            raise ValueError("Invalid virtual clock origin")
        self._now = float(start)

    def monotonic(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("Virtual clock cannot go backwards")
        self._now += seconds


@dataclass(frozen=True)
class RunParameters:
    poll_s: float = 2.0
    max_gap_s: float = 5.0
    max_age_s: float = 5.0
    step_margin_s: float = 15.0
    max_run_s: float | None = None

    def __post_init__(self) -> None:
        for key in ("poll_s", "max_gap_s", "max_age_s", "step_margin_s"):
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, (float, int)) or (
                not math.isfinite(value) or value <= 0 or value > 60
            ):
                raise ValueError("Invalid finite run parameter: " + key)
        if self.poll_s > self.max_gap_s or self.max_gap_s > 5 or self.max_age_s > 5:
            raise ValueError("Sampling windows exceed P00 policy")
        if self.max_run_s is not None and (
            isinstance(self.max_run_s, bool) or
            not isinstance(self.max_run_s, (int, float)) or
            not math.isfinite(self.max_run_s) or
            not 0 < self.max_run_s <= 1_209_600
        ):
            raise ValueError("Run watchdog must be finite, <= 14 days")


@dataclass(frozen=True)
class ExecutionSnapshot:
    schema_version: int
    run_id: str
    chamber_id: str
    identity: ChamberIdentity
    capabilities: ChamberCapabilities
    profile_id: str
    revision: int
    revision_sha256: str
    revision_saved_at_utc: str
    revision_source: str
    profile_name: str
    steps: tuple[ProfileStep, ...]
    repeat_count: int
    completion_action: str
    parameters: RunParameters
    operator_id: str
    created_at_utc: str
    controller_generation: int


@dataclass(frozen=True)
class RunEvent:
    run_id: str
    chamber_id: str
    sequence: int
    kind: str
    state: RunState
    monotonic_elapsed_s: float
    step_index: int
    detail: str = ""
    temperature_c: float | None = None
    quality: ReadingQuality | None = None
    observed_at_utc: str = ""
    source_sampled_at_utc: str | None = None
    sample_index: int | None = None
    # Independently observed device readback, never the intended setpoint.
    setpoint_temperature_c: float | None = None
    # G04 generation the event was observed under (crash reconciliation).
    controller_generation: int | None = None


class EventSink(Protocol):
    def prepare(self, snapshot: ExecutionSnapshot) -> None: ...
    def emit(self, event: RunEvent) -> None: ...


@dataclass(frozen=True)
class SupervisedRun:
    """Server-side supervised-physical run context; never browser-supplied.

    ``revalidate`` re-verifies the signed site permit (signature, window,
    unchanged bytes) and is invoked before every dispatch tick; any failure
    stops further physical dispatch and latches UNKNOWN.

    ``supervisor_alive`` reports the H02-C independent watchdog liveness; a
    false value at any tick stops further dispatch through the same bounded
    STOP path. The G04 controller remains the single STOP authority, so a
    watchdog alarm that bypasses the tick loop can still stop the chamber.
    """
    permit_sha256: str
    operator: str
    revalidate: Callable[[], None]
    supervisor_alive: Callable[[], bool] | None = None


def ramp_duration_s(step: ProfileStep, from_temperature_c: float | None) -> float:
    """Worst-case declared device ramp time from the previous target."""
    if from_temperature_c is None:
        return 0.0
    delta = float(step.target_temperature_c) - float(from_temperature_c)
    if delta > 0:
        rate = step.ramp_up_c_per_min
    elif delta < 0:
        rate = step.ramp_down_c_per_min
    else:
        return 0.0
    if rate is None:
        return 0.0
    return abs(delta) / float(rate) * 60.0


def step_budget(step: ProfileStep, params: RunParameters, *,
                from_temperature_c: float | None = None) -> float:
    """Finite per-step schedule used for permit preflight and watchdogs."""
    reach = float(step.reach_timeout_s)
    if not math.isfinite(reach) or reach <= 0 or reach > 1_209_600:
        raise ValueError("Invalid finite profile reach")
    total = reach
    for value, name in ((step.stabilize_s, "stabilize"), (step.dwell_s, "dwell")):
        number = float(value)
        if not math.isfinite(number) or number < 0 or number > 1_209_600:
            raise ValueError("Invalid finite profile " + name)
        total += number
    ramp = ramp_duration_s(step, from_temperature_c)
    if ramp > reach:
        raise ValueError("Reach timeout is shorter than the declared gradient")
    return total + ramp + params.step_margin_s


# Authorizer must resolve an authenticated server-side principal by itself.
# An arbitrary browser-supplied user name or operator token is NOT authorization.
Authorizer = Callable[[str, str], str]


class ProfileRunner:
    """One server-owned runner; one manager; no multi-chamber scheduler.

    The constructor requires a trusted server-side authorizer. Until G08-min
    provides one, no run/cancel/pause/resume operation is permitted. G07 should
    supply a durable EventSink; no disk or database journaling occurs here.
    """

    def __init__(
        self, manager: ChamberManager, store: ProfileStore, *,
        authorize: Authorizer | None = None,
        sink: EventSink | None = None,
        clock: Clock | None = None,
        supervised: SupervisedRun | None = None,
    ):
        ids = manager.configured_ids()
        if len(ids) != 1:
            raise ChamberSafetyError("Only a single chamber runner is supported")
        if supervised is not None and (
                not isinstance(supervised, SupervisedRun) or
                not isinstance(supervised.permit_sha256, str) or
                len(supervised.permit_sha256) != 64 or
                not isinstance(supervised.operator, str) or
                not supervised.operator.strip() or
                not callable(supervised.revalidate) or
                (supervised.supervisor_alive is not None and
                 not callable(supervised.supervisor_alive))):
            raise ChamberSafetyError("Invalid supervised run context")
        self._id = ids[0]
        self._manager = manager
        self._store = store
        self._authorize = authorize
        self._sink = sink
        self._clock = clock or RealClock()
        self._supervised = supervised
        self._mutex = threading.RLock()
        self._advance_lock = threading.Lock()
        self._stop_guard = threading.Lock()
        self._event_guard = threading.RLock()
        # STOP uses a separate caller from any potentially blocked poll/setpoint.
        self._stop_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="profile-stop")
        self._closed = False
        self._snapshot: ExecutionSnapshot | None = None
        self._scheduled_steps: tuple[ProfileStep, ...] = ()
        self._state: RunState | None = None
        self._reason = ""
        self._events: deque[RunEvent] = deque(maxlen=1024)  # diagnostic, NOT G07
        self._event_sequence = 0
        self._sample_index = 0
        self._owner_token: str | None = None
        self._t0 = 0.0
        self._run_deadline = 0.0
        self._step_deadline = 0.0
        self._reach_deadline = 0.0
        self._step_started = 0.0
        self._step_index = 0
        self._last_good: float | None = None
        self._last_source_timestamp: datetime | None = None
        self._stable_from: float | None = None
        self._stable_count = 0
        self._dwell_elapsed = 0.0
        self._cancel_requested = False
        self._watchdog_reason: str | None = None
        self._prepared = False
        self._stop_future: Future | None = None
        self._terminal_after_stop = RunState.UNKNOWN
        self._profile_running = False
        # Ramp-aware setpoint convergence supervision for the current step.
        self._setpoint_best = math.inf
        self._setpoint_observed: float | None = None
        self._setpoint_frozen = 0
        self._setpoint_progress_at: float | None = None

    @property
    def state(self) -> RunState | None:
        with self._mutex:
            return self._state

    @property
    def snapshot(self) -> ExecutionSnapshot | None:
        with self._mutex:
            return self._snapshot

    @property
    def reason(self) -> str:
        with self._mutex:
            return self._reason

    @property
    def progress(self) -> tuple[int, int]:
        """Return the zero-based scheduled step index and total including repeats."""
        with self._mutex:
            return self._step_index, len(self._scheduled_steps)

    @property
    def events(self) -> tuple[RunEvent, ...]:
        with self._event_guard:
            return tuple(self._events)

    def _permission(self, action: str) -> str:
        if self._authorize is None:
            raise ChamberSafetyError("G08-min authorization not configured")
        principal = self._authorize(action, self._id)
        if not isinstance(principal, str) or not principal.strip() or len(principal) > 128:
            raise ChamberSafetyError("Authenticated operator identity required")
        return principal

    def _now(self) -> float:
        value = self._clock.monotonic()
        if not math.isfinite(value):
            raise ChamberSafetyError("Monotonic clock unavailable")
        return value

    @staticmethod
    def _duration(value: object, name: str, *, positive: bool = False) -> float:
        try:
            number = float(value)
        except (ValueError, TypeError, OverflowError) as exc:
            raise ValueError("Invalid profile " + name) from exc
        if not math.isfinite(number) or number < 0 or (positive and number == 0) or number > 1_209_600:
            raise ValueError("Invalid finite profile " + name)
        return number

    def _step_budget(self, step: ProfileStep, params: RunParameters, *,
                     from_temperature_c: float | None = None) -> float:
        return step_budget(step, params, from_temperature_c=from_temperature_c)

    def _validate_gradients(self, step: ProfileStep,
                            caps: ChamberCapabilities) -> None:
        for direction, value in (("up", step.ramp_up_c_per_min),
                                 ("down", step.ramp_down_c_per_min)):
            if value is None:
                continue
            if self._supervised is not None:
                raise ChamberSafetyError(
                    "Supervised physical gradients require a signed H03 "
                    "authorization; gradients unsupported for this permit")
            if not getattr(caps, "supports_ramp_" + direction):
                raise ChamberSafetyError(
                    "Hardware gradients unsupported by the connected backend")
            limits = getattr(caps, "ramp_" + direction + "_range_c_per_min")
            rate = float(value)
            if not limits or not math.isfinite(rate) or not (
                    limits[0] <= rate <= limits[1]):
                raise ValueError(
                    direction.title() + " gradient outside supported range")

    def _emit(self, kind: str, detail: str = "", *,
              temperature: float | None = None,
              quality: ReadingQuality | None = None,
              source_sampled_at_utc: datetime | None = None,
              setpoint: float | None = None) -> None:
        assert self._snapshot is not None and self._state is not None
        with self._event_guard:
            self._event_sequence += 1
            if kind == "SAMPLE":
                self._sample_index += 1
            event = RunEvent(
                self._snapshot.run_id, self._id, self._event_sequence,
                kind, self._state, max(0.0, self._now() - self._t0),
                self._step_index, detail, temperature, quality,
                datetime.now(timezone.utc).isoformat(timespec="microseconds"),
                source_sampled_at_utc.isoformat() if source_sampled_at_utc else None,
                self._sample_index if kind == "SAMPLE" else None,
                setpoint, self._snapshot.controller_generation,
            )
            if self._sink is not None:
                self._sink.emit(event)  # fail closed; not best-effort logging
            self._events.append(event)

    def _transition(self, state: RunState, detail: str = "") -> None:
        self._state = state
        self._emit("STATE", detail)

    def start(self, chamber_id: str, profile_id: str, *, revision: int,
              parameters: RunParameters | None = None) -> ExecutionSnapshot:
        """Prepare only. Call advance() to dispatch commands, off the event loop."""
        validate_chamber_id(chamber_id)
        if chamber_id != self._id:
            raise ChamberSafetyError("Wrong chamber for profile run")
        principal = self._permission("profile.start")
        if (self._supervised is not None and
                principal != self._supervised.operator):
            raise ChamberSafetyError("Supervised physical run is bound to the permit operator")
        params = parameters or RunParameters()
        if not isinstance(params, RunParameters):
            raise ValueError("Invalid run parameters")
        with self._mutex:
            if self._closed:
                raise ChamberSafetyError("Runner is closed; cannot start again")
            if self._state is not None and self._state not in TERMINAL:
                raise ChamberSafetyError("An execution is already active")
            record: ProfileRevision = self._store.get_revision(
                chamber_id, profile_id, revision=revision,
            )
            enabled = tuple(s for s in record.profile.steps if s.enabled)
            if not enabled or record.profile.completion_action != "STOP":
                raise ChamberSafetyError("Only nonempty STOP profiles can run")
            caps = self._manager.capabilities(self._id)
            health = self._manager.health(self._id)
            status = self._manager.status(self._id)
            if self._supervised is None:
                identity_allowed = status.identity.is_simulation
            else:
                # Supervised runs are physical only, on the exact authorized
                # Vötsch backend with a reported serial.
                identity_allowed = (
                    not status.identity.is_simulation and
                    status.identity.backend_id == "votsch" and
                    bool(status.identity.serial_number))
            if (not health.connected or health.stop_latched or
                health.state not in ("VERIFIED_STOPPED",) or
                status.quality is not ReadingQuality.GOOD or
                status.operation_state is not OperationState.STOPPED or
                status.identity.chamber_id != self._id or
                not identity_allowed):
                raise ChamberSafetyError("Profile requires reconciled simulated STOPPED chamber")
            if not (caps.supports_start_stop and caps.supports_running_readback and
                    caps.supports_setpoint_readback):
                raise ChamberSafetyError("Missing mandatory verified control/readback capability")
            budgets: list[float] = []
            previous_target: float | None = None
            for step in enabled:
                try:
                    target = float(step.target_temperature_c)
                except (TypeError, ValueError, OverflowError) as exc:
                    raise ValueError("Invalid target") from exc
                finite_temperature(target, caps.temperature_min_c, caps.temperature_max_c)
                self._duration(step.tolerance_c, "tolerance", positive=True)
                self._validate_gradients(step, caps)
                budgets.append(self._step_budget(
                    step, params, from_temperature_c=previous_target))
                previous_target = target
                if step.chamber_run not in ("UNCHANGED", "ON", "OFF") or any(
                    directive not in ("UNCHANGED", "ON", "OFF")
                    for directive in (step.compressed_air, step.dryer)
                ):
                    raise ValueError("Invalid profile output directive")
                if any(
                    type(number) is not int or type(state) is not bool
                    for number, state in step.digital_outputs
                ):
                    raise ValueError("Invalid profile digital output command")
                available_outputs = {number for number, _ in caps.digital_outputs}
                requested_outputs = {number for number, _ in step.digital_outputs}
                if step.compressed_air != "UNCHANGED":
                    requested_outputs.add(7)
                if step.dryer != "UNCHANGED":
                    requested_outputs.add(8)
                if not requested_outputs <= available_outputs:
                    raise ChamberSafetyError(
                        "Profile requests unsupported/unverified digital outputs"
                    )
                if self._supervised is not None and (
                        step.chamber_run != "ON" or step.digital_outputs or
                        step.compressed_air != "UNCHANGED" or
                        step.dryer != "UNCHANGED" or
                        step.ramp_up_c_per_min is not None or
                        step.ramp_down_c_per_min is not None):
                    raise ChamberSafetyError(
                        "Supervised physical profiles run chamber_run=ON "
                        "steps without output or gradient mutations")
            total = sum(budgets) * record.profile.repeat_count + 30
            if not math.isfinite(total) or total > 1_209_600:
                raise ChamberSafetyError("Profile exceeds finite run watchdog limit")
            if params.max_run_s is not None:
                total = params.max_run_s
            owner = self._manager.claim_operator(self._id, principal)
            try:
                # Guard a handover/STOP race between preflight and lease grant.
                latest = self._manager.health(self._id)
                if latest.stop_latched or latest.generation != health.generation:
                    raise ChamberSafetyError("Controller generation changed during preparation")
                self._t0 = self._now()
                self._scheduled_steps = enabled * record.profile.repeat_count
                self._snapshot = ExecutionSnapshot(
                    1, str(uuid4()), self._id, status.identity, caps,
                    record.header.profile_id, record.revision, record.sha256,
                    record.saved_at_utc, record.source_format, record.profile.name,
                    enabled, record.profile.repeat_count, "STOP", params,
                    principal, datetime.now(timezone.utc).isoformat(), latest.generation,
                )
                self._owner_token = owner
                self._run_deadline = self._t0 + total
                self._step_index = 0
                self._step_started = self._t0
                # Allocate the first watchdog budget before supervision can be
                # armed.  Later step budgets are allocated atomically with the
                # step-index advance in _complete_step; _dispatch_step must not
                # reset them and make a same-step countdown move backwards.
                self._step_deadline = (
                    self._step_started + self._step_budget(
                        self._scheduled_steps[0], params,
                    )
                )
                self._state = RunState.PREPARING
                self._reason = ""
                with self._event_guard:
                    self._events.clear()
                    self._event_sequence = 0
                    self._sample_index = 0
                self._cancel_requested = False
                self._watchdog_reason = None
                self._prepared = False
                self._stop_future = None
                self._stable_from = self._last_good = None
                self._last_source_timestamp = None
                self._stable_count = 0
                self._dwell_elapsed = 0.0
                self._profile_running = False
                self._setpoint_best = math.inf
                self._setpoint_observed = None
                self._setpoint_frozen = 0
                if self._sink is not None:
                    # G07 must commit PREPARED snapshot before any mutation.
                    self._sink.prepare(self._snapshot)
                self._emit("PREPARED", "Immutable G03 revision and chamber snapshot")
                self._prepared = True  # external STOP cannot predate journal preparation
                return self._snapshot
            except BaseException:
                self._manager.release_operator(self._id, owner)
                self._owner_token = None
                self._prepared = False
                self._state = None
                self._snapshot = None
                self._scheduled_steps = ()
                raise

    async def start_async(self, *args, **kwargs) -> ExecutionSnapshot:
        return await asyncio.to_thread(self.start, *args, **kwargs)

    def _steps(self) -> tuple[ProfileStep, ...]:
        assert self._snapshot is not None
        return self._scheduled_steps

    def _step(self) -> ProfileStep:
        return self._steps()[self._step_index]

    def _healthy(self, *, running: bool) -> None:
        assert self._snapshot is not None
        health = self._manager.health(self._id)
        if (not health.connected or health.stop_latched or
                health.generation != self._snapshot.controller_generation or
                health.state in ("UNKNOWN", "FAULT", "STOP_REQUESTED", "DISCONNECTED")):
            raise ChamberSafetyError("Controller lost safe generation/connection")
        if running and health.state != "RUNNING":
            raise ChamberSafetyError("Controller no longer reports running")
        if not running and health.state != "VERIFIED_STOPPED":
            raise ChamberSafetyError("Controller no longer reports profile-stopped")

    def _dispatch_step(self) -> None:
        assert self._snapshot is not None and self._owner_token
        self._healthy(running=self._profile_running)
        step = self._step()
        target = float(step.target_temperature_c)
        self._setpoint_best = math.inf
        self._setpoint_observed = None
        self._setpoint_frozen = 0
        self._setpoint_progress_at = self._now()
        if self._step_index == 0:
            # START_INTENT fences the entire first mutating sequence,
            # including its setpoint, for G07 crash reconciliation.
            self._emit("START_INTENT", "First chamber mutation about to dispatch")
        if step.ramp_up_c_per_min is not None:
            self._emit("GRADIENT_INTENT", "Step " + str(step.step) + " upward")
            if self._cancel_requested:
                return
            self._manager.set_ramp_up(
                self._id, float(step.ramp_up_c_per_min),
                operator_token=self._owner_token)
        if step.ramp_down_c_per_min is not None:
            self._emit("GRADIENT_INTENT", "Step " + str(step.step) + " downward")
            if self._cancel_requested:
                return
            self._manager.set_ramp_down(
                self._id, float(step.ramp_down_c_per_min),
                operator_token=self._owner_token)
        self._emit("SETPOINT_INTENT", "Step " + str(step.step), temperature=target)
        if self._cancel_requested:
            return
        self._manager.set_temperature(self._id, target, operator_token=self._owner_token)
        output_commands = list(step.digital_outputs)
        if step.compressed_air != "UNCHANGED":
            output_commands.append((7, step.compressed_air == "ON"))
        if step.dryer != "UNCHANGED":
            output_commands.append((8, step.dryer == "ON"))
        for number, output_state in output_commands:
            if self._cancel_requested:
                return
            self._emit(
                "OUTPUT_INTENT", f"Digital output {number} -> " +
                ("ON" if output_state else "OFF"),
            )
            self._manager.set_digital_output(
                self._id, number, output_state, operator_token=self._owner_token,
            )
        if step.chamber_run != "UNCHANGED":
            if self._cancel_requested:
                return
            requested_running = step.chamber_run == "ON"
            if self._supervised is not None:
                # Physical chambers start once through the certified START path;
                # per-step simulated run toggling is never used. Steps after the
                # first require the chamber to already be running.
                if not self._profile_running:
                    self._emit("RUN_STATE_INTENT", "ON (certified START)")
                    self._manager.start(self._id, operator_token=self._owner_token)
                    self._profile_running = True
            else:
                self._emit("RUN_STATE_INTENT", "ON" if requested_running else "OFF")
                self._manager.set_profile_running(
                    self._id, requested_running, operator_token=self._owner_token,
                )
                self._profile_running = requested_running
        self._reach_deadline = self._now() + self._duration(
            step.reach_timeout_s, "reach", positive=True,
        )
        self._stable_from = self._last_good = None
        self._stable_count = 0
        self._dwell_elapsed = 0.0
        self._transition(RunState.REACHING)

    def notify_supervisor_fault(self, reason: str) -> None:
        """H02-C watchdog alarm: durable STOP intent, UNKNOWN, no replay.

        Callable from the supervision host thread; ``_begin_stop`` is
        idempotent and submits at most one G04 STOP. Device arbitration and
        generation fencing stay with G04.
        """
        text = str(reason).strip() or "watchdog fault"
        if self._watchdog_reason is None:
            self._watchdog_reason = text
        self._begin_stop(RunState.UNKNOWN, "Watchdog fault: " + text)

    def supervision_state(self) -> dict:
        """Bounded monotonic budgets and terminal flag for the watchdog."""
        with self._mutex:
            state = self._state
            if state is None:
                return {"terminal": True, "step_index": 0,
                        "step_remaining_s": 0.0, "whole_remaining_s": 0.0}
            now = self._now()
            return {
                "terminal": state in TERMINAL,
                "stopping": state is RunState.STOP_REQUESTED,
                "step_index": int(self._step_index),
                "step_remaining_s": max(0.0, self._step_deadline - now),
                "whole_remaining_s": max(0.0, self._run_deadline - now),
            }

    def _begin_stop(self, terminal: RunState, reason: str) -> None:
        with self._stop_guard:
            if self._stop_future is not None:
                return
            self._terminal_after_stop = terminal
            self._reason = reason
            self._state = RunState.STOP_REQUESTED
            try:
                self._emit("STOP_INTENT", reason)
            except Exception:
                # A recorder failure does not suppress simulated STOP.
                self._terminal_after_stop = RunState.UNKNOWN
                self._reason = "Event recorder failed before STOP"
            self._stop_future = self._stop_executor.submit(self._manager.stop, self._id)

    def _finish_stop(self) -> None:
        future = self._stop_future
        if future is None or not future.done():
            return
        try:
            future.result()  # G04 verifies authoritative stopped readback
        except Exception as exc:
            self._reason = "STOP unverified: " + type(exc).__name__
            self._terminal_after_stop = RunState.UNKNOWN
        self._state = self._terminal_after_stop
        if self._owner_token is not None:
            try:
                self._manager.release_operator(self._id, self._owner_token)
            except Exception:
                self._state = RunState.UNKNOWN
                self._reason = "Operator lease release unverified"
            self._owner_token = None
        try:
            self._emit("TERMINAL", self._reason)
        except Exception:
            self._state = RunState.UNKNOWN
            self._reason = "Terminal event recording failed"

    def _sample_fresh(self, sample) -> bool:
        timestamp = sample.sampled_at_utc
        if timestamp is None or timestamp.tzinfo is None:
            return False
        age = (datetime.now(timezone.utc) - timestamp).total_seconds()
        assert self._snapshot is not None
        return -1 <= age <= self._snapshot.parameters.max_age_s

    def _accept_setpoint(self, observed: float | None, target: float) -> bool:
        """Supervise independently observed setpoint readback during a ramp.

        A physical chamber may report an intermediate setpoint while it ramps
        toward the commanded target, so the readback is not required to equal
        the target immediately. It must however keep converging: a readback
        that moves away from the target (beyond readback noise) or that stays
        frozen short of the target for consecutive fresh samples fails closed.
        Returns True only when the observed setpoint has settled at the target;
        step qualification additionally requires that convergence.
        """
        if observed is None or not math.isfinite(observed):
            raise ChamberSafetyError("Setpoint readback unavailable")
        distance = abs(observed - target)
        if distance <= 0.1:
            self._setpoint_best = 0.0
            self._setpoint_observed = observed
            self._setpoint_frozen = 0
            self._setpoint_progress_at = self._now()
            return True
        assert self._snapshot is not None
        step = self._step()
        rate = (step.ramp_up_c_per_min if target > observed
                else step.ramp_down_c_per_min)
        # Scale the contraction threshold to how far the declared gradient
        # moves the readback per poll; a fixed 0.02 °C would fault slow ramps.
        per_poll = (float(rate) / 60.0 * self._snapshot.parameters.poll_s
                    if rate is not None else 0.0)
        noise = max(0.02, per_poll * 0.4)
        away = max(0.2, per_poll * 2.5)
        moved = (self._setpoint_observed is not None and
                 abs(observed - self._setpoint_observed) > noise)
        improved = distance < self._setpoint_best - noise
        if moved or improved:
            self._setpoint_progress_at = self._now()
            self._setpoint_frozen = 0
        else:
            self._setpoint_frozen += 1
        self._setpoint_observed = observed
        if distance > self._setpoint_best + away:
            raise ChamberSafetyError("Setpoint readback moved away from target")
        if rate is None:
            # No declared gradient: an unchanged setpoint is frozen, as before.
            if self._setpoint_frozen >= 3:
                raise ChamberSafetyError("Setpoint readback frozen before target")
        elif self._setpoint_frozen:
            remaining_s = distance / (float(rate) / 60.0)
            stall_s = max(30.0, min(600.0, remaining_s * 0.5 + 10.0))
            if (self._setpoint_progress_at is not None and
                    self._now() - self._setpoint_progress_at > stall_s):
                raise ChamberSafetyError("Setpoint readback frozen before target")
        self._setpoint_best = min(self._setpoint_best, distance)
        return False

    def _observe(self) -> None:
        assert self._snapshot is not None
        self._healthy(running=self._profile_running)
        sample = self._manager.status(self._id)  # G04 owns serialized I/O
        now = self._now()
        if now > self._step_deadline or now > self._run_deadline:
            raise TimeoutError("Step/run deadline expired during poll")
        self._healthy(running=self._profile_running)
        expected_operation = (OperationState.RUNNING if self._profile_running
                              else OperationState.STOPPED)
        if (sample.identity != self._snapshot.identity or
                sample.quality is not ReadingQuality.GOOD or
                not self._sample_fresh(sample) or
                sample.operation_state is not expected_operation or
                sample.measured_temperature_c is None or
                not math.isfinite(sample.measured_temperature_c) or
                sample.setpoint_temperature_c is None or
                not math.isfinite(sample.setpoint_temperature_c)):
            raise ChamberSafetyError("Telemetry quality/identity/state invalid")
        step = self._step()
        target = float(step.target_temperature_c)
        setpoint_settled = self._accept_setpoint(sample.setpoint_temperature_c, target)
        finite_temperature(sample.measured_temperature_c,
                           self._snapshot.capabilities.temperature_min_c,
                           self._snapshot.capabilities.temperature_max_c)
        self._emit("SAMPLE", temperature=sample.measured_temperature_c,
                   quality=sample.quality,
                   source_sampled_at_utc=sample.sampled_at_utc,
                   setpoint=sample.setpoint_temperature_c)
        source_time = sample.sampled_at_utc
        assert source_time is not None
        if self._last_source_timestamp is not None:
            if source_time < self._last_source_timestamp:
                raise ChamberSafetyError("Telemetry source timestamp moved backwards")
            if source_time == self._last_source_timestamp:
                return  # Cached reading cannot become a second observation.
        self._last_source_timestamp = source_time
        # No extrapolation or credit for duplicate timestamps/sparse polls.
        gap = None if self._last_good is None else now - self._last_good
        if gap is not None and gap < 0:
            raise ChamberSafetyError("Clock moved backwards")
        if gap is not None and gap > self._snapshot.parameters.max_gap_s:
            self._stable_from = None
            self._stable_count = 0
            self._dwell_elapsed = 0.0
            if self._state is RunState.DWELLING:
                self._transition(RunState.REACHING, "Observation gap reset dwell")
        # A step qualifies only once the observed setpoint has settled at the
        # target; a mid-ramp readback keeps the run in REACHING without credit.
        in_band = (setpoint_settled and
                   abs(sample.measured_temperature_c - target) <= float(step.tolerance_c))
        if not in_band:
            self._stable_from = None
            self._stable_count = 0
            self._dwell_elapsed = 0.0
            self._last_good = now
            if self._state is not RunState.REACHING:
                self._transition(RunState.REACHING, "Out-of-band resets stabilization and dwell")
            return
        if self._state is RunState.REACHING:
            if now > self._reach_deadline:
                raise TimeoutError("Target reach deadline exceeded")
            self._stable_from = now
            self._stable_count = 1
            self._last_good = now
            if float(step.stabilize_s) == 0:
                self._transition(RunState.DWELLING)
                if float(step.dwell_s) == 0:
                    self._complete_step()
            else:
                self._transition(RunState.STABILIZING)
            return
        if self._state is RunState.STABILIZING:
            if self._stable_from is None:
                self._stable_from = now
                self._stable_count = 1
            elif gap is not None and gap > 0:
                self._stable_count += 1
            self._last_good = now
            if (self._stable_count >= 2 and
                    now - self._stable_from >= float(step.stabilize_s)):
                self._transition(RunState.DWELLING)
                if float(step.dwell_s) == 0:
                    self._complete_step()
            return
        if self._state is RunState.DWELLING:
            if gap is not None and 0 < gap <= self._snapshot.parameters.max_gap_s:
                self._dwell_elapsed += gap
            self._last_good = now
            if self._dwell_elapsed >= float(step.dwell_s):
                self._complete_step()

    def _complete_step(self) -> None:
        self._emit("STEP_COMPLETED", str(self._step_index + 1))
        self._step_index += 1
        if self._step_index == len(self._steps()):
            self._begin_stop(RunState.COMPLETED, "All steps complete; verified STOP required")
        else:
            assert self._snapshot is not None
            # Publish the new step index and its fresh deadline together under
            # _mutex. The independent watchdog may then allow the budget reset
            # exactly once, when it observes the index change.
            self._step_started = self._now()
            self._step_deadline = (
                self._step_started + self._step_budget(
                    self._step(), self._snapshot.parameters,
                )
            )
            self._transition(RunState.TRANSITIONING)

    def advance(self) -> RunState | None:
        """One synchronous tick, suitable for deterministic tests or to_thread."""
        with self._advance_lock, self._mutex:
            if self._state is None or self._state in TERMINAL:
                return self._state
            if self._stop_future is not None:
                self._finish_stop()
                return self._state
            if self._cancel_requested:
                self._begin_stop(RunState.CANCELLED, "Operator cancellation")
                return self._state
            if self._watchdog_reason is not None and self._stop_future is None:
                self._begin_stop(
                    RunState.UNKNOWN, "Watchdog fault: " + self._watchdog_reason,
                )
                return self._state
            if (self._supervised is not None and
                    self._supervised.supervisor_alive is not None and
                    self._stop_future is None and
                    not self._supervised.supervisor_alive()):
                if self._watchdog_reason is None:
                    self._watchdog_reason = "Supervisor heartbeat lost"
                self._begin_stop(
                    RunState.UNKNOWN, "Watchdog fault: " + self._watchdog_reason,
                )
                return self._state
            if (self._supervised is not None and self._stop_future is None and
                    self._state is not None and self._state not in TERMINAL):
                try:
                    self._supervised.revalidate()
                except Exception as exc:
                    self._begin_stop(
                        RunState.UNKNOWN,
                        "Supervised permit revalidation failed: " + type(exc).__name__,
                    )
                    return self._state
            now = self._now()
            if now > self._run_deadline:
                self._begin_stop(RunState.FAULT, "Whole-run watchdog exceeded")
                return self._state
            if (self._state not in (RunState.PREPARING,) and
                    now > self._step_deadline):
                self._begin_stop(RunState.FAULT, "Whole-step watchdog exceeded")
                return self._state
            try:
                if self._state in (RunState.PREPARING, RunState.TRANSITIONING):
                    self._dispatch_step()
                elif self._state is RunState.PAUSED:
                    self._healthy(running=self._profile_running)
                    sample = self._manager.status(self._id)
                    self._healthy(running=self._profile_running)
                    expected_operation = (OperationState.RUNNING if self._profile_running
                                          else OperationState.STOPPED)
                    if (sample.quality is not ReadingQuality.GOOD or
                            not self._sample_fresh(sample) or
                            sample.identity != self._snapshot.identity or
                            sample.operation_state is not expected_operation or
                            sample.measured_temperature_c is None):
                        raise ChamberSafetyError("Telemetry invalid while paused")
                    self._accept_setpoint(
                        sample.setpoint_temperature_c,
                        float(self._step().target_temperature_c),
                    )
                    finite_temperature(
                        sample.measured_temperature_c,
                        self._snapshot.capabilities.temperature_min_c,
                        self._snapshot.capabilities.temperature_max_c,
                    )
                elif self._state in (RunState.REACHING, RunState.STABILIZING, RunState.DWELLING):
                    self._observe()
                    if (self._state in (RunState.REACHING, RunState.STABILIZING)
                            and self._now() > self._reach_deadline
                            and self._state is RunState.REACHING):
                        raise TimeoutError("Target reach deadline exceeded")
            except TimeoutError as exc:
                self._begin_stop(RunState.FAULT, str(exc))
            except Exception as exc:
                self._begin_stop(RunState.UNKNOWN, "Controller/telemetry/recording uncertainty: " +
                                 type(exc).__name__)
            if self._cancel_requested and self._stop_future is None:
                self._begin_stop(RunState.CANCELLED, "Operator cancellation")
            return self._state

    async def advance_async(self) -> RunState | None:
        return await asyncio.to_thread(self.advance)

    async def run_until_terminal(self) -> RunState:
        """Run off NiceGUI event loop; no busy polling or browser state owner."""
        while True:
            state = await self.advance_async()
            if state in TERMINAL:
                return state
            if state is None:
                raise ChamberSafetyError("No prepared execution")
            assert self._snapshot is not None
            await asyncio.sleep(self._snapshot.parameters.poll_s)

    def pause(self, chamber_id: str) -> None:
        self._check_action(chamber_id, "profile.pause", require_owner=True)
        with self._mutex:
            if self._state not in (RunState.REACHING, RunState.STABILIZING, RunState.DWELLING):
                raise ChamberSafetyError("Pause only during running observation stages")
            # A logical observation pause ONLY. Chamber continues its setpoint.
            # Absolute watchdogs remain active; dwell/stabilization reset.
            self._last_good = self._stable_from = None
            self._stable_count = 0
            self._dwell_elapsed = 0.0
            self._transition(RunState.PAUSED, "Logical pause; chamber retains commanded run state")

    async def pause_async(self, chamber_id: str) -> None:
        await asyncio.to_thread(self.pause, chamber_id)

    def resume(self, chamber_id: str) -> None:
        self._check_action(chamber_id, "profile.resume", require_owner=True)
        with self._mutex:
            if self._state is not RunState.PAUSED:
                raise ChamberSafetyError("Run is not paused")
            # OFF/UNCHANGED steps may be paused while the chamber is STOPPED.
            # Verify the commanded state instead of unconditionally demanding RUNNING.
            self._healthy(running=self._profile_running)
            self._reach_deadline = min(
                self._step_deadline, self._now() +
                self._duration(self._step().reach_timeout_s, "reach", positive=True),
            )
            self._transition(RunState.REACHING, "Qualification restarted after pause")

    async def resume_async(self, chamber_id: str) -> None:
        await asyncio.to_thread(self.resume, chamber_id)

    def _check_action(self, chamber_id: str, action: str, *,
                      require_owner: bool = False) -> None:
        validate_chamber_id(chamber_id)
        if chamber_id != self._id:
            raise ChamberSafetyError("Wrong chamber for profile action")
        principal = self._permission(action)
        if require_owner and (self._snapshot is None or
                              principal != self._snapshot.operator_id):
            raise ChamberSafetyError("Pause/resume reserved for current operator")

    def cancel(self, chamber_id: str) -> None:
        """Fence STOP even if advance() is blocked on G04 synchronous I/O.

        Cancellation deliberately does not acquire the advance mutex. A device
        call already in flight cannot be preempted; G04 invalidates queued writes.
        """
        self._check_action(chamber_id, "profile.cancel")
        if not self._prepared or self._state is None or self._state in TERMINAL:
            raise ChamberSafetyError("No fully prepared active run")
        self._cancel_requested = True
        self._begin_stop(RunState.CANCELLED, "Operator cancellation")

    async def cancel_async(self, chamber_id: str) -> None:
        await asyncio.to_thread(self.cancel, chamber_id)

    def request_shutdown_stop(self, chamber_id: str) -> None:
        """Trusted server shutdown path with one durable STOP owner.

        Browser cancellation remains authorized through ``cancel``. During
        process shutdown there is no browser principal, but the active runner
        must still own STOP intent and terminal evidence; issuing a second
        direct controller STOP races its generation fence.
        """
        validate_chamber_id(chamber_id)
        if chamber_id != self._id:
            raise ChamberSafetyError("Wrong chamber for profile shutdown")
        if not self._prepared or self._state is None or self._state in TERMINAL:
            return
        self._cancel_requested = True
        self._begin_stop(RunState.CANCELLED, "Server shutdown")

    def close(self) -> None:
        """Only after terminal. Never detach a still-active STOP worker."""
        with self._mutex:
            if self._state is not None and self._state not in TERMINAL:
                raise ChamberSafetyError("Cannot close a running execution")
            self._closed = True
        self._stop_executor.shutdown(wait=True)
