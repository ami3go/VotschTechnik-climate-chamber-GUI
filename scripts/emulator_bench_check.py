"""Explicit opt-in G04 bench check against a *signed* network emulator.

This never authorizes a physical chamber and never uses a HIL PIN. It exercises
the GUI's real ChamberManager/ChamberController/VotschBackend path against the
enrolled bench emulator (for example the Leonardo/W5500 SIMLEO0001 board) and
records separate emulator evidence. Do not present the result as physical HIL,
site acceptance or release approval.

Run it through the bounded watchdog:

    CHAMBER_EMULATOR_ENROLLMENT_FILE=... \
    CHAMBER_EMULATOR_TRUSTED_KEY=... \
    CHAMBER_EMULATOR_ACK=ISOLATED-BENCH-EMULATOR \
    python scripts/h02_watchdog_command.py --timeout-s 180 --idle-timeout-s 60 \
      --log-dir /tmp/opencode/emulator-bench -- \
      python scripts/emulator_bench_check.py --allow-writes \
        --evidence /tmp/opencode/emulator-bench/evidence.json
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chamber_web.adapters.votsch import VotschBackend  # noqa: E402
from chamber_web.domain.chamber import ChamberError, OperationState  # noqa: E402
from chamber_web.domain.config import ChamberConfig  # noqa: E402
from chamber_web.hil.emulator import emulator_authorization_from_env  # noqa: E402
from chamber_web.services.chamber_manager import ChamberManager  # noqa: E402


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(args) -> int:
    authorization = emulator_authorization_from_env(os.environ)
    if authorization is None:
        raise SystemExit("No signed emulator enrollment in the environment")
    if authorization.expected_serial != args.serial:
        raise SystemExit("--serial does not match the signed enrollment")
    evidence = {
        "utc": _utc(),
        "kind": "EMULATOR_BENCH_CHECK",
        "target_ip": authorization.address,
        "serial": authorization.expected_serial,
        "enrollment_sha256": authorization.enrollment_sha256,
        "writes_enabled": bool(args.allow_writes),
        "status": "FAIL",
        "checks": [],
    }
    config = ChamberConfig(authorization.chamber_id, "votsch_emulator",
                           authorization.address)

    def factory(cfg, allow_test_backend=False):
        if cfg != config:
            raise RuntimeError("Unexpected chamber configuration")
        return VotschBackend(cfg.chamber_id, cfg.address, emulator=authorization,
                             gradient_writes=True)

    manager = ChamberManager(
        [config], backend_factory=factory,
        lease_directory=Path(args.lease_directory) if args.lease_directory
        else Path(tempfile.mkdtemp(prefix="emulator-bench-lease-")),
        # The Leonardo W5500 server occasionally needs >2 s for START; this is
        # a bench check, still bounded by the external watchdog.
        io_timeout_s=5.0,
    )
    token = None
    try:
        manager.connect(config.chamber_id)
        identity = manager.status(config.chamber_id).identity
        health = manager.health(config.chamber_id)
        caps = manager.capabilities(config.chamber_id)
        if identity is None or not identity.is_emulator:
            raise RuntimeError("Connected device is not classified as an emulator")
        if identity.serial_number != authorization.expected_serial:
            raise RuntimeError("Connected serial does not match the enrollment")
        if health.state == "UNKNOWN":
            # A fresh lease starts fenced. This is an explicit STOP reconciliation
            # against the emulator, not a bypass of the physical restart fence.
            manager.reconcile_stop(config.chamber_id)
            health = manager.health(config.chamber_id)
        if health.state != "VERIFIED_STOPPED":
            raise RuntimeError(f"Emulator did not report verified STOPPED: {health.state}")
        evidence["checks"].append("G04 connect + emulator identity: PASS")
        evidence["checks"].append("Verified STOPPED before writes: PASS")
        evidence["capabilities"] = {
            "min_c": caps.temperature_min_c, "max_c": caps.temperature_max_c,
            "start_stop": caps.supports_start_stop,
            "setpoint_readback": caps.supports_setpoint_readback,
            "running_readback": caps.supports_running_readback,
            "digital_outputs": [number for number, _ in caps.digital_outputs],
        }
        if not args.allow_writes:
            evidence["status"] = "PASS"
            return 0

        target = float(args.target_c)
        if not (caps.temperature_min_c <= target <= caps.temperature_max_c):
            raise RuntimeError("Target outside the signed emulator envelope")
        token = manager.claim_operator(config.chamber_id, "emulator-bench-check")
        initial = manager.status(config.chamber_id).measured_temperature_c
        evidence["initial_temperature_c"] = initial
        evidence["target_temperature_c"] = target
        manager.set_temperature(config.chamber_id, target, operator_token=token)
        evidence["checks"].append("Setpoint write + readback accepted: PASS")
        manager.start(config.chamber_id, operator_token=token)
        evidence["checks"].append("START + running readback: PASS")
        deadline = time.monotonic() + args.reach_timeout_s
        reached = None
        while time.monotonic() < deadline:
            snapshot = manager.status(config.chamber_id)
            if snapshot.measured_temperature_c is not None:
                reached = snapshot.measured_temperature_c
                if abs(reached - target) <= args.tolerance_c:
                    break
            time.sleep(0.5)
        if reached is None or abs(reached - target) > args.tolerance_c:
            raise RuntimeError(
                f"Emulator did not reach {target:g} °C within "
                f"{args.tolerance_c:g} °C (last {reached!r})")
        evidence["reached_temperature_c"] = reached
        evidence["checks"].append(
            f"Temperature reached within {args.tolerance_c:g} °C: PASS")
        manager.stop(config.chamber_id)
        evidence["stop_status"] = manager.health(config.chamber_id).state
        if manager.health(config.chamber_id).state != "VERIFIED_STOPPED":
            raise RuntimeError("STOP was not authoritatively verified")
        evidence["checks"].append("STOP + authoritative readback: PASS")
        evidence["status"] = "PASS"
        return 0
    except (ChamberError, RuntimeError, OSError, ValueError) as exc:
        evidence["error"] = f"{type(exc).__name__}: {exc}"
        if token is not None:
            try:
                manager.stop(config.chamber_id)
                evidence["stop_status"] = manager.health(config.chamber_id).state
            except Exception as stop_exc:  # noqa: BLE001 - evidence only
                evidence["stop_status"] = f"UNKNOWN: {type(stop_exc).__name__}: {stop_exc}"
        return 1
    finally:
        try:
            manager.disconnect(config.chamber_id)
        except Exception:  # noqa: BLE001 - evidence only
            pass
        if args.evidence:
            path = Path(args.evidence)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(evidence, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", default="SIMLEO0001")
    parser.add_argument("--target-c", type=float, default=24.0)
    parser.add_argument("--reach-timeout-s", type=float, default=60.0)
    parser.add_argument("--tolerance-c", type=float, default=0.2)
    parser.add_argument("--allow-writes", action="store_true")
    parser.add_argument("--lease-directory", default="",
                        help="Optional fresh lease directory; default is a new temp dir")
    parser.add_argument("--evidence", default="")
    args = parser.parse_args()
    if args.reach_timeout_s <= 0 or not math.isfinite(args.reach_timeout_s):
        raise SystemExit("--reach-timeout-s must be finite and positive")
    if args.tolerance_c <= 0 or not math.isfinite(args.tolerance_c):
        raise SystemExit("--tolerance-c must be finite and positive")
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
