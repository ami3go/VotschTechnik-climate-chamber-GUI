"""Shared helpers for the opt-in real-hardware tests (no fixtures here)."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from chamber_web.hil.physical import hil_authorization_from_env

STEP_C = float(os.environ.get("CHAMBER_HIL_TEST_STEP_C", "1.0"))
RUN_S = float(os.environ.get("CHAMBER_HIL_TEST_RUN_S", "20"))
WEB_PORT = int(os.environ.get("CHAMBER_HIL_TEST_PORT", "8095"))
ADMIN = ("hil_test_admin", "StrongAdminPassword#1")
OPERATOR = ("hil_test_operator", "StrongOperatorPassword#2")



def authorization():
    if os.environ.get("CHAMBER_HIL_RUN_TESTS") != "1":
        return None, "set CHAMBER_HIL_RUN_TESTS=1 to run real-hardware tests"
    try:
        hil = hil_authorization_from_env(os.environ)
    except Exception as exc:  # invalid configuration must fail loudly, not skip
        pytest.exit(f"Invalid CHAMBER_HIL_* configuration: {exc}", returncode=2)
    if hil is None:
        return None, "CHAMBER_HIL_* authorization not configured"
    if not 0.1 <= STEP_C <= 5.0 or not 1 <= RUN_S <= 600:
        pytest.exit("CHAMBER_HIL_TEST_STEP_C must be 0.1..5 and CHAMBER_HIL_TEST_RUN_S 1..600",
                    returncode=2)
    return hil, None



class Evidence:
    """Append-only timeline for the hardware acceptance record."""

    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self._t0 = time.monotonic()

    def log(self, event: str, **data) -> None:
        record = {"t_s": round(time.monotonic() - self._t0, 2),
                  "utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "event": event, **data}
        with open(self.directory / "timeline.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        print(f"[HIL {record['t_s']:7.1f}s] {event} {data if data else ''}", flush=True)


def direct_driver(hil):
    """Independent driver connection; never open while the service stack is connected."""
    from VotschTechnikClimateChamber import ClimateChamber

    return ClimateChamber(hil.address, hil.temperature_min_c, hil.temperature_max_c, timeout=2)


def direct_status(hil) -> dict:
    chamber = direct_driver(hil)
    try:
        return {"serial": str(chamber.serial_number).strip(),
                "measured_c": chamber.temperature_measured,
                "setpoint_c": settled_setpoint(chamber),
                "running": chamber.is_running}
    finally:
        chamber.disconnect()


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
