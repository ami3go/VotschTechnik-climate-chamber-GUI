"""Explicit opt-in physical Leonardo/W5500 chamber emulator verification.

Never authorize real chamber HIL or GUI simulator mode. Requires an isolated
test LAN and live physical USB CDC console matching driver TCP identity.
Run this script through scripts/h02_watchdog_command.py.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import ipaddress
import json
import os
from pathlib import Path
import re
import sys
import time


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ip", required=True)
    parser.add_argument("--usb-port", required=True, help="Leonardo USB CDC port: COMx or /dev/ttyACMx")
    parser.add_argument("--serial", default="SIMLEO0001", help="expected alphanumeric EEPROM identity")
    parser.add_argument("--allow-writes", action="store_true")
    parser.add_argument("--ack-isolated-test-lan", action="store_true", required=True)
    parser.add_argument("--ack-physical-usb", action="store_true", required=True)
    parser.add_argument("--evidence", default="test-evidence/leonardo/physical-board.json")
    args = parser.parse_args()
    if os.environ.get("LEONARDO_EMULATOR_HARDWARE_OPT_IN") != "1":
        parser.error("LEONARDO_EMULATOR_HARDWARE_OPT_IN=1 required")
    if not args.ack_isolated_test_lan or not args.ack_physical_usb:
        parser.error("physical USB and isolated LAN acknowledgments required")
    try:
        ip = ipaddress.ip_address(args.ip)
    except ValueError:
        parser.error("invalid IP address")
    allowed = [ipaddress.ip_network(x) for x in
               ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]
    if not isinstance(ip, ipaddress.IPv4Address) or not any(ip in a for a in allowed):
        parser.error("Private RFC1918 IPv4 target required")
    if re.fullmatch(r"[A-Za-z0-9]{1,16}", args.serial) is None:
        parser.error("serial must be 1..16 alphanumeric")

    import serial
    from VotschTechnikClimateChamber.ClimateChamber import ClimateChamber
    from VotschTechnikClimateChamber.discovery import discover_chambers

    def read_usb_status():
        with serial.Serial(args.usb_port, 115200, timeout=0.25, write_timeout=0.5) as port:
            # Some Leonardo CDC revisions reset on port open.
            deadline = time.monotonic() + 18
            while time.monotonic() < deadline:
                port.write(b"status\n")
                line = port.readline().decode("ascii", errors="replace").strip()
                if line.startswith("LEO-EMU ") and "link=" in line and "SN=" in line:
                    fields = dict(piece.split("=", 1) for piece in line.split() if "=" in piece)
                    if fields.get("IP") != args.ip or fields.get("SN") != args.serial:
                        raise RuntimeError(
                            "Out-of-band USB status did not match target IP/serial")
                    # A CDC open or recent board reset can expose an early
                    # matching-identity status line before DHCP/link settles.
                    # Wait for that same board to report link readiness.
                    if fields.get("link") == "1":
                        return line, fields
        raise RuntimeError("No live LEO-EMU USB-CDC status response")

    evidence = Path(args.evidence)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "utc": datetime.now(timezone.utc).isoformat(),
        "target_ip": args.ip,
        "serial": args.serial,
        "status": "FAIL",
        "writes_enabled": args.allow_writes,
        "checks": [],
    }
    chamber = None
    control_write_attempted = False
    rc = 1
    try:
        found, _ = read_usb_status()
        report["usb_status"] = found
        report["checks"].append("Live physical USB-CDC identity matches isolated Ethernet: PASS")

        listed = discover_chambers(args.ip)
        if len(listed) != 1 or listed[0].serial_number != args.serial:
            raise RuntimeError("Existing driver discovery did not verify matching simulator identity")
        report["checks"].append("Current driver read-only direct-IP discovery: PASS")
        chamber = ClimateChamber(args.ip, -40, 180, timeout=0.75)
        if chamber.serial_number != args.serial or chamber.test_system_type != "VT4011-EMULATOR":
            raise RuntimeError("Driver reported identity mismatch")
        report["initial_temperature"] = chamber.temperature_measured
        report["target_temperature"] = chamber.temperature_set_point
        report["gradient_up"] = chamber.gradient_up
        report["gradient_down"] = chamber.gradient_down
        report["checks"].append("Driver TCP identity, temperature, gradient: PASS")
        if args.allow_writes:
            if chamber.is_running:
                raise RuntimeError("Refusing Start/Stop tests unless emulator is initially STOPPED")
            for cycle in range(1, 4):
                report["control_stage"] = f"cycle {cycle} START write"
                # A timed-out write may still have executed. Mark the board as
                # requiring STOP before the write, not only after its ACK.
                control_write_attempted = True
                chamber.start()
                report["control_stage"] = f"cycle {cycle} START readback"
                if not chamber.is_running:
                    raise RuntimeError("Start not verified by output 1")
                report["control_stage"] = f"cycle {cycle} STOP write/readback"
                chamber.stop(verify_timeout=2)
                if chamber.is_running:
                    raise RuntimeError("Stop not verified by output 1")
            report["checks"].append("3 repeated START/STOP readbacks: PASS")
        report["status"] = "PASS"
        rc = 0
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        print("FAIL:", report["error"], file=sys.stderr)
    finally:
        if chamber:
            try:
                chamber.disconnect()
            except Exception:
                pass
        if control_write_attempted:
            recovery = None
            try:
                # Always use a new TCP session. The maintained driver closes a
                # session after an ambiguous exchange, so reusing it cannot
                # establish STOP. STOP is idempotent for this simulator.
                # Recovery may replace a half-closed W5500 session. Keep this
                # bounded but longer than an ordinary exchange deadline.
                recovery = ClimateChamber(args.ip, -40, 180, timeout=2.0)
                recovery.stop(verify_timeout=2)
                report["recovery_stop"] = "PASS: fresh driver session verified STOPPED"
            except Exception as exc:
                report["status"] = "FAIL"
                rc = 1
                report["recovery_stop"] = f"FAIL: {type(exc).__name__}: {exc}"
            finally:
                if recovery:
                    try:
                        recovery.disconnect()
                    except Exception:
                        pass
            try:
                final_status, final_fields = read_usb_status()
                report["final_usb_status"] = final_status
                if final_fields.get("RUN") != "0":
                    raise RuntimeError("Final out-of-band USB state was not STOPPED")
                report["checks"].append("Final independent USB RUN=0: PASS")
            except Exception as exc:
                report["status"] = "FAIL"
                rc = 1
                report["final_usb_status"] = f"FAIL: {type(exc).__name__}: {exc}"
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        evidence.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"{report['status']}: wrote {evidence}")
    return rc


if __name__ == "__main__":
    sys.exit(run())
