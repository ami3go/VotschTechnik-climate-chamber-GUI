"""G05 server-owned manual control. Only G04 performs simulated device I/O.

No NiceGUI, vendor adapter or external device driver imports. Every mutation
uses the G08-min AuthorizedChamber guard, audited intent and G04 fencing.
Physical operation is unconditionally excluded, including test configuration.
"""
from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from chamber_web.domain.chamber import (
    ChamberProtocolError, ChamberSafetyError, ChamberSnapshot, OperationState, ReadingQuality,
    finite_temperature, validate_chamber_id,
)
from chamber_web.security.auth import SecurityStore
from chamber_web.security.guards import AuthorizedChamber, Permission
from chamber_web.services.chamber_manager import ChamberManager
from chamber_web.services.dashboard import DashboardService, DashboardView


class ManualState(str, Enum):
    IDLE = "IDLE"
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"
    FAULT = "FAULT"
    STOP_REQUESTED = "STOP_REQUESTED"


@dataclass(frozen=True)
class CommandOutcome:
    action: str
    state: ManualState
    message: str
    generation: int
    timestamp_utc: datetime


@dataclass(frozen=True)
class ManualView:
    dashboard: DashboardView
    controller_state: str
    connected: bool
    controller_generation: int
    stop_latched: bool
    owner: str | None
    owned_by_actor: bool
    can_set_target: bool
    can_start: bool
    can_stop: bool
    can_handover: bool
    can_reconcile: bool
    presets_c: tuple[float, ...]
    last_command: CommandOutcome | None


