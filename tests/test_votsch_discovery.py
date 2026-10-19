"""Offline unit tests: GUI discovery delegates solely to pinned vendor driver."""
from __future__ import annotations

import sys
import threading
import types
import unittest
from unittest.mock import patch

from chamber_web.adapters import votsch


class AdapterDiscoveryTests(unittest.TestCase):
    def test_calls_external_driver_with_selected_scope(self):
        seen = []
        pkg = types.ModuleType("VotschTechnikClimateChamber")
        pkg.__path__ = []
        discovery = types.ModuleType("VotschTechnikClimateChamber.discovery")
        def fake(network=None):
            seen.append(network)
            return ["device"]
        discovery.discover_chambers = fake
        with patch.dict(sys.modules, {
                "VotschTechnikClimateChamber": pkg,
                "VotschTechnikClimateChamber.discovery": discovery}):
            self.assertEqual(votsch.discover_votsch_chambers("10.42.0.0/24"), ["device"])
        self.assertEqual(seen, ["10.42.0.0/24"])

    def test_unavailable_driver_fails_closed(self):
        with patch.dict(sys.modules, {"VotschTechnikClimateChamber.discovery": None}):
            with self.assertRaisesRegex(RuntimeError, "driver discovery is unavailable"):
                votsch.discover_votsch_chambers()

    def test_parallel_scans_not_allowed(self):
        entered = threading.Event()
        release = threading.Event()
        pkg = types.ModuleType("VotschTechnikClimateChamber")
        pkg.__path__ = []
        discovery = types.ModuleType("VotschTechnikClimateChamber.discovery")
        def slow(network=None):
            entered.set()
            if not release.wait(2):
                raise TimeoutError("test event timed out")
            return []
        discovery.discover_chambers = slow
        with patch.dict(sys.modules, {
                "VotschTechnikClimateChamber": pkg,
                "VotschTechnikClimateChamber.discovery": discovery}):
            worker = threading.Thread(target=votsch.discover_votsch_chambers)
            worker.start()
            try:
                self.assertTrue(entered.wait(1), "test worker never started")
                with self.assertRaisesRegex(RuntimeError, "already running"):
                    votsch.discover_votsch_chambers()
            finally:
                release.set()
                worker.join(timeout=3)
            self.assertFalse(worker.is_alive())


if __name__ == "__main__":
    unittest.main()
