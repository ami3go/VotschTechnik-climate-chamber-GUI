"""W02 build-tool lock negative tests; offline with no hardware."""
from __future__ import annotations

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.w02_build_tools import verify_build_wheelhouse


class BuildWheelhouseTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.wheelhouse = self.root / "wheelhouse"
        self.wheelhouse.mkdir()
        self.lock = self.root / "builder.lock"

    def _wheel(self):
        data = b"test wheel fixture"
        path = self.wheelhouse / "pyinstaller-6.16.0-py3-none-any.whl"
        path.write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        self.lock.write_text(
            f"pyinstaller==6.16.0 --hash=sha256:{digest}\n", encoding="utf-8")
        return path

    def test_exact_lock(self):
        self._wheel()
        self.assertEqual(verify_build_wheelhouse(
            self.lock, self.wheelhouse, required=("PyInstaller",)), 1)

    def test_missing_wheel(self):
        self._wheel().unlink()
        with self.assertRaisesRegex(ValueError, "Missing"):
            verify_build_wheelhouse(self.lock, self.wheelhouse)

    def test_modified_wheel(self):
        self._wheel().write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            verify_build_wheelhouse(self.lock, self.wheelhouse)

    def test_extra_wheel(self):
        self._wheel()
        (self.wheelhouse / "other-1.0-py3-none-any.whl").write_bytes(b"x")
        with self.assertRaisesRegex(ValueError, "Unexpected"):
            verify_build_wheelhouse(self.lock, self.wheelhouse)

    def test_unhashed_lock(self):
        self._wheel()
        self.lock.write_text("pyinstaller==6.16.0\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "exact version"):
            verify_build_wheelhouse(self.lock, self.wheelhouse)

    def test_required_tool_missing(self):
        self._wheel()
        with self.assertRaisesRegex(ValueError, "required distributions"):
            verify_build_wheelhouse(
                self.lock, self.wheelhouse, required=("setuptools",))

    def test_duplicate_distribution(self):
        self._wheel()
        (self.wheelhouse / "pyinstaller-6.16.0-py2-none-any.whl").write_bytes(b"x")
        with self.assertRaisesRegex(ValueError, "Duplicate wheel"):
            verify_build_wheelhouse(self.lock, self.wheelhouse)

    def test_symlink_entry_rejected(self):
        wheel = self._wheel()
        other = self.wheelhouse / "other-1.0-py3-none-any.whl"
        try:
            other.symlink_to(wheel)
        except (OSError, NotImplementedError):
            self.skipTest("Symlink creation unsupported")
        with self.assertRaisesRegex(ValueError, "symlink"):
            verify_build_wheelhouse(self.lock, self.wheelhouse)


if __name__ == "__main__":
    unittest.main()
