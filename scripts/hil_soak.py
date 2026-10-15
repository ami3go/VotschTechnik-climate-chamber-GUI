"""Supervised physical soak / endurance run for ONE Vötsch chamber.

Uses the same G04/G08/G05 composition root as the web server (no browser),
so it runs locally without internet. Requires the complete CHAMBER_HIL_*
authorization (README_WEB.md). A person must stay at the chamber.

    python scripts/hil_soak.py --evidence DIR [--plan 25:600,26:360,24:360] [--restart 24:180]

Every phase is RUNNING at a target inside the HIL envelope. A watchdog STOPs
and aborts on any error, serial mismatch, non-GOOD telemetry for more than
15 s, measured temperature beyond envelope +/- 3 °C, SIGINT/SIGTERM, or the
hard deadline. The original setpoint is restored with the chamber STOPPED.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import signal
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chamber_web.domain.chamber import OperationState, ReadingQuality  # noqa: E402
from chamber_web.hil.physical import hil_authorization_from_env  # noqa: E402

ADMIN = ("soak_admin", "StrongAdminPassword#1")
OPERATOR = ("soak_operator", "StrongOperatorPassword#2")
SAMPLE_S = 5.0
BAD_QUALITY_LIMIT_S = 15.0
MEASURED_MARGIN_C = 3.0


def settled_setpoint(chamber, *, timeout_s: float = 90.0) -> float:
    """The 11002 readback ramps after a write; wait until it stops moving."""
    import time as _time

    deadline = _time.monotonic() + timeout_s
    previous = chamber.temperature_set_point
    while True:
        _time.sleep(2.0)
        current = chamber.temperature_set_point
        if abs(current - previous) <= 0.01:
            return current
        if _time.monotonic() > deadline:
            raise RuntimeError("Chamber setpoint still ramping; cannot record the original")
        previous = current


class Abort(RuntimeError):
    pass


class Soak:
    def __init__(self, hil, evidence: Path, deadline_s: float):
        self.hil = hil
        self.evidence = evidence
        evidence.mkdir(parents=True, exist_ok=True)
        self.t0 = time.monotonic()
        self.deadline = self.t0 + deadline_s
        self.stop_requested = False
        self.samples: list[dict] = []
        self.events: list[dict] = []
        self.bad_since: float | None = None

    # -- evidence ---------------------------------------------------------
    def log(self, event: str, **data) -> None:
        record = {"t_s": round(time.monotonic() - self.t0, 1),
                  "utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "event": event, **data}
        self.events.append(record)
        with open(self.evidence / "timeline.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        print(f"[{record['t_s']:7.1f}s] {event} {data if data else ''}", flush=True)

    # -- direct, independent driver checks (never while services connected) --
    def direct(self):
        from VotschTechnikClimateChamber import ClimateChamber

        return ClimateChamber(self.hil.address, self.hil.temperature_min_c,
                              self.hil.temperature_max_c, timeout=2)

    def precheck(self) -> float:
        chamber = self.direct()
        try:
            serial = str(chamber.serial_number).strip()
            running = chamber.is_running
            setpoint = settled_setpoint(chamber)
            measured = chamber.temperature_measured
        finally:
            chamber.disconnect()
        self.log("precheck", serial=serial, measured_c=measured, setpoint_c=setpoint, running=running)
        if serial != self.hil.expected_serial:
            raise Abort("serial mismatch")
        if running:
            raise Abort("chamber already RUNNING")
        if not self.hil.temperature_min_c <= setpoint <= self.hil.temperature_max_c:
            raise Abort("setpoint outside envelope")
        return setpoint

    def postcheck(self, original_setpoint: float) -> None:
        chamber = self.direct()
        try:
            if chamber.is_running:
                self.log("postcheck_running_direct_stop")
                chamber.stop()
            if abs(chamber.temperature_set_point - original_setpoint) > 0.05:
                chamber.temperature_set_point = original_setpoint
                self.log("restored_setpoint", setpoint_c=original_setpoint)
            self.log("postcheck", running=chamber.is_running,
                     measured_c=chamber.temperature_measured)
        finally:
            chamber.disconnect()

    # -- service stack ------------------------------------------------------
    def connect(self):
        from chamber_web.bootstrap import create_demo_control_services
        from chamber_web.security.auth import Role, SecurityStore

        security = SecurityStore(Path(tempfile.mkdtemp(prefix="hil-soak-")) / "security")
        security.bootstrap_admin(*ADMIN)
        self.admin = security.login(*ADMIN)
        security.create_user(self.admin.session, self.admin.csrf, *OPERATOR, Role.OPERATOR)
        self.operator = security.login(*OPERATOR)
        self.dashboard, self.manual = create_demo_control_services(
            security, self.hil, lease_directory=Path.home() / ".chamber_web" / "ownership")

    def send(self, tokens, action: str, **kw):
        outcome = self.manual.command(tokens.session, tokens.csrf, self.manual.chamber_id,
                                      action, **kw)
        self.log("command", action=action, state=outcome.state.value, message=outcome.message,
                 **({"target_c": kw["target_c"]} if "target_c" in kw else {}))
        return outcome

    def require(self, tokens, action: str, **kw) -> None:
        outcome = self.send(tokens, action, **kw)
        if outcome.state.value != "CONFIRMED":
            raise Abort(f"{action} not confirmed: {outcome.state.value} {outcome.message}")

    def sample(self, phase: str, expect: OperationState) -> None:
        started = time.monotonic()
        asyncio.run(self.dashboard.poll_once())
        view = self.manual.view(self.admin.session, self.manual.chamber_id)
        latency_ms = round(1000 * (time.monotonic() - started))
        d = view.dashboard
        record = {"t_s": round(time.monotonic() - self.t0, 1), "phase": phase,
                  "measured_c": d.measured_temperature_c, "setpoint_c": d.setpoint_temperature_c,
                  "state": d.operation_state.value, "quality": d.quality.value,
                  "controller": view.controller_state, "latency_ms": latency_ms}
        self.samples.append(record)
        with open(self.evidence / "samples.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        print(f"[{record['t_s']:7.1f}s] {phase:<10} measured={d.measured_temperature_c} "
              f"setpoint={d.setpoint_temperature_c} {d.operation_state.value} "
              f"{d.quality.value} {latency_ms}ms", flush=True)
        # Watchdog checks
        now = time.monotonic()
        good = d.quality is ReadingQuality.GOOD and d.identity is not None and (
            d.identity.serial_number == self.hil.expected_serial)
        if d.identity is not None and d.identity.serial_number != self.hil.expected_serial:
            raise Abort("serial changed during soak")
        if not good:
            self.bad_since = self.bad_since or now
            if now - self.bad_since > BAD_QUALITY_LIMIT_S:
                raise Abort("telemetry not GOOD for too long")
            return
        self.bad_since = None
        m = d.measured_temperature_c
        if m is None or not math.isfinite(m) or not (
                self.hil.temperature_min_c - MEASURED_MARGIN_C <= m
                <= self.hil.temperature_max_c + MEASURED_MARGIN_C):
            raise Abort(f"measured temperature {m} beyond envelope margin")
        if d.operation_state is not expect:
            raise Abort(f"expected {expect.value}, chamber reports {d.operation_state.value}")

    def hold(self, phase: str, seconds: float, expect: OperationState) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if self.stop_requested:
                raise Abort("signal received")
            if time.monotonic() > self.deadline:
                raise Abort("hard deadline reached")
            self.sample(phase, expect)
            time.sleep(SAMPLE_S)

    def summary(self, status: str, reason: str | None) -> dict:
        running = [s for s in self.samples if s["state"] == "RUNNING"]
        measured = [s["measured_c"] for s in self.samples if s["measured_c"] is not None]
        latencies = [s["latency_ms"] for s in self.samples]
        result = {
            "status": status, "reason": reason,
            "duration_s": round(time.monotonic() - self.t0, 1),
            "samples": len(self.samples), "running_samples": len(running),
            "non_good_samples": sum(s["quality"] != "GOOD" for s in self.samples),
            "measured_min_c": min(measured) if measured else None,
            "measured_max_c": max(measured) if measured else None,
            "latency_ms_max": max(latencies) if latencies else None,
            "latency_ms_mean": round(sum(latencies) / len(latencies)) if latencies else None,
            "commands": [e for e in self.events if e["event"] == "command"],
        }
        (self.evidence / "summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result


def parse_plan(text: str) -> list[tuple[float, float]]:
    steps = []
    for part in text.split(","):
        target, seconds = part.split(":")
        steps.append((float(target), float(seconds)))
    return steps


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--plan", default="25:600,26:360,24:360",
                        help="RUNNING phases as target:seconds,... (default ~22 min)")
    parser.add_argument("--stopped-pause", type=float, default=60.0)
    parser.add_argument("--restart", default="24:180", help="target:seconds after STOP/restart")
    parser.add_argument("--deadline", type=float, default=2400.0, help="hard limit, seconds")
    args = parser.parse_args()

    hil = hil_authorization_from_env(os.environ)
    if hil is None:
        print("CHAMBER_HIL_* authorization required (see README_WEB.md)", file=sys.stderr)
        return 2
    plan, restart = parse_plan(args.plan), parse_plan(args.restart)
    for target, seconds in plan + restart:
        if not hil.temperature_min_c <= target <= hil.temperature_max_c or seconds <= 0:
            print(f"Plan step {target}:{seconds} outside envelope", file=sys.stderr)
            return 2

    soak = Soak(hil, args.evidence, args.deadline)

    def on_signal(signum, _frame):
        soak.stop_requested = True
        soak.log("signal", signum=signum)
    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    original = soak.precheck()
    status, reason = "PASSED", None
    connected = False
    try:
        soak.connect()
        connected = True
        view = soak.manual.view(soak.admin.session, soak.manual.chamber_id)
        if view.stop_latched:
            soak.require(soak.admin, "reconcile")  # chamber independently verified STOPPED
        soak.require(soak.operator, "claim")
        for index, (target, seconds) in enumerate(plan):
            soak.require(soak.operator, "set_temperature", target_c=target)
            if index == 0:
                soak.require(soak.operator, "start")
            soak.hold(f"run@{target:g}", seconds, OperationState.RUNNING)
        soak.require(soak.operator, "stop")
        soak.hold("stopped", args.stopped_pause, OperationState.STOPPED)
        soak.require(soak.admin, "reconcile")
        # STOP does not release the operator lease; claim only if it is free.
        if not soak.manual.view(soak.operator.session, soak.manual.chamber_id).owned_by_actor:
            soak.require(soak.operator, "claim")
        for index, (target, seconds) in enumerate(restart):
            soak.require(soak.operator, "set_temperature", target_c=target)
            if index == 0:
                soak.require(soak.operator, "start")
            soak.hold(f"rerun@{target:g}", seconds, OperationState.RUNNING)
        soak.require(soak.operator, "stop")
    except BaseException as exc:  # noqa: BLE001 - always STOP below
        status, reason = "ABORTED", f"{type(exc).__name__}: {exc}"
        soak.log("abort", reason=reason)
    finally:
        if connected:
            try:
                soak.send(soak.admin, "stop")
            except Exception as exc:  # noqa: BLE001
                soak.log("service_stop_failed", error=repr(exc))
            try:
                asyncio.run(soak.dashboard.close())
            except Exception as exc:  # noqa: BLE001
                soak.log("disconnect_failed", error=repr(exc))
        soak.postcheck(original)
        result = soak.summary(status, reason)
        soak.log("summary", **{k: v for k, v in result.items() if k != "commands"})
    return 0 if status == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
