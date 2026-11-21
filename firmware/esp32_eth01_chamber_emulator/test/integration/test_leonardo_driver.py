"""Unmodified Vötsch Python driver talks to exact AVR core over real host TCP.

Requires external-driver checkout pinned by CI. This is not hardware HIL.
"""
import ipaddress
import os
import socket
import subprocess
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
DRIVER_SRC = Path(os.environ.get("DRIVER_SRC", str(ROOT / "external-driver")))
sys.path.insert(0, str(DRIVER_SRC))

from VotschTechnikClimateChamber.ClimateChamber import ClimateChamber, StopNotVerified
from VotschTechnikClimateChamber.discovery import discover_chambers
from VotschTechnikClimateChamber.transport import ChamberTransportError

BIN = str(ROOT / "firmware/esp32_eth01_chamber_emulator/build/leonardo_tcp_reference")


def private_ip():
    for dest in ("10.255.255.254", "192.168.255.254", "172.31.255.254"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as conn:
                conn.connect((dest, 9))
                address = conn.getsockname()[0]
                if ipaddress.IPv4Address(address).is_private and not ipaddress.IPv4Address(address).is_loopback:
                    return address
        except OSError:
            pass
    return None


class _ReferenceServer:
    def start_server(self, *args):
        self.process = subprocess.Popen(
            [BIN, *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        ready = self.process.stdout.readline().strip()
        if ready != "LEONARDO REFERENCE TCP 2049 READY":
            self.process.terminate()
            raise RuntimeError("Reference server unavailable: " + ready)

    def stop_server(self):
        self.process.terminate()
        try:
            self.process.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.communicate(timeout=3)


class TestLeonardoDriver(_ReferenceServer, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.start_server(cls)
        cls.ip = private_ip()

    @classmethod
    def tearDownClass(cls):
        cls.stop_server(cls)

    def test_driver_identity_control_and_reconnect(self):
        c = ClimateChamber("127.0.0.1", -40, 180, timeout=0.75)
        try:
            self.assertEqual(c.test_system_type, "VT4011-EMULATOR")
            self.assertEqual(c.serial_number, "SIMLEO0001")
            self.assertEqual(c.year_manufactured, "2026")
            self.assertAlmostEqual(c.temperature_measured, 23.0, delta=2)
            c.temperature_set_point = 27.25
            self.assertEqual(c.temperature_set_point, 27.25)
            c.gradient_up = 3.0
            c.gradient_down = 2.0
            self.assertEqual(c.gradient_up, 3.0)
            self.assertEqual(c.gradient_down, 2.0)
            self.assertEqual(c.gradient_up_range, (0.01, 5.0))
            self.assertEqual(c.gradient_down_range, (0.01, 3.5))
            self.assertEqual(c.number_of_digital_outputs, 8)
            names = [c.digital_output_name(n) for n in range(1, 9)]
            self.assertEqual(names[0], "Running")
            self.assertEqual(names[6:], ["Compressed air", "Dryer"])
            self.assertTrue(all(names))
            c.set_digital_output(2, True)
            self.assertIs(c.read_digital_output(2), True)
            c.set_digital_output(2, False)
            self.assertIs(c.read_digital_output(2), False)
            for _ in range(2):
                c.start()
                self.assertTrue(c.is_running)
                c.stop(verify_timeout=1.5)
                self.assertFalse(c.is_running)
            c.dryer = True
            self.assertTrue(c.dryer)
            c.compressed_air = True
            self.assertTrue(c.compressed_air)
        finally:
            c.disconnect()
        c = ClimateChamber("127.0.0.1", -40, 180, timeout=0.75)
        try:
            self.assertFalse(c.is_running)
            self.assertEqual(c.serial_number, "SIMLEO0001")
        finally:
            c.disconnect()

    def test_bounded_repeated_tcp_queries_remain_live(self):
        c = ClimateChamber("127.0.0.1", -40, 180, timeout=0.75)
        try:
            for _ in range(1000):
                self.assertEqual(c.query("GET CONTROL_VARIABLE ACTUAL_VALUE", 1), ["23.000"])
        finally:
            c.disconnect()

    def test_discovery_uses_unmodified_driver(self):
        if not self.ip:
            self.skipTest("No RFC1918 address; current driver intentionally rejects loopback discovery")
        direct = discover_chambers(self.ip)
        self.assertTrue(any(d.serial_number == "SIMLEO0001" for d in direct))
        subnet = str(ipaddress.ip_network(self.ip + "/24", strict=False))
        found = discover_chambers(subnet)
        self.assertTrue(any(d.serial_number == "SIMLEO0001" for d in found))


class TestAmbiguousStop(_ReferenceServer, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.start_server(cls, "--drop-stop-reply")

    @classmethod
    def tearDownClass(cls):
        cls.stop_server(cls)

    def test_stop_ack_lost_never_reports_stopped(self):
        c = ClimateChamber("127.0.0.1", -40, 180, timeout=0.5)
        try:
            c.start()
            with self.assertRaises(StopNotVerified):
                c.stop(verify_timeout=0.7)
        finally:
            c.disconnect()


class TestFaultFraming(unittest.TestCase):
    def run_server(self, scenario):
        process = subprocess.Popen(
            [BIN, scenario], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        ready = process.stdout.readline().strip()
        self.assertEqual(ready, "LEONARDO REFERENCE TCP 2049 READY")
        return process

    def stop_server(self, process):
        process.terminate()
        try:
            process.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=3)

    def test_partial_reply_is_transport_failure(self):
        process = self.run_server("--partial-reply")
        try:
            c = ClimateChamber("127.0.0.1", -40, 180, timeout=0.5)
            try:
                with self.assertRaises((ChamberTransportError, RuntimeError, ValueError)):
                    _ = c.serial_number
            finally:
                c.disconnect()
        finally:
            self.stop_server(process)

    def test_invalid_sensor_is_not_temperature(self):
        process = self.run_server("--invalid-sensor")
        try:
            c = ClimateChamber("127.0.0.1", -40, 180, timeout=0.5)
            try:
                with self.assertRaises((ChamberTransportError, RuntimeError, ValueError)):
                    _ = c.temperature_measured
            finally:
                c.disconnect()
        finally:
            self.stop_server(process)

    def test_sticky_stop_is_not_reported_stopped(self):
        process = self.run_server("--sticky-stop")
        try:
            c = ClimateChamber("127.0.0.1", -40, 180, timeout=0.5)
            try:
                c.start()
                with self.assertRaises(StopNotVerified):
                    c.stop(verify_timeout=0.7)
            finally:
                c.disconnect()
        finally:
            self.stop_server(process)


if __name__ == "__main__":
    unittest.main()
