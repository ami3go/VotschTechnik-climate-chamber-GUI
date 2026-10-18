"""H02-C watchdog child process: independent supervision, no device authority.

Launched by ``chamber_web.hil.supervision.SupervisionHost`` as a separate OS
process over an authenticated loopback connection. It enforces, with its own
monotonic clock:

- the application heartbeat deadline (``process_heartbeat_s``);
- whole-run and per-step remaining-budget monotonicity;
- telemetry freshness, temperature-envelope, operator-lease, recorder-health
  and controller-generation flags supplied by the application.

On any violation it sends exactly one ``STOP_REQUEST``; the application (G04
command authority) owns the approved STOP path. If the application stops
heartbeating, the child records ``PARENT_LOST`` and exits non-zero. The child
never opens a device connection and never writes bench state.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from datetime import datetime, timezone

from chamber_web.hil import watchdog_protocol as wp

AUTHKEY_ENV = "CHAMBER_WATCHDOG_AUTHKEY_B64"


def _evidence(path: str, event: str, **fields) -> None:
    record = {
        "at_utc": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        "monotonic": time.monotonic(),
        "pid": os.getpid(),
        "event": event,
        **fields,
    }
    try:
        with open(path, "a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, sort_keys=True) + "\n")
    except OSError:
        pass  # evidence loss never suppresses supervision decisions


def watchdog_main(address, authkey: bytes, config: dict,
                  evidence_path: str) -> int:
    from multiprocessing.connection import Client

    _evidence(evidence_path, "CHILD_START", protocol=wp.PROTOCOL_VERSION)
    try:
        limits = dict(config["limits"])
        wp.validate_limits(limits)
        chamber_id = str(config["chamber_id"])
        serial_number = str(config["serial_number"])
        if not chamber_id.strip() or not serial_number.strip():
            raise wp.WatchdogProtocolError("Missing identity binding")
    except Exception as exc:
        _evidence(evidence_path, "CONFIG_INVALID", error=type(exc).__name__)
        return wp.EXIT_CONFIG_INVALID
    try:
        conn = Client(address, authkey=authkey)
    except Exception as exc:
        _evidence(evidence_path, "CHILD_CONNECT_FAILED", error=type(exc).__name__)
        return wp.EXIT_CONNECT_FAILED

    parent_deadline_s = float(limits["process_heartbeat_s"])
    step_deadline_s = float(limits["profile_step_deadline_s"])
    whole_deadline_s = float(limits["whole_profile_deadline_s"])
    telemetry_gap_s = float(limits["max_telemetry_gap_s"])
    sent_stop = False
    last_parent = time.monotonic()
    expected_seq = 0
    observed_step: int | None = None
    step_remaining: float | None = None
    whole_remaining: float | None = None
    try:
        conn.send({"type": wp.READY, "protocol": wp.PROTOCOL_VERSION,
                   "pid": os.getpid()})
        _evidence(evidence_path, "CHILD_READY")
        while True:
            if time.monotonic() - last_parent > parent_deadline_s:
                _evidence(evidence_path, "PARENT_LOST")
                return wp.EXIT_PARENT_LOST
            if conn.poll(0.05):
                message = conn.recv()
                if not isinstance(message, dict):
                    _evidence(evidence_path, "PROTOCOL_ERROR", detail="non-dict")
                    return wp.EXIT_PROTOCOL_ERROR
                kind = message.get("type")
                if kind == wp.SHUTDOWN:
                    _evidence(evidence_path, "SHUTDOWN")
                    return 0
                if kind == wp.CONFIG:
                    try:
                        allowed = set(limits) | {"chamber_id", "serial_number",
                                                 "type", "protocol"}
                        if set(message) != allowed:
                            raise wp.WatchdogProtocolError("unexpected CONFIG keys")
                        if message.get("protocol") != wp.PROTOCOL_VERSION:
                            raise wp.WatchdogProtocolError("CONFIG protocol mismatch")
                        if {name: message.get(name) for name in limits} != limits:
                            raise wp.WatchdogProtocolError("CONFIG limits mismatch")
                        if (message.get("chamber_id") != chamber_id or
                                message.get("serial_number") != serial_number):
                            raise wp.WatchdogProtocolError("CONFIG identity mismatch")
                    except Exception as exc:
                        _evidence(evidence_path, "PROTOCOL_ERROR",
                                  detail="CONFIG " + type(exc).__name__)
                        return wp.EXIT_PROTOCOL_ERROR
                    _evidence(evidence_path, "CONFIG_CONFIRMED")
                    conn.send({"type": wp.ACK, "seq": message.get("seq")})
                    continue
                if kind != wp.HEARTBEAT:
                    _evidence(evidence_path, "PROTOCOL_ERROR", detail=str(kind))
                    return wp.EXIT_PROTOCOL_ERROR
                last_parent = time.monotonic()
                fault = _heartbeat_fault(message, expected_seq)
                expected_seq += 1
                if fault is None:
                    fault = _run_fault(
                        message, step_deadline_s, whole_deadline_s,
                        telemetry_gap_s, observed_step, step_remaining,
                        whole_remaining,
                    )
                    if fault is None:
                        observed_step = message.get("step_index")
                        step_remaining = message.get("step_remaining_s")
                        whole_remaining = message.get("whole_remaining_s")
                conn.send({"type": wp.ACK, "seq": message.get("seq")})
                if fault is not None and not sent_stop:
                    sent_stop = True
                    _evidence(evidence_path, "FAULT", reason=fault)
                    conn.send({"type": wp.STOP_REQUEST, "reason": fault})
    except (EOFError, OSError):
        _evidence(evidence_path, "PARENT_LOST")
        return wp.EXIT_PARENT_LOST
    finally:
        conn.close()


def _heartbeat_fault(message: dict, expected_seq: int) -> str | None:
    if message.get("seq") != expected_seq:
        return "heartbeat sequence gap"
    state = message.get("state")
    if state not in (wp.STATE_IDLE, wp.STATE_ARMED):
        return "unknown supervision state"
    return None


def _run_fault(message: dict, step_deadline_s: float, whole_deadline_s: float,
               telemetry_gap_s: float, observed_step: int | None,
               previous_step_remaining: float | None,
               previous_whole_remaining: float | None) -> str | None:
    if message.get("state") != wp.STATE_ARMED:
        return None
    generation = message.get("generation")
    if (isinstance(generation, bool) or not isinstance(generation, int) or
            generation != message.get("expected_generation")):
        return "controller generation changed"
    if message.get("owner_ok") is not True:
        return "operator lease lost"
    if message.get("recorder_ok") is not True:
        return "run recorder unhealthy"
    if message.get("temp_ok") is not True:
        return "measured temperature outside the approved envelope"
    age = message.get("telemetry_age_s")
    if (isinstance(age, bool) or not isinstance(age, (int, float)) or
            not 0 <= age <= telemetry_gap_s):
        return "stale telemetry"
    whole = message.get("whole_remaining_s")
    if isinstance(whole, bool) or not isinstance(whole, (int, float)):
        return "invalid whole-run budget"
    if whole < -0.25 or whole > whole_deadline_s + 0.25:
        return "whole-run deadline exceeded"
    if previous_whole_remaining is not None and whole > previous_whole_remaining + 0.5:
        return "whole-run budget moved backwards"
    step_index = message.get("step_index")
    remaining = message.get("step_remaining_s")
    if (isinstance(step_index, bool) or not isinstance(step_index, int) or
            step_index < 0):
        return "invalid step index"
    if (isinstance(remaining, bool) or not isinstance(remaining, (int, float))):
        return "invalid step budget"
    if step_index != observed_step:
        if remaining > step_deadline_s + 0.25:
            return "step deadline exceeds the approved maximum"
    else:
        if remaining < -0.25:
            return "step deadline exceeded"
        if (previous_step_remaining is not None and
                remaining > previous_step_remaining + 0.5):
            return "step budget moved backwards"
    return None


def _cli(argv: list[str] | None = None) -> int:
    """Process entry point; the host launches this via ``python -m``.

    The launch is deliberately a fresh interpreter rather than a
    ``multiprocessing`` spawn child: spawn re-executes the parent's
    ``__main__`` module, which for the GUI app would rebuild the composition
    root (including backend connections) inside the watchdog process.
    """
    parser = argparse.ArgumentParser(description="H02-C watchdog process")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args(argv)
    raw_key = os.environ.pop(AUTHKEY_ENV, "")
    try:
        authkey = base64.b64decode(raw_key, validate=True)
        if len(authkey) != 32:
            raise ValueError("authkey must be 32 bytes")
        config = json.loads(sys.stdin.read())
    except Exception as exc:
        _evidence(args.evidence, "CONFIG_INVALID", error=type(exc).__name__)
        return wp.EXIT_CONFIG_INVALID
    return watchdog_main(
        ("127.0.0.1", args.port), authkey, config, args.evidence,
    )


if __name__ == "__main__":
    raise SystemExit(_cli())
