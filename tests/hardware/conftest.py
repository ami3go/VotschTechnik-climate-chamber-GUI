"""Opt-in REAL-HARDWARE tests for one supervised Vötsch chamber.

Collected but SKIPPED unless BOTH are true:

* a complete, valid ``CHAMBER_HIL_*`` authorization (see README_WEB.md), and
* ``CHAMBER_HIL_RUN_TESTS=1`` (so an exported HIL server environment alone
  never makes a broad ``pytest`` run move a chamber).

A person must be present at the chamber. The session guard refuses to start
unless the chamber is verified STOPPED inside the envelope, issues STOP after
every test, and finally re-checks STOP and restores the original setpoint over
an independent driver connection. Web STOP is not an emergency stop.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pytest

from hil_support import (ADMIN, OPERATOR, STEP_C, Evidence, authorization as _authorization,
                         direct_driver, direct_status)

def pytest_collection_modifyitems(config, items):
    here = Path(__file__).parent
    hil, reason = _authorization()
    for item in items:
        if here in Path(str(item.fspath)).parents:
            item.add_marker(pytest.mark.hardware)
            if hil is None:
                item.add_marker(pytest.mark.skip(reason=reason))


@pytest.fixture(scope="session")
def hil():
    authorization, reason = _authorization()
    if authorization is None:
        pytest.skip(reason)
    return authorization


@pytest.fixture(scope="session")
def evidence():
    root = os.environ.get("CHAMBER_HIL_EVIDENCE_DIR")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    directory = Path(root) if root else Path(tempfile.gettempdir()) / f"chamber-hil-{stamp}"
    return Evidence(directory)


@pytest.fixture(scope="session", autouse=True)
def chamber_guard(request):
    """Pre-check before the first hardware test; STOP + restore after the last."""
    authorization, _ = _authorization()
    if authorization is None:
        yield None
        return
    hil = authorization
    log = request.getfixturevalue("evidence")
    before = direct_status(hil)
    log.log("precheck", **before)
    if before["serial"] != hil.expected_serial:
        pytest.exit("Connected chamber serial does not match CHAMBER_HIL_EXPECTED_SERIAL", returncode=2)
    if before["running"]:
        pytest.exit("Chamber is RUNNING; hardware tests only start from a verified stopped chamber",
                    returncode=2)
    if not hil.temperature_min_c <= before["setpoint_c"] <= hil.temperature_max_c:
        pytest.exit("Chamber setpoint is outside the HIL envelope", returncode=2)
    try:
        yield before
    finally:
        chamber = direct_driver(hil)
        try:
            if chamber.is_running:
                log.log("postcheck_running_direct_stop")
                chamber.stop()
            if abs(chamber.temperature_set_point - before["setpoint_c"]) > 0.05:
                chamber.temperature_set_point = before["setpoint_c"]
                log.log("restored_setpoint", setpoint_c=before["setpoint_c"])
            log.log("postcheck", running=chamber.is_running,
                    measured_c=chamber.temperature_measured)
        finally:
            chamber.disconnect()
        log.log("evidence_dir", path=str(log.directory))


@dataclass
class Stack:
    hil: object
    dashboard: object
    manual: object
    admin: object
    operator: object
    original_setpoint_c: float

    @property
    def chamber_id(self) -> str:
        return self.manual.chamber_id

    def send(self, tokens, action: str, **kw):
        return self.manual.command(tokens.session, tokens.csrf, self.chamber_id, action, **kw)

    def view(self, tokens=None):
        asyncio.run(self.dashboard.poll_once())
        return self.manual.view((tokens or self.admin).session, self.chamber_id)

    def step_target(self, step: float = STEP_C) -> float:
        """A small step from the original setpoint that stays inside the envelope."""
        up = self.original_setpoint_c + step
        return round(up if up <= self.hil.temperature_max_c else self.original_setpoint_c - step, 2)


@pytest.fixture
def stack(hil, evidence, chamber_guard, tmp_path):
    """The real composition root (G04 + G08 + G05) bound to the physical chamber."""
    from chamber_web.bootstrap import create_demo_control_services
    from chamber_web.security.auth import Role, SecurityStore
    from chamber_web.services.manual_control import ManualState

    security = SecurityStore(tmp_path / "security")
    security.bootstrap_admin(*ADMIN)
    admin = security.login(*ADMIN)
    security.create_user(admin.session, admin.csrf, OPERATOR[0], OPERATOR[1], Role.OPERATOR)
    operator = security.login(*OPERATOR)
    real_home = Path(os.environ.get("CHAMBER_TEST_REAL_HOME", str(Path.home())))
    dashboard, manual = create_demo_control_services(
        security, hil, lease_directory=real_home / ".chamber_web" / "ownership")
    built = Stack(hil, dashboard, manual, admin, operator, chamber_guard["setpoint_c"])
    try:
        view = built.view()
        if view.stop_latched:
            # Chamber independently verified STOPPED by the session pre-check.
            outcome = built.send(admin, "reconcile")
            evidence.log("startup_reconcile", state=outcome.state.value)
            assert outcome.state is ManualState.CONFIRMED, outcome.message
        yield built
    finally:
        try:
            outcome = built.send(admin, "stop")
            evidence.log("teardown_stop", state=outcome.state.value, message=outcome.message)
        finally:
            asyncio.run(dashboard.close())
