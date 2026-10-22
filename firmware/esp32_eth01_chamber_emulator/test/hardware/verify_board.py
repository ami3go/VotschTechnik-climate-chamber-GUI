"""Opt-in physical ESP32-ETH01 emulator check, NEVER a real chamber HIL test.

Requires local, physical 3.3 V UART readback matching IP and serial.
No GUI authorization or generic 'simulation_only' bypass is granted.
All commands use maintained external Vötsch Python driver exclusively.
Run only under scripts/h02_watchdog_command.py with test evidence logging.
"""
from __future__ import annotations
import argparse
import ipaddress
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ip", required=True)
    parser.add_argument("--uart-port", required=True, help="physical USB-UART COMx or /dev/ttyUSBx")
    parser.add_argument("--serial", required=True, help="expected emulator serial number")
    parser.add_argument("--allow-writes", action="store_true", help="permit limited emulator Start/Stop cycle tests")
    parser.add_argument("--ack-isolated-test-lan", action="store_true", required=True)
    parser.add_argument("--ack-physical-uart", action="store_true", required=True)
    parser.add_argument("--evidence", default="test-evidence/esp32-emulator/physical-board.json")
    args = parser.parse_args()
    if os.environ.get("ESP_EMULATOR_HARDWARE_OPT_IN") != "1":
        parser.error("ESP_EMULATOR_HARDWARE_OPT_IN=1 required")
    if not (args.ack_isolated_test_lan and args.ack_physical_uart):
        parser.error("both isolation and physical-UART acknowledgments required")
    try:
        address = ipaddress.ip_address(args.ip)
    except ValueError:
        parser.error("invalid IPv4 address")
    if (not isinstance(address, ipaddress.IPv4Address) or
        not any(address in ipaddress.ip_network(s) for s in (
            "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))):
        parser.error("private RFC1918 IPv4 address required")
    if re.fullmatch(r"[A-Za-z0-9]{1,40}", args.serial) is None:
        parser.error("expected serial must be alphanumeric, 1..40")

    import serial
    from VotschTechnikClimateChamber.ClimateChamber import ClimateChamber
    report = {
        "start_utc": datetime.now(timezone.utc).isoformat(),
        "ip": args.ip, "expected_serial": args.serial,
        "evidence": "physical UART + unmodified driver TCP",
        "writes_requested": bool(args.allow_writes),
        "status": "FAIL", "tests": [],
    }
    evidence_path = Path(args.evidence)
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    device = None
    command_started = False
    try:
        with serial.Serial(args.uart_port, 115200, timeout=0.25, write_timeout=0.5) as uart:
            uart.reset_input_buffer()
            uart.write(b"status\r\n")
            deadline = time.monotonic() + 6
            uart_status = None
            while time.monotonic() < deadline:
                line = uart.readline().decode("utf-8", "replace").strip()
                if line.startswith("ESP-EMU ") and "ipReady=1" in line and "MAC=" in line:
                    uart_status = line
                    break
            if not uart_status:
                raise RuntimeError("No live ESP-EMU UART diagnostics with Ethernet IP readiness")
            tokens = dict(p.split("=", 1) for p in uart_status.split() if "=" in p)
            if tokens.get("IP") != args.ip or tokens.get("SN") != args.serial or tokens.get("link") != "1":
                raise RuntimeError("Out-of-band UART IP/serial/link does not match requested endpoint")
            if not re.fullmatch(r"[0-9A-Fa-f:]{17}", tokens.get("MAC", "")):
                raise RuntimeError("Invalid MAC in physical UART diagnostics")
            report["uart"] = uart_status
            report["tests"].append("UART identity and Ethernet status: PASS")

        device = ClimateChamber(args.ip, -40, 180, timeout=0.75)
        if device.serial_number != args.serial or device.test_system_type != "VT4011-EMULATOR":
            raise RuntimeError("Driver identity does not match physical UART enrollment")
        report["tests"].append("Driver identity and discovery: PASS")
        measured = device.temperature_measured
        target = device.temperature_set_point
        up, down = device.gradient_up, device.gradient_down
        if not all(-40 <= x <= 180 for x in (measured, target)):
            raise RuntimeError("Temperature outside configured emulator range")
        report["tests"].append("Driver read-only telemetry: PASS")
        report["readings"] = {"measured": measured, "target": target, "gradient_up": up, "gradient_down": down}
        if args.allow_writes:
            if device.is_running:
                raise RuntimeError("Must be STOPPED before emulator write test")
            for i in range(3):
                device.start()
                command_started = True
                if not device.is_running:
                    raise RuntimeError("RUNNING readback not verified")
                device.stop(verify_timeout=2)
                command_started = False
                if device.is_running:
                    raise RuntimeError("STOPPED readback not verified")
            report["tests"].append("3 Start/Stop/Start cycles: PASS")
        report["status"] = "PASS"
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        print(f"FAIL: {report['error']}", file=sys.stderr)
        return_code = 1
    else:
        return_code = 0
    finally:
        if device:
            if command_started:
                try:
                    device.stop(verify_timeout=2)
                except Exception as exc:
                    report["stop_verification"] = f"UNKNOWN: {type(exc).__name__}: {exc}"
                    report["status"] = "FAIL"
                    return_code = 1
            try:
                device.disconnect()
            except Exception:
                pass
        report["end_utc"] = datetime.now(timezone.utc).isoformat()
        evidence_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"ESP-EMU board verification: {report['status']}; evidence {evidence_path}")
    return return_code

if __name__ == "__main__":
    sys.exit(main())
