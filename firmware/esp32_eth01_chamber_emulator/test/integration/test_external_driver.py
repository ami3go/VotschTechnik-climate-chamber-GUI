"""Real, unmodified vendor-driver-over-TCP interoperability with native C++ core.

Run from repository root after compiling tcp_reference; set DRIVER_SRC to checkout.
Never contacts a physical chamber; reference server binds the local test host.
"""
import os
import ipaddress
import socket
import subprocess
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
FIRMWARE = ROOT / "firmware/esp32_eth01_chamber_emulator"
DRIVER_SRC = Path(os.environ.get("DRIVER_SRC", str(ROOT / "external-driver")))
sys.path.insert(0, str(DRIVER_SRC))

from VotschTechnikClimateChamber.ClimateChamber import ClimateChamber, StopNotVerified
from VotschTechnikClimateChamber.discovery import discover_chambers
from VotschTechnikClimateChamber.transport import ChamberTransportError

BIN = str(FIRMWARE / "build/tcp_reference")


def private_ip():
    # Discover a local RFC1918 address without scanning or sending packets.
    for dest in ("10.255.255.254", "192.168.255.254", "172.31.255.254"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect((dest, 9))
                ip = s.getsockname()[0]
                if ipaddress.IPv4Address(ip).is_private and not ipaddress.IPv4Address(ip).is_loopback:
                    return ip
        except OSError:
            pass
    return None


class Integration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.proc = subprocess.Popen([BIN], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        ready = cls.proc.stdout.readline().strip()
        if ready != "REFERENCE TCP 2049 READY":
            cls.proc.terminate()
            raise RuntimeError("Reference server failed to start: " + ready)
        cls.ip = private_ip()

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        try:
            cls.proc.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            cls.proc.kill(); cls.proc.communicate(timeout=3)

    def chamber(self, host="127.0.0.1"):
        return ClimateChamber(host, -40, 180, timeout=0.5)

    def test_driver_identity_temperature_and_repeated_start_stop(self):
        c = self.chamber()
        try:
            self.assertEqual(c.test_system_type, "VT4011-EMULATOR")
            self.assertEqual(c.serial_number, "SIMESP0001")
            self.assertEqual(c.year_manufactured, "2026")
            c.temperature_set_point = 25.5
            self.assertEqual(c.temperature_set_point, 25.5)
            self.assertAlmostEqual(c.temperature_measured, 23.0, places=1)
            c.gradient_up = 3.0
            c.gradient_down = 2.0
            self.assertEqual(c.gradient_up, 3.0)
            self.assertEqual(c.gradient_down, 2.0)
            for _ in range(3):
                c.start()
                self.assertTrue(c.is_running)
                c.stop(verify_timeout=1)
                self.assertFalse(c.is_running)
        finally:
            c.disconnect()
        c = self.chamber()
        try:
            self.assertFalse(c.is_running)
        finally:
            c.disconnect()

    def test_private_direct_ip_and_subnet_discovery(self):
        if self.ip is None:
            self.skipTest("No RFC1918 interface on host; driver forbids loopback discovery")
        found = discover_chambers(self.ip)
        self.assertTrue(any(x.serial_number == "SIMESP0001" for x in found))
        subnet = str(ipaddress.ip_network(self.ip + "/24", strict=False))
        found_subnet = discover_chambers(subnet)
        self.assertTrue(any(x.address == self.ip for x in found_subnet))


class AmbiguousStop(unittest.TestCase):
    def test_stop_reply_lost_is_not_success(self):
        process = subprocess.Popen([BIN, "--drop-stop-reply"], stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True)
        try:
            ready = process.stdout.readline().strip()
            self.assertEqual(ready, "REFERENCE TCP 2049 READY")
            c = ClimateChamber("127.0.0.1", -40, 180, timeout=0.5)
            try:
                c.start()
                with self.assertRaises(StopNotVerified):
                    c.stop(verify_timeout=0.6)
            finally:
                c.disconnect()
        finally:
            process.terminate()
            try: process.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill(); process.communicate(timeout=3)


if __name__ == "__main__":
    unittest.main()
