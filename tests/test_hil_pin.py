"""No hardware / network: PIN lifecycle, expiry, permissions and isolation."""
from __future__ import annotations

import json
import os
import select
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from chamber_web.hil.pin import (HilPinError, TTL, issue_pin, require_hil_pin,
                                 revoke_pin, state_path, verify_pin)
from scripts import hil_lab_acceptance, hil_soak


class HilPinTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "state" / "hil-pin.json"
        self.now = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)

    def test_issue_validate_and_expire_exactly_24h(self):
        pin, expiry = issue_pin(path=self.path, now=self.now)
        self.assertEqual(len(pin), 8)
        self.assertTrue(pin.isdigit())
        self.assertEqual(expiry, self.now + TTL)
        verify_pin(pin, path=self.path, now=expiry - timedelta(microseconds=1))
        with self.assertRaises(HilPinError):
            verify_pin(pin, path=self.path, now=expiry)

    def test_missing_wrong_and_early_pin_fail(self):
        with self.assertRaises(HilPinError):
            verify_pin("12345678", path=self.path, now=self.now)
        pin, _ = issue_pin(path=self.path, now=self.now)
        with self.assertRaises(HilPinError):
            verify_pin(None, path=self.path, now=self.now)
        with self.assertRaises(HilPinError):
            verify_pin("not a pin", path=self.path, now=self.now)
        with self.assertRaises(HilPinError):
            verify_pin("999999999", path=self.path, now=self.now)
        with self.assertRaises(HilPinError):
            verify_pin("00000000" if pin != "00000000" else "11111111",
                       path=self.path, now=self.now)
        with self.assertRaises(HilPinError):
            verify_pin(pin, path=self.path, now=self.now - timedelta(seconds=1))

    def test_cannot_overwrite_without_reset_and_rotation_invalidates_old_pin(self):
        old, _ = issue_pin(path=self.path, now=self.now)
        with self.assertRaises(HilPinError):
            issue_pin(path=self.path, now=self.now)
        new, _ = issue_pin(path=self.path, now=self.now + timedelta(minutes=1), reset=True)
        # Extremely rare random collision is handled by regenerating in production.
        if new == old:
            self.skipTest("Random PIN collision")
        with self.assertRaises(HilPinError):
            verify_pin(old, path=self.path, now=self.now + timedelta(minutes=2))
        verify_pin(new, path=self.path, now=self.now + timedelta(minutes=2))

    def test_revoke(self):
        pin, _ = issue_pin(path=self.path, now=self.now)
        revoke_pin(path=self.path)
        with self.assertRaises(HilPinError):
            verify_pin(pin, path=self.path, now=self.now)

    def test_state_stores_hash_not_pin_and_restricts_permissions(self):
        pin, _ = issue_pin(path=self.path, now=self.now)
        raw = self.path.read_text()
        self.assertNotIn(pin, raw)
        self.assertEqual(json.loads(raw)["version"], 1)
        if os.name == "posix":
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.path.parent.stat().st_mode & 0o777, 0o700)
            self.path.chmod(0o644)
            with self.assertRaises(HilPinError):
                verify_pin(pin, path=self.path, now=self.now)

    def test_unsafe_state_directory_is_refused_after_issue(self):
        pin, _ = issue_pin(path=self.path, now=self.now)
        if os.name != "posix":
            self.skipTest("POSIX ownership and mode check")
        self.path.parent.chmod(0o755)
        with self.assertRaises(HilPinError):
            verify_pin(pin, path=self.path, now=self.now)

    def test_malformed_state_and_invalid_timestamps_fail_closed(self):
        pin, _ = issue_pin(path=self.path, now=self.now)
        original = json.loads(self.path.read_text(encoding="utf-8"))
        cases = (
            "not-json",
            json.dumps({**original, "expires_at_utc": "not-a-time"}),
            json.dumps({**original, "expires_at_utc": self.now.isoformat()}),
            json.dumps({**original, "digest": "00"}),
        )
        for payload in cases:
            with self.subTest(payload=payload[:30]):
                self.path.write_text(payload, encoding="utf-8")
                with self.assertRaises(HilPinError):
                    verify_pin(pin, path=self.path, now=self.now)
        self.path.write_text(json.dumps(original), encoding="utf-8")

    def test_concurrent_setup_has_exactly_one_winner(self):
        barrier = threading.Barrier(3)
        outcomes = []

        def setup():
            barrier.wait()
            try:
                outcomes.append(("ok", issue_pin(path=self.path, now=self.now)[0]))
            except HilPinError:
                outcomes.append(("denied", None))

        threads = [threading.Thread(target=setup) for _ in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=10)
            self.assertFalse(thread.is_alive())
        self.assertEqual([kind for kind, _ in outcomes].count("ok"), 1)
        self.assertEqual([kind for kind, _ in outcomes].count("denied"), 1)
        verify_pin(next(pin for kind, pin in outcomes if kind == "ok"),
                   path=self.path, now=self.now)

    def test_symlink_state_refused(self):
        other = self.path.parent / "other.json"
        pin, _ = issue_pin(path=self.path, now=self.now)
        self.path.rename(other)
        try:
            self.path.symlink_to(other)
        except (OSError, NotImplementedError):
            self.skipTest("No symlink support")
        with self.assertRaises(HilPinError):
            verify_pin(pin, path=self.path, now=self.now)

    def test_env_gate(self):
        with patch("chamber_web.hil.pin.state_path", return_value=self.path):
            pin, _ = issue_pin(path=self.path, now=datetime.now(timezone.utc))
            require_hil_pin({"CHAMBER_HIL_PIN": pin})
            with self.assertRaises(HilPinError):
                require_hil_pin({})
            with self.assertRaises(HilPinError):
                require_hil_pin({"CHAMBER_HIL_PIN": "123"})
        
    def test_direct_soak_without_pin_never_reaches_chamber_authorization(self):
        with patch("chamber_web.hil.pin.state_path", return_value=self.path), \
             patch.object(hil_soak, "hil_authorization_from_env") as authorization, \
             patch.dict(os.environ, {}, clear=True):
            result = hil_soak.main(["--evidence", str(self.path.parent / "evidence")])
        self.assertEqual(result, 2)
        authorization.assert_not_called()
        self.assertFalse((self.path.parent / "evidence").exists())

    def test_direct_soak_wrong_pin_rejected_before_chamber_authorization(self):
        pin, _ = issue_pin(path=self.path, now=datetime.now(timezone.utc))
        wrong = "00000000" if pin != "00000000" else "99999999"
        with patch("chamber_web.hil.pin.state_path", return_value=self.path), \
             patch.object(hil_soak, "hil_authorization_from_env") as authorization, \
             patch.dict(os.environ, {"CHAMBER_HIL_PIN": wrong}, clear=True):
            result = hil_soak.main(["--evidence", str(self.path.parent / "evidence")])
        self.assertEqual(result, 2)
        authorization.assert_not_called()

    def test_direct_soak_valid_pin_reaches_only_configuration_gate(self):
        pin, _ = issue_pin(path=self.path, now=datetime.now(timezone.utc))
        with patch("chamber_web.hil.pin.state_path", return_value=self.path), \
             patch.object(hil_soak, "hil_authorization_from_env",
                          return_value=None) as authorization, \
             patch.dict(os.environ, {"CHAMBER_HIL_PIN": pin}, clear=True):
            result = hil_soak.main(["--evidence", str(self.path.parent / "evidence")])
        self.assertEqual(result, 2)
        authorization.assert_called_once()
        self.assertFalse((self.path.parent / "evidence").exists())

    def test_full_acceptance_without_pin_never_reaches_hil_configuration(self):
        evidence = self.path.parent / "acceptance"
        with patch.object(hil_lab_acceptance, "require_hil_pin",
                          side_effect=HilPinError("denied")), \
             patch.object(hil_lab_acceptance, "hil_authorization_from_env") as authorization, \
             patch.dict(os.environ, {}, clear=True):
            result = hil_lab_acceptance.main(["--evidence", str(evidence)])
        self.assertEqual(result, 2)
        authorization.assert_not_called()
        self.assertFalse(evidence.exists())

    @unittest.skipUnless(os.name == "posix" and shutil.which("bash") and shutil.which("flock"),
                         "POSIX bash/flock bench serialization")
    def test_wrapper_serializes_concurrent_runs_and_survives_new_process(self):
        home = self.path.parent / "home"
        state = home / ".local" / "state" / "votsch-climate-chamber" / "hil-pin.json"
        pin, _ = issue_pin(path=state, now=datetime.now(timezone.utc))
        env = {**os.environ, "HOME": str(home), "PYTHON": sys.executable,
               "CHAMBER_HIL_PIN": pin}
        first = subprocess.Popen(
            ["bash", "scripts/hil_pin.sh", "run", "--", sys.executable, "-c",
             "import time; print('LOCKED', flush=True); time.sleep(10)"],
            cwd=Path(__file__).resolve().parents[1], env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            ready, _, _ = select.select([first.stdout], [], [], 5)
            self.assertTrue(ready, "first wrapper did not acquire the bench lock")
            self.assertEqual(first.stdout.readline().strip(), "LOCKED")
            second = subprocess.run(
                ["bash", "scripts/hil_pin.sh", "run", "--", sys.executable,
                 "-c", "print('unexpected')"],
                cwd=Path(__file__).resolve().parents[1], env=env,
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(second.returncode, 2)
            self.assertIn("bench busy", second.stderr)
            self.assertNotIn(pin, second.stdout + second.stderr)
        finally:
            first.terminate()
            first.wait(timeout=10)
            first.stdout.close()
            first.stderr.close()
        restarted = subprocess.run(
            [sys.executable, "-m", "chamber_web.hil.pin", "verify"],
            cwd=Path(__file__).resolve().parents[1], env=env,
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(restarted.returncode, 0, restarted.stderr)
        self.assertNotIn(pin, restarted.stdout + restarted.stderr)

    def test_operator_pin_changes_require_a_real_terminal(self):
        with patch.object(sys.stdin, "isatty", return_value=False), \
             patch.object(sys.stdout, "isatty", return_value=False):
            with self.assertRaises(HilPinError):
                from chamber_web.hil.pin import _operator_confirmation
                _operator_confirmation("setup")

    def test_default_path_not_controlled_by_env_override(self):
        with patch.dict(os.environ, {"CHAMBER_HIL_PIN_STATE": "/tmp/unsafe"}, clear=False):
            self.assertNotEqual(str(state_path()), "/tmp/unsafe")


if __name__ == "__main__":
    unittest.main()
