"""Run one bounded G06/G07 profile against a signed bench emulator.

This uses the normal VotschBackend, ChamberManager, ProfileExecutionService,
and append-only run journal. It is simulator evidence, not physical HIL, site
acceptance, or release approval. No HIL PIN is used.

The read-only stability preflight must pass before the first mutation. Every
exit attempts a bounded runner-owned STOP and independently verifies STOPPED.
Use ``scripts/h02_watchdog_command.py`` as the outer process watchdog.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import secrets
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chamber_web.adapters.votsch import VotschBackend  # noqa: E402
from chamber_web.domain.chamber import (  # noqa: E402
    ChamberError,
    OperationState,
    ReadingQuality,
)
from chamber_web.domain.config import ChamberConfig  # noqa: E402
from chamber_web.execution.profile_runner import (  # noqa: E402
    TERMINAL,
    RunParameters,
    RunState,
)
from chamber_web.hil.emulator import emulator_authorization_from_env  # noqa: E402
from chamber_web.persistence.profiles import ProfileStore  # noqa: E402
from chamber_web.security.auth import SecurityStore  # noqa: E402
from chamber_web.security.guards import AuthorizedChamber  # noqa: E402
from chamber_web.services.chamber_manager import ChamberManager  # noqa: E402
from chamber_web.services.profile_editor import ProfileEditorService  # noqa: E402
from chamber_web.services.profile_execution import ProfileExecutionService  # noqa: E402
from chamber_web.services.profile_runtime import ProfileRunRuntime  # noqa: E402


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_evidence(evidence: dict, path_text: str) -> None:
    payload = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    if path_text:
        path = Path(path_text)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
    print(payload, end="")


def _assert_stopped(manager: ChamberManager, chamber_id: str) -> None:
    health = manager.health(chamber_id)
    sample = manager.status(chamber_id)
    if (not health.connected or health.stop_latched or
            health.state != "VERIFIED_STOPPED" or
            sample.quality is not ReadingQuality.GOOD or
            sample.operation_state is not OperationState.STOPPED):
        raise RuntimeError("Emulator is not authoritatively STOPPED")


def _stability_preflight(
    manager: ChamberManager,
    chamber_id: str,
    *,
    duration_s: float,
    interval_s: float,
    serial: str,
) -> tuple[int, float | None]:
    """Require uninterrupted fresh identity/STOP readback before any write."""
    deadline = time.monotonic() + duration_s
    samples = 0
    measured = None
    while True:
        sample = manager.status(chamber_id)
        identity = sample.identity
        _assert_stopped(manager, chamber_id)
        if (identity is None or not identity.is_emulator or
                identity.serial_number != serial):
            raise RuntimeError("Emulator identity changed during preflight")
        if sample.measured_temperature_c is None or not math.isfinite(
                sample.measured_temperature_c):
            raise RuntimeError("Emulator temperature is unavailable")
        measured = sample.measured_temperature_c
        samples += 1
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(interval_s, remaining))
    if samples < 2:
        raise RuntimeError("Stability preflight produced fewer than two samples")
    return samples, measured


def _build_profile(
    editor: ProfileEditorService,
    *,
    target_c: float,
    tolerance_c: float,
    reach_timeout_s: float,
):
    """Two steps exercise gradients, output ON/OFF, and run ON/OFF."""
    draft = editor.new_draft()
    draft = editor.set_metadata(draft, "name", "Leonardo emulator G06 check")
    first = (
        ("target_temperature_c", str(target_c)),
        ("tolerance_c", str(tolerance_c)),
        ("ramp_up_c_per_min", "3.0"),
        ("ramp_down_c_per_min", "1.5"),
        ("stabilize_s", "0"),
        ("dwell_s", "1"),
        ("reach_timeout_s", str(reach_timeout_s)),
        ("chamber_run", "ON"),
        ("digital_outputs", "2=ON"),
        ("notes", "Network emulator running step"),
    )
    for field, value in first:
        draft = editor.edit_step(draft, 0, field, value)
    draft = editor.change_step(draft, "add")
    second = (
        ("stabilize_s", "0"),
        ("dwell_s", "1"),
        ("chamber_run", "OFF"),
        ("digital_outputs", "2=OFF"),
        ("notes", "Network emulator restore step"),
    )
    for field, value in second:
        draft = editor.edit_step(draft, 1, field, value)
    return editor.save(draft)


def _restore_stop(
    service: ProfileExecutionService,
    manager: ChamberManager,
    chamber_id: str,
    *,
    deadline_s: float = 15.0,
) -> str:
    """Finish the runner-owned STOP, then independently verify/reconcile it."""
    runner = service.runner
    deadline = time.monotonic() + deadline_s
    if runner is not None and runner.state is not None and runner.state not in TERMINAL:
        runner.request_shutdown_stop(chamber_id)
        while runner.state not in TERMINAL and time.monotonic() < deadline:
            runner.advance()
            time.sleep(0.05)
        if runner.state not in TERMINAL:
            raise RuntimeError("Runner STOP did not reach a terminal state")
    if runner is not None and runner.state in TERMINAL:
        runner.close()
    health = manager.health(chamber_id)
    if health.state != "VERIFIED_STOPPED" or health.stop_latched:
        manager.reconcile_stop(chamber_id)
    _assert_stopped(manager, chamber_id)
    return manager.health(chamber_id).state


def run(args: argparse.Namespace) -> int:
    authorization = emulator_authorization_from_env(os.environ)
    if authorization is None:
        raise SystemExit("No signed emulator enrollment in the environment")
    if authorization.expected_serial != args.serial:
        raise SystemExit("--serial does not match the signed enrollment")
    if not authorization.temperature_min_c <= args.target_c <= authorization.temperature_max_c:
        raise SystemExit("--target-c is outside the signed emulator envelope")

    root = Path(tempfile.mkdtemp(prefix="emulator-profile-check-"))
    evidence: dict = {
        "started_at_utc": _utc(),
        "kind": "EMULATOR_PROFILE_CHECK",
        "target_ip": authorization.address,
        "serial": authorization.expected_serial,
        "enrollment_sha256": authorization.enrollment_sha256,
        "work_directory": str(root),
        "status": "FAIL",
        "mutations_started": False,
        "checks": [],
    }
    config = ChamberConfig(
        authorization.chamber_id, "votsch_emulator", authorization.address)

    def factory(cfg, allow_test_backend=False):
        if cfg != config:
            raise RuntimeError("Unexpected chamber configuration")
        return VotschBackend(
            cfg.chamber_id, cfg.address, emulator=authorization,
            gradient_writes=True)

    manager = ChamberManager(
        [config], backend_factory=factory, lease_directory=root / "lease",
        io_timeout_s=5.0,
    )
    security = SecurityStore(root / "auth")
    password = secrets.token_urlsafe(24) + "Aa1!"
    security.bootstrap_admin("emulator_check", password)
    admin = security.login("emulator_check", password)
    profile_store = ProfileStore(root / "profiles.sqlite3")
    editor = ProfileEditorService(profile_store, config.chamber_id)
    saved = _build_profile(
        editor, target_c=args.target_c, tolerance_c=args.tolerance_c,
        reach_timeout_s=args.reach_timeout_s,
    )
    runtime = ProfileRunRuntime(root / "run-journal")
    service = ProfileExecutionService(
        manager, profile_store, security, config.chamber_id,
        simulation=False, emulator=True,
        manual_guard=AuthorizedChamber(manager, security),
        sink_factory=runtime.sink_factory,
        start_blocker=runtime.start_blocker,
        parameters=RunParameters(
            poll_s=0.2, max_gap_s=2.0, max_age_s=2.0,
            max_run_s=args.timeout_s,
        ),
    )
    connected = False
    result = 1
    try:
        manager.connect(config.chamber_id)
        connected = True
        identity = manager.status(config.chamber_id).identity
        if identity is None or not identity.is_emulator:
            raise RuntimeError("Connected device is not classified as an emulator")
        if manager.health(config.chamber_id).state == "UNKNOWN":
            manager.reconcile_stop(config.chamber_id)
        _assert_stopped(manager, config.chamber_id)
        evidence["checks"].append("G04 signed identity + verified STOPPED: PASS")

        sample_count, initial = _stability_preflight(
            manager, config.chamber_id,
            duration_s=args.preflight_s,
            interval_s=args.preflight_interval_s,
            serial=args.serial,
        )
        evidence["preflight_samples"] = sample_count
        evidence["initial_temperature_c"] = initial
        evidence["checks"].append(
            f"Read-only stability preflight ({sample_count} samples): PASS")

        snapshot = service.start(admin.session, admin.csrf, saved.profile_id, 1)
        evidence["run_id"] = snapshot.run_id
        evidence["checks"].append("G06 signed-emulator admission: PASS")
        runner = service.runner
        if runner is None:
            raise RuntimeError("Profile runner was not created")
        deadline = time.monotonic() + args.timeout_s
        state = runner.state
        while state not in TERMINAL and time.monotonic() < deadline:
            evidence["mutations_started"] = True
            state = runner.advance()
            if state not in TERMINAL:
                time.sleep(0.1)
        if state not in TERMINAL:
            raise RuntimeError("Profile run exceeded its internal deadline")
        evidence["final_state"] = state.value
        if state is not RunState.COMPLETED:
            raise RuntimeError(f"Profile ended in non-success state {state.value}")
        evidence["checks"].append("Two-step profile COMPLETED: PASS")
        _assert_stopped(manager, config.chamber_id)
        evidence["checks"].append("Runner final verified STOPPED: PASS")

        store = runtime.store
        if store is None:
            raise RuntimeError("G07 run journal is unavailable")
        record = store.get_run(config.chamber_id, snapshot.run_id)
        events = store.list_events(config.chamber_id, snapshot.run_id, limit=500)
        evidence["journal_terminal_state"] = record["terminal_state"]
        evidence["journal_event_count"] = len(events)
        if record["terminal_state"] != "COMPLETED":
            raise RuntimeError("G07 did not finalize the run as COMPLETED")
        if not any(event["kind"] == "OUTPUT_INTENT" for event in events):
            raise RuntimeError("G07 did not record output control")
        if not any(event["kind"] == "GRADIENT_INTENT" for event in events):
            raise RuntimeError("G07 did not record gradient control")
        evidence["checks"].append("G07 durable terminal/output/gradient evidence: PASS")
        evidence["status"] = "PASS"
        result = 0
    except (ChamberError, RuntimeError, OSError, ValueError) as exc:
        evidence["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if connected:
            try:
                evidence["restore_state"] = _restore_stop(
                    service, manager, config.chamber_id)
                evidence["checks"].append("Final independent STOP restore: PASS")
            except Exception as exc:  # noqa: BLE001 - preserve primary evidence
                evidence["restore_error"] = f"{type(exc).__name__}: {exc}"
                evidence["status"] = "FAIL"
                result = 1
            try:
                manager.disconnect(config.chamber_id)
            except Exception as exc:  # noqa: BLE001 - evidence only
                evidence["disconnect_error"] = f"{type(exc).__name__}: {exc}"
                evidence["status"] = "FAIL"
                result = 1
        evidence["finished_at_utc"] = _utc()
        _write_evidence(evidence, args.evidence)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", default="SIMLEO0001")
    parser.add_argument("--target-c", type=float, default=24.0)
    parser.add_argument("--tolerance-c", type=float, default=0.5)
    parser.add_argument("--reach-timeout-s", type=float, default=60.0)
    parser.add_argument("--preflight-s", type=float, default=15.0)
    parser.add_argument("--preflight-interval-s", type=float, default=1.0)
    parser.add_argument("--timeout-s", type=float, default=90.0)
    parser.add_argument("--evidence", default="")
    args = parser.parse_args()
    for name in (
        "target_c", "tolerance_c", "reach_timeout_s", "preflight_s",
        "preflight_interval_s", "timeout_s",
    ):
        value = getattr(args, name)
        if not math.isfinite(value):
            raise SystemExit(f"--{name.replace('_', '-')} must be finite")
    if (args.tolerance_c <= 0 or args.reach_timeout_s <= 0 or
            args.preflight_s <= 0 or args.preflight_interval_s <= 0 or
            args.timeout_s <= 0):
        raise SystemExit("All durations and tolerance must be positive")
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
