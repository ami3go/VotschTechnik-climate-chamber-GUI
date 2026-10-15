"""Real-hardware acceptance tests (opt-in; see tests/hardware/conftest.py).

Ordered from read-only to mutating. Every mutation is a small step inside
the HIL envelope and every test ends with a STOP.
"""
from __future__ import annotations

import math
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from chamber_web.domain.chamber import OperationState, ReadingQuality
from chamber_web.services.manual_control import ManualState

from hil_support import ADMIN, RUN_S, WEB_PORT, direct_status

ROOT = Path(__file__).resolve().parents[2]


# ---- 1. Read-only ---------------------------------------------------------

def test_identity_envelope_and_gradients(stack, evidence):
    view = stack.view()
    identity, caps = view.dashboard.identity, view.dashboard.capabilities
    evidence.log("identity", model=identity.model, serial=identity.serial_number,
                 ramp_c_per_min=caps.setpoint_readback_ramp_c_per_min)
    assert identity.is_simulation is False
    assert identity.backend_id == "votsch"
    assert identity.serial_number == stack.hil.expected_serial
    assert (caps.temperature_min_c, caps.temperature_max_c) == (
        stack.hil.temperature_min_c, stack.hil.temperature_max_c)
    up, down = caps.setpoint_readback_ramp_c_per_min
    assert 0 < up <= 60 and 0 < down <= 60
    assert view.controller_state == "VERIFIED_STOPPED"


def test_telemetry_fresh_stable_and_fast(stack, evidence):
    latencies, measured = [], []
    for _ in range(10):
        started = time.monotonic()
        view = stack.view()
        latencies.append(time.monotonic() - started)
        sample = view.dashboard
        assert sample.quality is ReadingQuality.GOOD
        assert sample.operation_state is OperationState.STOPPED
        assert math.isfinite(sample.measured_temperature_c)
        measured.append(sample.measured_temperature_c)
        time.sleep(0.5)
    evidence.log("telemetry", max_latency_ms=round(1000 * max(latencies)),
                 measured_min=min(measured), measured_max=max(measured))
    assert max(latencies) < 1.0
    assert max(measured) - min(measured) < 1.0  # stopped chamber: no large jumps


# ---- 2. Guarded mutations while stopped ------------------------------------

def test_out_of_envelope_target_never_written(stack, evidence):
    assert stack.send(stack.operator, "claim").state is ManualState.CONFIRMED
    before = stack.view().dashboard.setpoint_temperature_c
    for target in (stack.hil.temperature_max_c + 5, stack.hil.temperature_min_c - 5):
        outcome = stack.send(stack.operator, "set_temperature", target_c=target)
        evidence.log("out_of_envelope", target_c=target, state=outcome.state.value)
        assert outcome.state is not ManualState.CONFIRMED
    after = stack.view().dashboard.setpoint_temperature_c
    assert abs(after - before) < 0.05


def test_command_without_operator_lease_refused(stack):
    # A command without the operator lease must be refused before any I/O.
    outcome = stack.send(stack.admin, "start")
    assert outcome.state is not ManualState.CONFIRMED
    assert stack.view().dashboard.operation_state is OperationState.STOPPED


def test_ramped_setpoint_round_trip_while_stopped(stack, evidence):
    assert stack.send(stack.operator, "claim").state is ManualState.CONFIRMED
    for target in (stack.step_target(), stack.original_setpoint_c):
        started = time.monotonic()
        outcome = stack.send(stack.operator, "set_temperature", target_c=target)
        evidence.log("set_temperature", target_c=target, state=outcome.state.value,
                     seconds=round(time.monotonic() - started, 1))
        assert outcome.state is ManualState.CONFIRMED, outcome.message
        assert abs(stack.view().dashboard.setpoint_temperature_c - target) <= 0.1
    assert stack.view().dashboard.operation_state is OperationState.STOPPED


# ---- 3. Running the chamber -------------------------------------------------

def test_start_run_and_verified_stop(stack, evidence):
    assert stack.send(stack.operator, "claim").state is ManualState.CONFIRMED
    target = stack.step_target()
    assert stack.send(stack.operator, "set_temperature", target_c=target).state is ManualState.CONFIRMED
    outcome = stack.send(stack.operator, "start")
    assert outcome.state is ManualState.CONFIRMED, outcome.message
    deadline = time.monotonic() + RUN_S
    while time.monotonic() < deadline:
        sample = stack.view().dashboard
        assert sample.quality is ReadingQuality.GOOD
        assert sample.operation_state is OperationState.RUNNING
        evidence.log("running", measured_c=sample.measured_temperature_c,
                     setpoint_c=sample.setpoint_temperature_c)
        time.sleep(5)
    outcome = stack.send(stack.operator, "stop")
    evidence.log("stop", state=outcome.state.value)
    assert outcome.state is ManualState.CONFIRMED, outcome.message
    assert stack.view().dashboard.operation_state is OperationState.STOPPED


