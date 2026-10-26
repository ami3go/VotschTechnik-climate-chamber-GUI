"""Unattended full-range HIL acceptance for ONE Vötsch chamber (isolated lab).

Runs without operator interaction through the same G04/G05/G06/G07/G08
composition the web server uses, in isolated-lab mode:

    CHAMBER_HIL_ADDRESS=192.168.0.11 CHAMBER_HIL_EXPECTED_SERIAL=58566207770010 \\
    CHAMBER_HIL_TEMP_MIN_C=-40 CHAMBER_HIL_TEMP_MAX_C=130 \\
    CHAMBER_HIL_ACK=SUPERVISED-PHYSICAL-HIL CHAMBER_LAB_MODE=ISOLATED-LAB-UNATTENDED \\
    python scripts/hil_lab_acceptance.py --evidence hil-evidence/lab-$(date +%F)

Phases (each ends with a verified STOP before the next one starts):

  identity   identity/serial, envelope, gradients, telemetry freshness/latency
  guards     out-of-envelope setpoints and lease-less commands are refused
  manual     manual set/start across a large step, long-ramp confirmation, STOP
  cancel     profile toward an envelope edge, cancelled mid-ramp, verified STOP
  profile    full-range profile: max -> min -> start temperature, with dwell
  gradient   profile with declared gradients; verifies gradient readback and slope
  web        real server process in lab mode answers HTTP with the lab title

Before anything moves, the chamber must be STOPPED with the expected serial.
Afterwards the chamber is STOPPED and its original setpoint and gradients are
restored over an independent driver connection, whatever happened. SIGINT or
SIGTERM cancels the active run and goes straight to that cleanup.

``--simulate`` runs every phase against an in-process VT 4011 simulator
(scripts/vt4011_simulator.py) through the real Vötsch adapter; use it to
validate the script and the server stack without a chamber.

Evidence: timeline.jsonl, samples.jsonl, runs/ (G07 journal), summary.json,
summary.md. Exit code 0 only if every selected phase passed.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chamber_web.domain.chamber import OperationState, ReadingQuality  # noqa: E402
from chamber_web.hil.lab_mode import LabMode, lab_mode_from_env  # noqa: E402
from chamber_web.hil.physical import HilAuthorization, hil_authorization_from_env  # noqa: E402

ADMIN = ("lab_admin", "StrongLabAdminPassword#1")
OPERATOR = ("lab_operator", "StrongLabOperatorPassword#2")
PHASES = ("identity", "guards", "manual", "cancel", "profile", "gradient", "web")
SAMPLE_LOG_S = 10.0


def console(text: str) -> None:
    """Best-effort console output; a closed terminal/pipe must never stop cleanup."""
    try:
        print(text, flush=True)
    except (OSError, ValueError):
        pass


class Abort(RuntimeError):
    """Stop all remaining phases (signal, deadline or unverified STOP)."""


class PhaseFailed(AssertionError):
    pass


def check(condition: bool, message: str) -> None:
    if not condition:
        raise PhaseFailed(message)


@dataclass
class Settings:
    targets: list[float]
    dwell_s: float
    stabilize_s: float
    tolerance_c: float
    settle_s: float
    manual_delta_c: float
    manual_hold_s: float
    gradient_c_per_min: float
    gradient_delta_c: float
    cancel_after_s: float
    poll_s: float = 2.0


@dataclass
class PhaseResult:
    name: str
    status: str = "SKIPPED"
    seconds: float = 0.0
    detail: str = ""
    data: dict = field(default_factory=dict)


def ramp_seconds(start: float, target: float, gradients: tuple[float, float]) -> float:
    rate = gradients[0] if target >= start else gradients[1]
    return abs(target - start) / rate * 60.0


class LabAcceptance:
    def __init__(self, hil: HilAuthorization, lab: LabMode, evidence: Path,
                 settings: Settings, *, deadline_s: float, driver_factory=None,
                 web_port: int | None = None):
        self.hil, self.lab, self.settings = hil, lab, settings
        self.evidence = evidence
        evidence.mkdir(parents=True, exist_ok=True)
        self.driver_factory = driver_factory
        self.web_port = web_port
        self.t0 = time.monotonic()
        self.deadline = self.t0 + deadline_s
        self.stop_requested = threading.Event()
        self.results: list[PhaseResult] = []
        self.original: dict = {}
        self.connected = False
        self.measured: list[float] = []
        self._last_sample_log = 0.0

    # -- evidence -------------------------------------------------------------
    def log(self, event: str, **data) -> None:
        record = {"t_s": round(time.monotonic() - self.t0, 1),
                  "utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "event": event, **data}
        with open(self.evidence / "timeline.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")
        console(f"[{record['t_s']:8.1f}s] {event} {data if data else ''}")

    def sample(self, phase: str, **data) -> None:
        record = {"t_s": round(time.monotonic() - self.t0, 1), "phase": phase, **data}
        if isinstance(data.get("measured_c"), (int, float)):
            self.measured.append(float(data["measured_c"]))
        with open(self.evidence / "samples.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")
        now = time.monotonic()
        if now - self._last_sample_log >= SAMPLE_LOG_S:
            self._last_sample_log = now
            console(f"[{record['t_s']:8.1f}s]   {phase:<9} " + " ".join(
                f"{k}={v}" for k, v in data.items()))

    def guard_time(self) -> None:
        if self.stop_requested.is_set():
            raise Abort("signal received")
        if time.monotonic() > self.deadline:
            raise Abort("hard deadline reached")

    # -- independent driver connection (never while the stack is connected) ---
    def direct(self):
        if self.driver_factory is not None:
            return self.driver_factory()
        from VotschTechnikClimateChamber import ClimateChamber
        return ClimateChamber(self.hil.address, self.hil.temperature_min_c,
                              self.hil.temperature_max_c, timeout=2)

    def precheck(self) -> None:
        chamber = self.direct()
        try:
            serial = str(chamber.serial_number).strip()
            running = chamber.is_running
            setpoint = _settled_setpoint(chamber)
            self.original = {
                "serial": serial, "running": running, "setpoint_c": setpoint,
                "measured_c": chamber.temperature_measured,
                "gradient_up": float(chamber.gradient_up),
                "gradient_down": float(chamber.gradient_down),
            }
        finally:
            chamber.disconnect()
        self.log("precheck", **self.original)
        if serial != self.hil.expected_serial:
            raise Abort(f"serial {serial!r} does not match CHAMBER_HIL_EXPECTED_SERIAL")
        if running:
            raise Abort("chamber is RUNNING; start only from a stopped chamber")
        if not self.hil.temperature_min_c <= setpoint <= self.hil.temperature_max_c:
            raise Abort("chamber setpoint is outside the software envelope")

    def postcheck(self) -> None:
        if not self.original:
            return
        chamber = self.direct()
        try:
            if chamber.is_running:
                self.log("postcheck_running_direct_stop")
                chamber.stop()
            for name in ("gradient_up", "gradient_down"):
                if abs(float(getattr(chamber, name)) - self.original[name]) > 0.005:
                    try:
                        setattr(chamber, name, self.original[name])
                        self.log("restored_" + name, value=self.original[name])
                    except Exception as exc:  # noqa: BLE001 - report, keep restoring
                        self.log("restore_failed_" + name, error=repr(exc))
            if abs(chamber.temperature_set_point - self.original["setpoint_c"]) > 0.05:
                chamber.temperature_set_point = self.original["setpoint_c"]
                self.log("restored_setpoint", setpoint_c=self.original["setpoint_c"])
            self.log("postcheck", running=chamber.is_running,
                     measured_c=chamber.temperature_measured)
        finally:
            chamber.disconnect()

    # -- service stack (the server's own composition) ---------------------------
    def connect(self) -> None:
        from chamber_web.bootstrap import create_demo_control_services
        from chamber_web.execution.profile_runner import RunParameters
        from chamber_web.persistence.profiles import ProfileStore
        from chamber_web.security.auth import Role, SecurityStore
        from chamber_web.services.profile_execution import ProfileExecutionService
        from chamber_web.services.profile_runtime import ProfileRunRuntime

        work = Path(tempfile.mkdtemp(prefix="hil-lab-"))
        security = SecurityStore(work / "security")
        security.bootstrap_admin(*ADMIN)
        self.admin = security.login(*ADMIN)
        security.create_user(self.admin.session, self.admin.csrf, *OPERATOR, Role.OPERATOR)
        self.operator = security.login(*OPERATOR)
        factory = self.driver_factory
        self.dashboard, self.manual = create_demo_control_services(
            security, self.hil,
            hil_driver_factory=factory,
            # Shared with a live server: both can never control at once.
            lease_directory=Path.home() / ".chamber_web" / "ownership",
            gradient_writes=self.lab.gradients)
        self.connected = True
        self.manager = self.dashboard.manager
        self.chamber_id = self.manual.chamber_id
        self.profiles = ProfileStore(work / "profiles.sqlite3")
        self.journal = ProfileRunRuntime(self.evidence / "runs")
        self.execution = ProfileExecutionService(
            self.manager, self.profiles, security, self.chamber_id, simulation=False,
            sink_factory=self.journal.sink_factory, start_blocker=self.journal.start_blocker,
            parameters=RunParameters(poll_s=self.settings.poll_s),
            manual_guard=self.manual._authorized, lab=self.lab)

    def close(self) -> None:
        if not self.connected:
            return
        try:
            outcome = self.send(self.admin, "stop")
            self.log("final_stop", state=outcome.state.value)
        except Exception as exc:  # noqa: BLE001
            self.log("final_stop_failed", error=repr(exc))
        try:
            runner = self.execution.runner
            if runner is not None:
                runner.close()
        except Exception as exc:  # noqa: BLE001
            self.log("runner_close_failed", error=repr(exc))
        try:
            asyncio.run(self.dashboard.close())
        except Exception as exc:  # noqa: BLE001
            self.log("disconnect_failed", error=repr(exc))
        self.connected = False

    def send(self, tokens, action: str, **kw):
        outcome = self.manual.command(tokens.session, tokens.csrf, self.chamber_id, action, **kw)
        self.log("command", action=action, state=outcome.state.value, message=outcome.message,
                 **({"target_c": kw["target_c"]} if "target_c" in kw else {}))
        return outcome

    def require(self, tokens, action: str, **kw):
        outcome = self.send(tokens, action, **kw)
        check(outcome.state.value == "CONFIRMED",
              f"{action} not confirmed: {outcome.state.value} {outcome.message}")
        return outcome

    def view(self, tokens=None):
        asyncio.run(self.dashboard.poll_once())
        return self.manual.view((tokens or self.admin).session, self.chamber_id)

    def ensure_rearmed(self) -> None:
        view = self.view()
        if view.stop_latched:
            # An uncertain persisted lease connects as UNKNOWN; reconciliation
            # performs its own fresh STOPPED readback before clearing the latch.
            check(view.can_reconcile,
                  f"controller {view.controller_state}; STOP is not verified and "
                  "the administrator cannot reconcile it")
            self.require(self.admin, "reconcile")

    def verify_stopped(self, phase: str) -> None:
        deadline = time.monotonic() + 30
        while True:
            d = self.view().dashboard
            if d.quality is ReadingQuality.GOOD and d.operation_state is OperationState.STOPPED:
                self.log("verified_stopped", phase=phase, measured_c=d.measured_temperature_c)
                return
            if time.monotonic() > deadline:
                raise Abort(f"STOP not verified after {phase}")
            time.sleep(1)

    def release_lease(self) -> None:
        if self.manual.view(self.operator.session, self.chamber_id).owned_by_actor:
            self.send(self.operator, "release")

    @property
    def gradients(self) -> tuple[float, float]:
        caps = self.manager.capabilities(self.chamber_id)
        ramp = caps.setpoint_readback_ramp_c_per_min
        check(bool(ramp), "chamber reports no setpoint ramp")
        return ramp

    # -- phases -----------------------------------------------------------------
    def phase_identity(self, result: PhaseResult) -> None:
        view = self.view()
        identity, caps = view.dashboard.identity, view.dashboard.capabilities
        result.data.update(model=identity.model, serial=identity.serial_number,
                           ramp_c_per_min=caps.setpoint_readback_ramp_c_per_min,
                           envelope_c=(caps.temperature_min_c, caps.temperature_max_c),
                           gradient_writes=caps.supports_ramp_up)
        check(identity.is_simulation is False and identity.backend_id == "votsch",
              "backend is not the physical Vötsch adapter")
        check(identity.serial_number == self.hil.expected_serial, "serial mismatch")
        check((caps.temperature_min_c, caps.temperature_max_c) ==
              (self.hil.temperature_min_c, self.hil.temperature_max_c), "envelope mismatch")
        up, down = caps.setpoint_readback_ramp_c_per_min
        check(0 < up <= 60 and 0 < down <= 60, "invalid chamber gradients")
        check(caps.supports_ramp_up == self.lab.gradients, "gradient capability mismatch")
        latencies = []
        for _ in range(10):
            started = time.monotonic()
            d = self.view().dashboard
            latencies.append(time.monotonic() - started)
            check(d.quality is ReadingQuality.GOOD, f"telemetry {d.quality.value}")
            check(d.operation_state is OperationState.STOPPED, "chamber not STOPPED")
            check(d.measured_temperature_c is not None and
                  math.isfinite(d.measured_temperature_c), "measured temperature invalid")
            time.sleep(0.5)
        result.data["latency_ms_max"] = round(1000 * max(latencies))
        check(max(latencies) < 1.5, "telemetry slower than 1.5 s")
        check(self.view().controller_state == "VERIFIED_STOPPED",
              f"controller {self.view().controller_state}")

    def phase_guards(self, result: PhaseResult) -> None:
        self.require(self.operator, "claim")
        before = self.view().dashboard.setpoint_temperature_c
        for target in (self.hil.temperature_max_c + 5, self.hil.temperature_min_c - 5):
            outcome = self.send(self.operator, "set_temperature", target_c=target)
            check(outcome.state.value != "CONFIRMED", f"out-of-envelope {target} accepted")
        check(abs(self.view().dashboard.setpoint_temperature_c - before) < 0.05,
              "out-of-envelope setpoint reached the chamber")
        outcome = self.send(self.admin, "start")
        check(outcome.state.value != "CONFIRMED", "START without the operator lease accepted")
        check(self.view().dashboard.operation_state is OperationState.STOPPED,
              "chamber started without a lease")
        self.release_lease()

    def _manual_target(self) -> float:
        start = self.original["setpoint_c"]
        delta = self.settings.manual_delta_c
        target = start + delta if start + delta <= self.hil.temperature_max_c else start - delta
        return round(max(self.hil.temperature_min_c, min(self.hil.temperature_max_c, target)), 2)

    def phase_manual(self, result: PhaseResult) -> None:
        self.ensure_rearmed()
        self.require(self.operator, "claim")
        start = self.view().dashboard.setpoint_temperature_c
        target = self._manual_target()
        set_outcome = self.require(self.operator, "set_temperature", target_c=target)
        self.require(self.operator, "start")
        budget = ramp_seconds(start, target, self.gradients) + self.settings.settle_s
        result.data.update(target_c=target, from_c=start, set_message=set_outcome.message,
                           budget_s=round(budget))
        reached = None
        end = time.monotonic() + budget
        while time.monotonic() < end:
            self.guard_time()
            d = self.view().dashboard
            self.sample("manual", measured_c=d.measured_temperature_c,
                        setpoint_c=d.setpoint_temperature_c, state=d.operation_state.value,
                        quality=d.quality.value)
            check(d.quality is ReadingQuality.GOOD, f"telemetry {d.quality.value}")
            check(d.operation_state is OperationState.RUNNING, "chamber stopped unexpectedly")
            if (abs(d.setpoint_temperature_c - target) <= 0.1 and
                    abs(d.measured_temperature_c - target) <= self.settings.tolerance_c):
                reached = time.monotonic()
                break
            time.sleep(self.settings.poll_s)
        check(reached is not None, f"measured temperature did not reach {target} °C "
              f"within {round(budget)} s")
        result.data["reach_s"] = round(reached - (end - budget))
        hold_end = time.monotonic() + self.settings.manual_hold_s
        while time.monotonic() < hold_end:
            self.guard_time()
            d = self.view().dashboard
            check(d.operation_state is OperationState.RUNNING, "chamber stopped during hold")
            time.sleep(self.settings.poll_s)
        self.require(self.operator, "stop")
        self.verify_stopped("manual")
        self.release_lease()

    def _profile(self, name: str, steps: list[dict]):
        from chamber_web.domain.profile import ParsedProfile, ProfileStep

        built = tuple(ProfileStep(
            step=index + 1, enabled=True,
            target_temperature_c=Decimal(str(step["target"])),
            ramp_up_c_per_min=(None if step.get("ramp_up") is None
                               else Decimal(str(step["ramp_up"]))),
            ramp_down_c_per_min=(None if step.get("ramp_down") is None
                                 else Decimal(str(step["ramp_down"]))),
            tolerance_c=Decimal(str(self.settings.tolerance_c)),
            stabilize_s=Decimal(str(int(step.get("stabilize", self.settings.stabilize_s)))),
            dwell_s=Decimal(str(int(step.get("dwell", self.settings.dwell_s)))),
            reach_timeout_s=Decimal(str(int(math.ceil(step["reach"])))),
            notes=step.get("notes", ""),
        ) for index, step in enumerate(steps))
        header = self.profiles.create_profile(
            self.chamber_id, ParsedProfile(steps=built, name=name,
                                           description="Unattended lab acceptance"))
        self.log("profile_created", name=name, profile_id=header.profile_id,
                 steps=[(float(s.target_temperature_c), float(s.reach_timeout_s))
                        for s in built])
        return header

    def _run_profile(self, phase: str, header, *, cancel_after_s: float | None = None):
        from chamber_web.execution.profile_runner import TERMINAL

        snapshot = self.execution.start(self.operator.session, self.operator.csrf,
                                        header.profile_id, 1)
        runner = self.execution.runner
        self.log("profile_started", phase=phase, run_id=snapshot.run_id)
        started = time.monotonic()
        cancelled_at = None
        last_state = None
        while True:
            state = runner.advance()
            if state is not last_state:
                self.log("run_state", phase=phase, state=state.value if state else None,
                         reason=runner.reason)
                last_state = state
            if state in TERMINAL:
                break
            if cancelled_at is None and (
                    self.stop_requested.is_set() or time.monotonic() > self.deadline or
                    (cancel_after_s is not None and
                     time.monotonic() - started >= cancel_after_s)):
                self.log("profile_cancel", phase=phase)
                self.execution.cancel(self.operator.session, self.operator.csrf)
                cancelled_at = time.monotonic()
            samples = [e for e in runner.events[-5:] if e.kind == "SAMPLE"]
            if samples:
                event = samples[-1]
                self.sample(phase, measured_c=event.temperature_c,
                            setpoint_c=event.setpoint_temperature_c, state=state.value,
                            step=event.step_index + 1)
            time.sleep(self.settings.poll_s)
        events = runner.events
        summary = {
            "run_id": snapshot.run_id, "state": state.value, "reason": runner.reason,
            "seconds": round(time.monotonic() - started),
            "steps_completed": [
                {"step": int(e.detail), "elapsed_s": round(e.monotonic_elapsed_s)}
                for e in events if e.kind == "STEP_COMPLETED"],
        }
        if cancelled_at is not None:
            summary["stop_after_cancel_s"] = round(time.monotonic() - cancelled_at, 1)
        self.log("profile_finished", phase=phase, **summary)
        if self.stop_requested.is_set() or time.monotonic() > self.deadline:
            raise Abort("profile interrupted by signal or deadline")
        return state, summary, events

    def phase_cancel(self, result: PhaseResult) -> None:
        start = self.view().dashboard.setpoint_temperature_c
        # The farther envelope edge: long enough that cancel lands mid-ramp.
        far = (self.hil.temperature_max_c
               if self.hil.temperature_max_c - start >= start - self.hil.temperature_min_c
               else self.hil.temperature_min_c)
        reach = ramp_seconds(start, far, self.gradients) + self.settings.settle_s
        header = self._profile("Lab acceptance - cancel", [{"target": far, "reach": reach}])
        state, summary, _ = self._run_profile(
            "cancel", header, cancel_after_s=self.settings.cancel_after_s)
        result.data.update(summary)
        check(state.value == "CANCELLED", f"run ended {state.value}: {summary['reason']}")
        check(summary.get("stop_after_cancel_s", 99) <= 20, "STOP took longer than 20 s")
        self.verify_stopped("cancel")

    def full_range_steps(self) -> list[dict]:
        start = self.view().dashboard.setpoint_temperature_c
        steps, previous = [], start
        for target in self.settings.targets:
            reach = ramp_seconds(previous, target, self.gradients) + self.settings.settle_s
            steps.append({"target": target, "reach": reach})
            previous = target
        return steps

    def phase_profile(self, result: PhaseResult) -> None:
        steps = self.full_range_steps()
        header = self._profile("Lab acceptance - full range", steps)
        state, summary, events = self._run_profile("profile", header)
        result.data.update(summary, targets=self.settings.targets)
        per_step = {}
        for event in events:
            if event.kind == "SAMPLE" and event.temperature_c is not None:
                low, high = per_step.get(event.step_index + 1, (math.inf, -math.inf))
                per_step[event.step_index + 1] = (min(low, event.temperature_c),
                                                  max(high, event.temperature_c))
        result.data["measured_range_per_step"] = per_step
        check(state.value == "COMPLETED", f"run ended {state.value}: {summary['reason']}")
        self.verify_stopped("profile")

    def phase_gradient(self, result: PhaseResult) -> None:
        check(self.lab.gradients, "gradients disabled (CHAMBER_LAB_GRADIENTS=off)")
        caps = self.manager.capabilities(self.chamber_id)
        requested = self.settings.gradient_c_per_min
        # Each direction within the chamber's own gradient range.
        up = max(caps.ramp_up_range_c_per_min[0], min(requested, caps.ramp_up_range_c_per_min[1]))
        down = max(caps.ramp_down_range_c_per_min[0],
                   min(requested, caps.ramp_down_range_c_per_min[1]))
        start = self.view().dashboard.setpoint_temperature_c
        delta = self.settings.gradient_delta_c
        target = start + delta if start + delta <= self.hil.temperature_max_c else start - delta
        rate = up if target > start else down  # first step's direction
        reach = abs(delta) / min(up, down) * 60.0 + self.settings.settle_s
        steps = [
            {"target": target, "ramp_up": up, "ramp_down": down, "reach": reach,
             "dwell": min(self.settings.dwell_s, 120)},
            {"target": start, "ramp_up": up, "ramp_down": down, "reach": reach,
             "dwell": min(self.settings.dwell_s, 120)},
        ]
        header = self._profile("Lab acceptance - gradients", steps)
        state, summary, events = self._run_profile("gradient", header)
        result.data.update(summary, ramp_up_c_per_min=up, ramp_down_c_per_min=down,
                           target_c=target)
        check(state.value == "COMPLETED", f"run ended {state.value}: {summary['reason']}")
        slope = _readback_slope(events, step_index=0, target=target)
        result.data["observed_readback_slope_c_per_min"] = slope
        check(slope is not None, "no ramping setpoint readback observed")
        check(0.5 * rate <= slope <= 1.5 * rate,
              f"setpoint readback moved at {slope:.3f} °C/min, declared {rate}")
        status = self.manager.status(self.chamber_id)  # fresh G04 device read
        read_up, read_down = status.gradient_up_c_per_min, status.gradient_down_c_per_min
        result.data["gradient_readback"] = (read_up, read_down)
        check(read_up is not None and abs(read_up - up) <= 0.01,
              "gradient up readback mismatch")
        check(read_down is not None and abs(read_down - down) <= 0.01,
              "gradient down readback mismatch")
        self.verify_stopped("gradient")

    def phase_web(self, result: PhaseResult) -> None:
        """A real server process boots in lab mode against the chamber."""
        from chamber_web.security.auth import SecurityStore

        port = self.web_port or 8097
        work = Path(tempfile.mkdtemp(prefix="hil-lab-web-"))
        SecurityStore(work / "security").bootstrap_admin(*ADMIN)
        # Loopback for this check, whatever lab network the operator configured.
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("PYTEST", "NICEGUI_", "CHAMBER_TLS_")) and k not in (
                   "CHAMBER_BIND_HOST", "CHAMBER_PUBLIC_ORIGIN",
                   "CHAMBER_ALLOWED_CLIENT_CIDRS", "CHAMBER_ALLOWED_ORIGINS")}
        env.update({"CHAMBER_SECURITY_DIR": str(work / "security"),
                    "CHAMBER_RUN_JOURNAL_DIR": str(work / "runs"),
                    "CHAMBER_PORT": str(port), "CHAMBER_NETWORK_MODE": "localhost",
                    "CHAMBER_LAB_MODE": "ISOLATED-LAB-UNATTENDED",
                    "PYTHONUNBUFFERED": "1"})
        url = f"http://127.0.0.1:{port}/login"
        with open(self.evidence / "web-server.log", "w", encoding="utf-8") as log:
            server = subprocess.Popen([sys.executable, "-m", "main"], cwd=ROOT, env=env,
                                      stdout=log, stderr=subprocess.STDOUT)
            try:
                body, deadline = "", time.monotonic() + 60
                while time.monotonic() < deadline and server.poll() is None:
                    try:
                        with urllib.request.urlopen(url, timeout=2) as response:
                            body = response.read().decode("utf-8", "replace")
                            result.data["http_status"] = response.status
                        break
                    except Exception:  # noqa: BLE001 - still starting
                        time.sleep(0.5)
                check(server.poll() is None, "lab server exited (see web-server.log)")
                check(result.data.get("http_status") == 200, "lab server did not answer")
                check("isolated lab mode" in body, "page title does not show lab mode")
            finally:
                server.send_signal(signal.SIGINT if os.name != "nt" else signal.SIGTERM)
                try:
                    server.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    server.kill()

    # -- orchestration -----------------------------------------------------------
    def run(self, selected: list[str]) -> bool:
        aborted = None
        try:
            self.precheck()
            stack_phases = [p for p in selected if p != "web"]
            if stack_phases:
                self.connect()
                self.ensure_rearmed()
            for name in stack_phases:
                if aborted:
                    self.results.append(PhaseResult(name, "SKIPPED", detail=aborted))
                    continue
                aborted = self._phase(name)
        except Abort as exc:
            aborted = str(exc)
            self.log("abort", reason=aborted)
        except Exception as exc:  # noqa: BLE001 - always clean up below
            aborted = f"{type(exc).__name__}: {exc}"
            self.log("abort", reason=aborted)
        finally:
            try:
                self.close()
            except Exception as exc:  # noqa: BLE001 - postcheck must still run
                self.log("close_failed", error=repr(exc))
            try:
                self.postcheck()
            except Exception as exc:  # noqa: BLE001
                self.log("postcheck_failed", error=repr(exc))
                aborted = aborted or f"postcheck failed: {exc}"
        if "web" in selected:
            if aborted:
                self.results.append(PhaseResult("web", "SKIPPED", detail=aborted))
            else:
                self._phase("web")
        done = {r.name for r in self.results}
        for name in selected:
            if name not in done:
                self.results.append(PhaseResult(name, "SKIPPED", detail=aborted or ""))
        passed = not aborted and all(r.status == "PASSED" for r in self.results)
        self.write_summary(passed, aborted)
        return passed

    def _phase(self, name: str) -> str | None:
        result = PhaseResult(name)
        self.results.append(result)
        self.log("phase_start", phase=name)
        started = time.monotonic()
        aborted = None
        try:
            self.guard_time()
            getattr(self, "phase_" + name)(result)
            result.status = "PASSED"
        except Abort as exc:
            result.status, result.detail = "ABORTED", str(exc)
            aborted = str(exc)
        except Exception as exc:  # noqa: BLE001 - a failed phase is evidence
            result.status = "FAILED"
            result.detail = str(exc) if isinstance(exc, PhaseFailed) else (
                f"{type(exc).__name__}: {exc}")
        result.seconds = round(time.monotonic() - started, 1)
        if name != "web":
            # Every phase ends STOPPED, released and re-armed for the next one.
            try:
                from chamber_web.execution.profile_runner import TERMINAL

                runner = self.execution.runner
                if runner is not None and runner.state is not None and (
                        runner.state not in TERMINAL):
                    self.execution.cancel(self.operator.session, self.operator.csrf)
                    for _ in range(100):
                        if runner.advance() in TERMINAL:
                            break
                        time.sleep(0.2)
                if self.view().dashboard.operation_state is not OperationState.STOPPED:
                    self.send(self.admin, "stop")
                self.verify_stopped(name)
                self.release_lease()
                if not aborted:
                    self.ensure_rearmed()
            except Abort as exc:
                aborted = str(exc)
            except Exception as exc:  # noqa: BLE001
                aborted = f"cleanup after {name} failed: {type(exc).__name__}: {exc}"
        self.log("phase_end", phase=name, status=result.status, seconds=result.seconds,
                 detail=result.detail)
        return aborted

    def write_summary(self, passed: bool, aborted: str | None) -> None:
        summary = {
            "status": "PASSED" if passed else "FAILED",
            "aborted": aborted,
            "duration_s": round(time.monotonic() - self.t0, 1),
            "chamber": {"address": self.hil.address, "serial": self.hil.expected_serial,
                        "envelope_c": [self.hil.temperature_min_c, self.hil.temperature_max_c]},
            "lab": {"measured_margin_c": self.lab.measured_margin_c,
                    "gradients": self.lab.gradients},
            "original": self.original,
            "measured_min_c": min(self.measured) if self.measured else None,
            "measured_max_c": max(self.measured) if self.measured else None,
            "phases": [r.__dict__ for r in self.results],
        }
        (self.evidence / "summary.json").write_text(
            json.dumps(summary, indent=2, default=str), encoding="utf-8")
        lines = [f"# Lab HIL acceptance: {summary['status']}", "",
                 f"Chamber {self.hil.expected_serial} at {self.hil.address}, envelope "
                 f"{self.hil.temperature_min_c:g}..{self.hil.temperature_max_c:g} °C, "
                 f"duration {summary['duration_s'] / 60:.1f} min, measured "
                 f"{summary['measured_min_c']}..{summary['measured_max_c']} °C.", "",
                 "| Phase | Result | Minutes | Detail |", "|---|---|---|---|"]
        lines += [f"| {r.name} | {r.status} | {r.seconds / 60:.1f} | {r.detail} |"
                  for r in self.results]
        if aborted:
            lines += ["", f"Aborted: {aborted}"]
        (self.evidence / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.log("summary", status=summary["status"], aborted=aborted,
                 phases={r.name: r.status for r in self.results})


def _settled_setpoint(chamber, *, timeout_s: float = 600.0) -> float:
    """The 11002 readback ramps after a write; wait until it stops moving."""
    deadline = time.monotonic() + timeout_s
    previous = chamber.temperature_set_point
    while True:
        time.sleep(2.0)
        current = chamber.temperature_set_point
        if abs(current - previous) <= 0.01:
            return current
        if time.monotonic() > deadline:
            raise Abort("chamber setpoint still ramping; cannot record the original")
        previous = current


def _readback_slope(events, *, step_index: int, target: float) -> float | None:
    """°C/min of the setpoint readback while it ramps toward ``target``."""
    points = [(e.monotonic_elapsed_s, e.setpoint_temperature_c) for e in events
              if e.kind == "SAMPLE" and e.step_index == step_index and
              e.setpoint_temperature_c is not None and
              abs(e.setpoint_temperature_c - target) > 0.2]
    if len(points) < 3:
        return None
    (t1, s1), (t2, s2) = points[0], points[-1]
    return abs(s2 - s1) / (t2 - t1) * 60.0 if t2 > t1 else None


def plan_estimate(hil, settings: Settings, gradients: tuple[float, float], start_c: float,
                  selected: list[str]) -> dict[str, float]:
    """Rough minutes per phase, for the operator's planning only."""
    estimate = {}
    if "manual" in selected:
        estimate["manual"] = (2 * ramp_seconds(start_c, start_c + settings.manual_delta_c,
                                               gradients) + settings.manual_hold_s) / 60
    if "cancel" in selected:
        estimate["cancel"] = (settings.cancel_after_s + 60) / 60
    if "profile" in selected:
        total, previous = 0.0, start_c
        for target in settings.targets:
            total += ramp_seconds(previous, target, gradients) + settings.dwell_s + \
                settings.stabilize_s + 600
            previous = target
        estimate["profile"] = total / 60
    if "gradient" in selected:
        estimate["gradient"] = (2 * settings.gradient_delta_c / settings.gradient_c_per_min * 60
                                + 2 * min(settings.dwell_s, 120) + 600) / 60
    return {k: round(v, 1) for k, v in estimate.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--phases", default=",".join(PHASES),
                        help="comma-separated subset of: " + ",".join(PHASES))
    parser.add_argument("--targets", default="max,min,start",
                        help="full-range profile targets in °C; max/min/start are the "
                             "envelope edges and the starting setpoint (default max,min,start)")
    parser.add_argument("--edge-inset", type=float, default=0.0,
                        help="keep max/min targets this many °C inside the envelope")
    parser.add_argument("--dwell", type=float, help="dwell per profile step, s (600)")
    parser.add_argument("--stabilize", type=float, help="stabilization per step, s (60)")
    parser.add_argument("--tolerance", type=float, default=1.5, help="°C band (1.5)")
    parser.add_argument("--settle", type=float,
                        help="allowance beyond the setpoint ramp to reach the band, s (2400)")
    parser.add_argument("--manual-delta", type=float, default=15.0)
    parser.add_argument("--manual-hold", type=float, help="manual hold, s (60)")
    parser.add_argument("--gradient", type=float,
                        help="declared gradient for the gradient phase, °C/min (1.0)")
    parser.add_argument("--gradient-delta", type=float,
                        help="gradient phase step size, °C (10)")
    parser.add_argument("--cancel-after", type=float, help="cancel phase run time, s (60)")
    parser.add_argument("--deadline-hours", type=float,
                        help="hard limit for the whole run (estimate + 2 h)")
    parser.add_argument("--web-port", type=int, default=8097)
    parser.add_argument("--plan-only", action="store_true",
                        help="connect read-only, print the plan and estimate, then exit")
    parser.add_argument("--simulate", action="store_true",
                        help="use the in-process VT 4011 simulator instead of a chamber")
    parser.add_argument("--sim-envelope", default="-40,130")
    args = parser.parse_args(argv)

    selected = [p.strip() for p in args.phases.split(",") if p.strip()]
    unknown = sorted(set(selected) - set(PHASES))
    if unknown:
        parser.error("unknown phases: " + ", ".join(unknown))

    driver_factory = None
    if args.simulate:
        from scripts.vt4011_simulator import SimulatedVT4011

        low, high = (float(v) for v in args.sim_envelope.split(","))
        chamber = SimulatedVT4011(gradient_up=60.0, gradient_down=60.0, tau_s=4.0)
        driver_factory = lambda: chamber  # noqa: E731 - one shared simulated chamber
        hil = HilAuthorization("hil-votsch", "192.168.0.11", chamber.serial_number, low, high)
        lab = LabMode()
        if "web" in selected:
            selected.remove("web")  # a separate server process cannot share the simulator
        defaults = dict(dwell=5, stabilize=4, settle=60, manual_hold=5, cancel_after=3,
                        gradient=5.0, gradient_delta=3.0)
    else:
        try:
            hil = hil_authorization_from_env(os.environ)
            lab = lab_mode_from_env(os.environ, hil_present=hil is not None)
        except Exception as exc:  # noqa: BLE001 - configuration errors are fatal
            print(f"Configuration refused: {exc}", file=sys.stderr)
            return 2
        if hil is None or lab is None:
            print("Requires the complete CHAMBER_HIL_* authorization and "
                  "CHAMBER_LAB_MODE=ISOLATED-LAB-UNATTENDED (see README_LAB.md)",
                  file=sys.stderr)
            return 2
        defaults = dict(dwell=600, stabilize=60, settle=2400, manual_hold=60, cancel_after=60,
                        gradient=1.0, gradient_delta=10.0)
    if "gradient" in selected and not lab.gradients:
        selected.remove("gradient")

    def pick(name):
        value = getattr(args, name)
        return defaults[name] if value is None else value

    def target(token: str) -> float | str:
        token = token.strip().lower()
        if token == "max":
            return hil.temperature_max_c - args.edge_inset
        if token == "min":
            return hil.temperature_min_c + args.edge_inset
        if token == "start":
            return "start"
        return float(token)

    raw_targets = [target(t) for t in args.targets.split(",") if t.strip()]
    settings = Settings(
        targets=[], dwell_s=pick("dwell"), stabilize_s=pick("stabilize"),
        tolerance_c=args.tolerance, settle_s=pick("settle"),
        manual_delta_c=args.manual_delta, manual_hold_s=pick("manual_hold"),
        gradient_c_per_min=pick("gradient"), gradient_delta_c=pick("gradient_delta"),
        cancel_after_s=pick("cancel_after"))

    # Read-only probe for the plan: starting setpoint and the chamber gradients.
    probe = LabAcceptance(hil, lab, args.evidence, settings, deadline_s=3600,
                          driver_factory=driver_factory)
    try:
        probe.precheck()
    except Abort as exc:
        print(f"Precheck refused: {exc}", file=sys.stderr)
        return 2
    start_c = probe.original["setpoint_c"]
    settings.targets = [start_c if t == "start" else t for t in raw_targets]
    for value in settings.targets:
        if not hil.temperature_min_c <= value <= hil.temperature_max_c:
            print(f"Target {value} °C is outside the envelope", file=sys.stderr)
            return 2
    gradients = (probe.original["gradient_up"], probe.original["gradient_down"])
    estimate = plan_estimate(hil, settings, gradients, start_c, selected)
    total_h = sum(estimate.values()) / 60
    deadline_h = args.deadline_hours or total_h + 2
    probe.log("plan", phases=selected, targets=settings.targets, gradients=gradients,
              estimate_min=estimate, deadline_h=round(deadline_h, 2))
    if args.plan_only:
        return 0

    acceptance = LabAcceptance(hil, lab, args.evidence, settings,
                               deadline_s=deadline_h * 3600, driver_factory=driver_factory,
                               web_port=args.web_port)

    def on_signal(signum, _frame):
        acceptance.stop_requested.set()
        acceptance.log("signal", signum=signum)
    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)
    if hasattr(signal, "SIGHUP"):
        # A dropped SSH session or closed terminal must not end an unattended
        # run without its STOP/restore cleanup: keep running, evidence on disk.
        signal.signal(signal.SIGHUP, lambda signum, _frame: acceptance.log(
            "sighup_ignored", note="console detached; run continues"))
    return 0 if acceptance.run(selected) else 1


if __name__ == "__main__":
    raise SystemExit(main())