class ManualControlService:
    """Per-server single-chamber facade, shared between all browser sessions.

    G04 serializes device I/O and owns the durable controller generation. The
    latest outcome is informational, not authority for subsequent operations.
    STOP is never blocked on this service's result lock or the operator lease.
    """

    def __init__(self, manager: ChamberManager, dashboard: DashboardService,
                 authorized: AuthorizedChamber, security: SecurityStore,
                 chamber_id: str, *, max_sample_age_s: float = 5.0,
                 physical_hil=None):
        self.chamber_id = validate_chamber_id(chamber_id)
        if physical_hil is not None and physical_hil.chamber_id != self.chamber_id:
            raise ChamberSafetyError("HIL authorization is for a different chamber")
        # Explicit launch-time supervised HIL authorization; None = simulation only.
        self._hil = physical_hil
        if manager.configured_ids() != (self.chamber_id,) or dashboard.chamber_id != self.chamber_id:
            raise ChamberSafetyError("Manual service wrong device identity")
        if not 0 < max_sample_age_s <= 60 or not math.isfinite(max_sample_age_s):
            raise ValueError("Invalid telemetry age")
        self._manager = manager
        self._dashboard = dashboard
        self._authorized = authorized
        self._security = security
        self._max_age = max_sample_age_s
        self._lock = threading.Lock()
        self._serial = 0
        self._pending_stop_serial: int | None = None
        self._last: CommandOutcome | None = None

    def _check_id(self, chamber_id: str) -> None:
        self._manager.get(chamber_id)
        if chamber_id != self.chamber_id:
            raise ChamberSafetyError("Wrong chamber")

    def _controllable(self, identity) -> bool:
        """A simulator, or exactly the HIL-authorized physical chamber."""
        if identity is None or identity.chamber_id != self.chamber_id:
            return False
        if identity.is_simulation:
            return self._hil is None
        return (self._hil is not None and identity.backend_id == "votsch" and
                identity.serial_number == self._hil.expected_serial)

    def _require_mock(self, identity) -> None:
        if not self._controllable(identity):
            raise ChamberSafetyError("Physical equipment is disabled without HIL authorization")

    def view(self, session: str | None, chamber_id: str) -> ManualView:
        """Read-only cached telemetry; passive timer reads never renew sessions."""
        self._check_id(chamber_id)
        actor = self._security.authenticate(session, touch=False)
        from chamber_web.security.guards import require_permission
        require_permission(actor, Permission.READ)
        dashboard = self._dashboard.view()
        health = self._manager.health(chamber_id)
        owner, mine = self._authorized.ownership_view(session, chamber_id)
        simulator = self._controllable(dashboard.identity)
        good = simulator and dashboard.quality is ReadingQuality.GOOD and health.connected
        if not simulator:
            # Do not display a live identity as controllable or confirmed.
            good = False
        caps = dashboard.capabilities
        bounded = bool(caps and math.isfinite(caps.temperature_min_c) and
                       math.isfinite(caps.temperature_max_c) and
                       caps.temperature_min_c < caps.temperature_max_c)
        has_temperature = bool(bounded and caps.supports_setpoint_readback)
        has_operation = bool(caps and caps.supports_start_stop and caps.supports_running_readback)
        target = dashboard.setpoint_temperature_c
        has_valid_target = bool(
            bounded and target is not None and math.isfinite(target) and
            caps.temperature_min_c <= target <= caps.temperature_max_c)
        from chamber_web.security.auth import Role
        allowed = actor.role in (Role.ADMIN, Role.OPERATOR)
        presets = (tuple(t for t in (0.0, 23.0, 40.0)
                         if caps.temperature_min_c <= t <= caps.temperature_max_c)
                   if bounded and simulator else ())
        with self._lock:
            last = self._last
        return ManualView(
            dashboard, health.state, health.connected, health.generation, health.stop_latched,
            owner, mine,
            allowed and good and mine and not health.stop_latched and
            health.state in ("VERIFIED_STOPPED", "RUNNING") and
            has_temperature,
            allowed and good and mine and not health.stop_latched and
            health.state in ("VERIFIED_STOPPED", "RUNNING") and
            has_temperature and has_operation and has_valid_target,
            allowed,  # STOP is always offered to an authorized user, even on stale data
            actor.role is Role.ADMIN and owner is not None and not mine,
            actor.role is Role.ADMIN and health.stop_latched,
            presets, last,
        )

    def _await_ramped_setpoint(self, chamber_id: str, target: float,
                               ramp: tuple[float, float], origin: float | None):
        """Fresh G04 reads (STOP can interleave) until a device ramp reaches target."""
        from chamber_web.domain.chamber import ChamberProtocolError, ChamberTimeoutError

        if origin is None or not math.isfinite(origin):
            raise ChamberProtocolError("No verified setpoint before ramped write")
        rate = ramp[0] if target >= origin else ramp[1]
        budget = min(300.0, abs(target - origin) / rate * 60.0 * 1.5 + 15.0)
        deadline = time.monotonic() + budget
        # A ramp toward a WRONG goal passes through the target, so convergence
        # also requires the readback to have stopped moving: a second read,
        # spaced so the slowest configured ramp would move >= 0.05 °C.
        settle_s = min(30.0, max(1.0, 0.05 * 60.0 / min(ramp)))
        best = math.inf
        candidate = None
        while True:
            verified, _ = self._fresh(chamber_id)
            readback = verified.setpoint_temperature_c
            if readback is None or not math.isfinite(readback):
                raise ChamberProtocolError("Setpoint readback unavailable during ramp")
            distance = abs(readback - target)
            now = time.monotonic()
            if distance <= 0.1:
                if candidate is None:
                    candidate = (readback, now)
                elif abs(readback - candidate[0]) > 0.02:
                    candidate = (readback, now)  # still moving: restart settle window
                elif now - candidate[1] >= settle_s:
                    return verified
            else:
                candidate = None
            if distance > best + 0.2:
                raise ChamberProtocolError("Setpoint ramp moving away from target")
            best = min(best, distance)
            if now >= deadline + settle_s:
                raise ChamberTimeoutError("Setpoint ramp did not reach target in time")
            time.sleep(0.25 if candidate is not None else 0.5)

    def _fresh(self, chamber_id: str) -> tuple[ChamberSnapshot, object]:
        """A new G04 worker read, never a browser/Dashboard cached sample."""
        self._check_id(chamber_id)
        status = self._manager.status(chamber_id)
        self._require_mock(status.identity)
        health = self._manager.health(chamber_id)
        if not health.connected or health.stop_latched or health.state not in (
            "VERIFIED_STOPPED", "RUNNING"
        ):
            raise ChamberSafetyError("STOP/UNKNOWN/restart reconciliation is required")
        if status.quality is not ReadingQuality.GOOD or status.operation_state not in (
            OperationState.STOPPED, OperationState.RUNNING
        ):
            raise ChamberSafetyError("Authoritative device status unavailable")
        sampled = status.sampled_at_utc
        if sampled is None or sampled.tzinfo is None or not (
            -1 <= (datetime.now(timezone.utc) -
                    sampled.astimezone(timezone.utc)).total_seconds() <= self._max_age
        ):
            raise ChamberSafetyError("Authoritative readback stale")
        if status.measured_temperature_c is None or not math.isfinite(
            status.measured_temperature_c
        ):
            raise ChamberSafetyError("Invalid chamber measurement")
        caps = self._manager.capabilities(chamber_id)
        if not (math.isfinite(caps.temperature_min_c) and
                math.isfinite(caps.temperature_max_c) and
                caps.temperature_min_c < caps.temperature_max_c):
            raise ChamberSafetyError("Unverified temperature capability range")
        return status, caps

    def _begin(self, action: str) -> int:
        generation = self._manager.health(self.chamber_id).generation
        with self._lock:
            self._serial += 1
            serial = self._serial
            if action == "stop":
                self._pending_stop_serial = serial
                self._last = CommandOutcome(
                    action, ManualState.STOP_REQUESTED,
                    "Awaiting verified device response",
                    generation, datetime.now(timezone.utc))
            elif self._pending_stop_serial is None:
                # A later rejected attempt must not hide an in-flight STOP.
                self._last = CommandOutcome(
                    action, ManualState.PENDING,
                    "Awaiting verified device response",
                    generation, datetime.now(timezone.utc))
            return serial

    def _finish(self, serial: int, action: str, state: ManualState,
                message: str) -> CommandOutcome:
        result = CommandOutcome(action, state, message,
                                self._manager.health(self.chamber_id).generation,
                                datetime.now(timezone.utc))
        with self._lock:
            # STOP stays visible until the newest STOP has actually concluded,
            # even if another denied START/setpoint was attempted meanwhile.
            if action == "stop" and serial == self._pending_stop_serial:
                self._pending_stop_serial = None
                self._last = result
                return result
            if self._pending_stop_serial is None and serial == self._serial:
                self._last = result
                return result
            if state is ManualState.CONFIRMED:
                # A superseded callback may never announce success to its page.
                return CommandOutcome(
                    action, ManualState.UNKNOWN,
                    "Superseded by a newer command; result is not authoritative",
                    result.generation, result.timestamp_utc)
        return result

    def _error_state(self, error: Exception) -> ManualState:
        from chamber_web.domain.chamber import (
            ChamberConnectionError, ChamberProtocolError, ChamberTimeoutError,
        )
        health = self._manager.health(self.chamber_id)
        if health.state == "FAULT":
            return ManualState.FAULT
        if health.state in ("UNKNOWN", "STOP_REQUESTED") or isinstance(
            error, (ChamberConnectionError, ChamberProtocolError, ChamberTimeoutError)
        ):
            return ManualState.UNKNOWN
        return ManualState.REJECTED

    def command(self, session: str | None, csrf: str | None, chamber_id: str,
                action: str, *, target_c: float | None = None) -> CommandOutcome:
        """Only explicitly enumerated commands are possible; no generic dispatch."""
        permissions = {
            "claim": Permission.CHAMBER_CONTROL,
            "release": Permission.CHAMBER_CONTROL,
            "set_temperature": Permission.CHAMBER_CONTROL,
            "start": Permission.CHAMBER_CONTROL,
            "stop": Permission.STOP,
            "handover": Permission.SETTINGS,
            "reconcile": Permission.RECONCILE,
        }
        if action not in permissions:
            raise ChamberSafetyError("Unsupported manual operation")
        # Authenticate before reading equipment or changing UI-visible command state.
        actor = self._authorized.authorize(
            session, csrf, permissions[action], chamber_id=chamber_id)
        self._check_id(chamber_id)
        serial = self._begin(action)
        command_may_have_dispatched = False
        try:
            if action == "stop":
                # No pre-read, no ownership checks, no service-level lock.
                command_may_have_dispatched = True
                self._authorized.stop(session, csrf, chamber_id)
                sample = self._manager.status(chamber_id)
                self._require_mock(sample.identity)
                sampled = sample.sampled_at_utc
                age = ((datetime.now(timezone.utc) - sampled.astimezone(timezone.utc))
                       .total_seconds() if sampled is not None and
                       sampled.tzinfo is not None else float("inf"))
                health = self._manager.health(chamber_id)
                if (sample.quality is not ReadingQuality.GOOD or
                        sample.operation_state is not OperationState.STOPPED or
                        not (-1 <= age <= self._max_age) or
                        not health.connected or health.state != "VERIFIED_STOPPED"):
                    raise ChamberSafetyError("STOP not confirmed by fresh readback")
            elif action == "claim":
                sample, _ = self._fresh(chamber_id)
                self._authorized.execute(session, csrf, chamber_id, "claim_operator")
            elif action == "release":
                command_may_have_dispatched = True
                self._authorized.execute_owned(session, csrf, chamber_id, "release_operator")
            elif action == "handover":
                command_may_have_dispatched = True
                self._authorized.handover_to_admin(session, csrf, chamber_id)
            elif action == "reconcile":
                command_may_have_dispatched = True
                self._authorized.execute(session, csrf, chamber_id, "reconcile_stop")
            else:
                sample, caps = self._fresh(chamber_id)
                admitted_generation = self._manager.health(chamber_id).generation
                if action == "start":
                    if not (caps.supports_start_stop and caps.supports_running_readback and
                            caps.supports_setpoint_readback):
                        raise ChamberSafetyError("START/readback capability unsupported")
                    if sample.setpoint_temperature_c is None:
                        raise ChamberSafetyError("No verified target temperature")
                    finite_temperature(sample.setpoint_temperature_c,
                                       caps.temperature_min_c, caps.temperature_max_c)
                    command_may_have_dispatched = True
                    self._authorized.execute_owned(session, csrf, chamber_id, "start")
                elif action == "set_temperature":
                    if not caps.supports_setpoint_readback:
                        raise ChamberSafetyError("Setpoint readback unsupported")
                    # Explicit finite validation; never coerce browser text/boolean.
                    target = finite_temperature(
                        target_c, caps.temperature_min_c, caps.temperature_max_c)
                    command_may_have_dispatched = True
                    self._authorized.execute_owned(
                        session, csrf, chamber_id, "set_temperature", target)
                ramp = caps.setpoint_readback_ramp_c_per_min
                if action == "set_temperature" and ramp:
                    verified = self._await_ramped_setpoint(
                        chamber_id, target, ramp, sample.setpoint_temperature_c)
                else:
                    verified, _ = self._fresh(chamber_id)  # independent authoritative readback
                if action == "start" and verified.operation_state is not OperationState.RUNNING:
                    raise ChamberProtocolError("Follow-up START readback disagrees")
                if action == "set_temperature" and (
                    verified.setpoint_temperature_c is None or
                    not math.isfinite(verified.setpoint_temperature_c) or
                    abs(verified.setpoint_temperature_c - target) > 0.1
                ):
                    raise ChamberProtocolError("Follow-up setpoint readback disagrees")
                completion = self._manager.health(chamber_id)
                if (completion.generation != admitted_generation or
                        completion.stop_latched or completion.state not in (
                            "VERIFIED_STOPPED", "RUNNING")):
                    raise ChamberSafetyError(
                        "Command superseded by a newer STOP/FAULT generation")
            return self._finish(serial, action, ManualState.CONFIRMED,
                                ("Confirmed by authoritative physical device readback"
                                 if self._hil is not None else
                                 "Confirmed by simulated authoritative device readback")
                                if action in ("start", "set_temperature", "stop", "reconcile")
                                else "Server operator-lease transition confirmed")
        except Exception as exc:
            state = self._error_state(exc)
            from chamber_web.security.auth import AuthenticationError, AuthorizationError
            if (command_may_have_dispatched and state is ManualState.REJECTED and
                    not isinstance(exc, (AuthenticationError, AuthorizationError))):
                # An accepted write or lease transition can have occurred before
                # a later status/readback/audit failure. Never call it refused.
                state = ManualState.UNKNOWN
            self._security.audit(actor, "manual." + action, state.value,
                                 chamber_id, type(exc).__name__)
            return self._finish(
                serial, action, state,
                "Command refused or unverified: " + type(exc).__name__ +
                (". Device state is not guaranteed." if state in (
                    ManualState.UNKNOWN, ManualState.FAULT) else ""))

    def unsupported_operation(self, session: str | None, csrf: str | None,
                              chamber_id: str, kind: str) -> None:
        """No ramp/gradient/mode/manual-profile mutation exists in G05."""
        actor = self._authorized.authorize(
            session, csrf, Permission.CHAMBER_CONTROL, chamber_id=chamber_id)
        self._check_id(chamber_id)
        self._security.audit(actor, "manual.unsupported", "DENIED", chamber_id, str(kind)[:60])
        raise ChamberSafetyError("Ramp, gradient and operating-mode writes are disabled")
