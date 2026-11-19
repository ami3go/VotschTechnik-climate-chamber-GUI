"""No hardware / network: PIN lifecycle, expiry, permissions and isolation."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from chamber_web.hil.pin import (HilPinError, TTL, issue_pin, require_hil_pin,
                                 revoke_pin, state_path, verify_pin)


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
        
    def test_default_path_not_controlled_by_env_override(self):
        with patch.dict(os.environ, {"CHAMBER_HIL_PIN_STATE": "/tmp/unsafe"}, clear=False):
            self.assertNotEqual(str(state_path()), "/tmp/unsafe")


if __name__ == "__main__":
    unittest.main()
