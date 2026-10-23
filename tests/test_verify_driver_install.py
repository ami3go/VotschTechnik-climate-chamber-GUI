"""Offline, deterministic driver installation diagnostics; no chamber I/O."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock

from scripts import verify_driver_install as check

PIN = "b56cfbd54570e66cddf83106505487d3b19d9677"


class DiscoveryInstallationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.requirements = Path(tmp.name) / "requirements-hardware.txt"
        self.requirements.write_text(
            "VotschTechnikClimateChamber @ git+https://github.com/"
            "ami3go/VotschTechnik-climate-chamber-Python.git@" + PIN + "\n",
            encoding="utf-8",
        )

    def installed_dist(self, sha=PIN):
        return types.SimpleNamespace(read_text=lambda key: json.dumps({
            "vcs_info": {"commit_id": sha}}) if key == "direct_url.json" else None)

    def test_reads_exact_pinned_revision(self):
        self.assertEqual(check.expected_driver_commit(self.requirements), PIN)

    def test_rejects_unpinned_or_ambiguous_requirement(self):
        for value in ("VotschTechnikClimateChamber==0.2.0",
                      "# no VCS pin\n",
                      "VotschTechnikClimateChamber @ git+https://example.com/test.git@" + PIN):
            with self.subTest(value=value):
                self.requirements.write_text(value + "\n", encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, "exactly one"):
                    check.expected_driver_commit(self.requirements)

    def test_healthy_discovery_import_and_git_revision(self):
        module = types.SimpleNamespace(__file__="/installed/discovery.py",
                                       discover_chambers=lambda: ())
        with (mock.patch.object(check, "import_module", return_value=module),
              mock.patch.object(check, "distribution", return_value=self.installed_dist())):
            self.assertIn("Driver discovery OK", check.verify_driver_install(
                requirements=self.requirements))

    def test_old_same_version_package_fails_revision_check(self):
        module = types.SimpleNamespace(discover_chambers=lambda: [])
        with (mock.patch.object(check, "import_module", return_value=module),
              mock.patch.object(check, "distribution",
                                return_value=self.installed_dist("0" * 40))):
            with self.assertRaisesRegex(RuntimeError, "revision mismatch"):
                check.verify_driver_install(requirements=self.requirements)

    def test_missing_discovery_fails_and_does_not_touch_hardware(self):
        with mock.patch.object(check, "import_module",
                               side_effect=ImportError("discovery not found")):
            with self.assertRaisesRegex(RuntimeError, "Driver discovery import failed"):
                check.verify_driver_install(requirements=self.requirements)


if __name__ == "__main__":
    unittest.main()