def test_stop_during_setpoint_ramp_while_running(stack, evidence):
    """STOP must win while G05 is still waiting for a device ramp to settle."""
    assert stack.send(stack.operator, "claim").state is ManualState.CONFIRMED
    assert stack.send(stack.operator, "start").state is ManualState.CONFIRMED
    results = {}
    ramp = threading.Thread(target=lambda: results.setdefault(
        "set", stack.send(stack.operator, "set_temperature", target_c=stack.step_target(2.0))))
    ramp.start()
    time.sleep(2.0)
    started = time.monotonic()
    stop = stack.send(stack.admin, "stop")
    stop_seconds = time.monotonic() - started
    ramp.join(timeout=60)
    evidence.log("stop_during_ramp", stop=stop.state.value, stop_seconds=round(stop_seconds, 2),
                 set=results["set"].state.value)
    assert not ramp.is_alive()
    assert stop.state is ManualState.CONFIRMED, stop.message
    assert stop_seconds < 10
    assert results["set"].state is not ManualState.CONFIRMED
    assert stack.view().dashboard.operation_state is OperationState.STOPPED
    assert stack.send(stack.admin, "reconcile").state is ManualState.CONFIRMED


# ---- 4. Full web stack ------------------------------------------------------

def test_web_ui_claim_set_start_stop(hil, evidence, chamber_guard):
    playwright = pytest.importorskip("playwright.sync_api")
    url = f"http://127.0.0.1:{WEB_PORT}"
    work = Path(tempfile.mkdtemp(prefix="hil-web-"))
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("PYTEST", "NICEGUI_"))}
    env.update({"HOME": os.environ.get("CHAMBER_TEST_REAL_HOME", str(Path.home())),
                "CHAMBER_SECURITY_DIR": str(work / "security"), "CHAMBER_PORT": str(WEB_PORT),
                "CHAMBER_ALLOWED_ORIGINS": url, "PYTHONUNBUFFERED": "1"})
    subprocess.run([sys.executable, "-c", (
        "import sys; from pathlib import Path; from chamber_web.security.auth import SecurityStore;"
        "SecurityStore(Path(sys.argv[1])).bootstrap_admin(sys.argv[2], sys.argv[3])"),
        str(work / "security"), *ADMIN], cwd=ROOT, env=env, check=True)
    log = open(evidence.directory / "web-server.log", "w", encoding="utf-8")
    server = subprocess.Popen([sys.executable, "-m", "main"], cwd=ROOT, env=env,
                              stdout=log, stderr=subprocess.STDOUT)
    target = chamber_guard["setpoint_c"] + 1.0
    if target > hil.temperature_max_c:
        target = chamber_guard["setpoint_c"] - 1.0
    try:
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline and server.poll() is None:
            try:
                urllib.request.urlopen(url + "/login", timeout=1.5)
                break
            except Exception:
                time.sleep(0.3)
        assert server.poll() is None, "HIL web server exited (see web-server.log)"
        with playwright.sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1500, "height": 1000})
            expect = playwright.expect
            body = page.locator("body")
            page.goto(url + "/login")
            page.get_by_label("Username").fill(ADMIN[0])
            page.get_by_label("Password").fill(ADMIN[1])
            page.get_by_role("button", name="Sign in").click()
            expect(body).to_contain_text("SUPERVISED PHYSICAL HIL", timeout=15000)
            page.goto(url + "/admin")
            if "STOP/reconciliation required" in body.inner_text():
                page.get_by_role("button", name="Admin reconcile STOP").click()
                page.get_by_role("button", name="Confirm reconcile").click()
            claim = page.get_by_role("button", name="Claim", exact=True)
            expect(claim).to_be_enabled(timeout=20000)
            claim.click()
            expect(body).to_contain_text("you hold control", timeout=15000)
            page.goto(url + "/")
            page.get_by_label("Target °C").fill(f"{target:g}")
            page.get_by_role("button", name="Set Target").click()
            expect(body).to_contain_text("CONFIRMED · set_temperature", timeout=90000)
            page.get_by_role("button", name="Start", exact=True).click()
            expect(body).to_contain_text("CONFIRMED · start", timeout=20000)
            page.screenshot(path=evidence.directory / "web-running.png", full_page=True)
            evidence.log("web_running", target_c=target)
            time.sleep(min(RUN_S, 30))
            page.get_by_role("button", name="Stop", exact=True).click()
            expect(body).to_contain_text("CONFIRMED · stop", timeout=20000)
            page.screenshot(path=evidence.directory / "web-stopped.png", full_page=True)
            evidence.log("web_stopped")
            browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=15)
        except subprocess.TimeoutExpired:
            server.kill()
        log.close()
    status = direct_status(hil)
    evidence.log("web_postcheck", **status)
    assert status["running"] is False
