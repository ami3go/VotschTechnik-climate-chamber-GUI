"""Adversarial W02 signature/inventory/update checks: no hardware access."""
import json
from pathlib import Path
import tempfile
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts import w02_release as release
from scripts import windows_manifest


class W02ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.bundle = root / "bundle"
        for name in ("ClimateChamberLauncher.exe", "server/ClimateChamberServer.exe",
                     "server/_internal/nicegui/assets/runtime.js",
                     "server/_internal/chamber_web/assets/style.css"):
            path = self.bundle / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"mock bytes")
        files = windows_manifest.files_under(self.bundle)
        (self.bundle / "build-manifest.json").write_text(
            json.dumps({"files": files}), encoding="utf-8")
        (self.bundle / "SHA256SUMS.txt").write_text(
            "".join(f"{digest}  {name}\n" for name, digest in sorted(files.items())),
            encoding="utf-8")
        self.private = Ed25519PrivateKey.generate()
        self.priv = root / "signing.pem"
        self.pub = root / "trusted.pem"
        self.priv.write_bytes(self.private.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()))
        self.pub.write_bytes(self.private.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
        self.sha = "a" * 64
        release.sign(self.bundle, "1.0.0", self.priv, source_sha=self.sha)

    def test_signed_release_and_tampering(self):
        self.assertEqual(release.verify(self.bundle, self.pub)["version"], "1.0.0")
        file = self.bundle / "server/ClimateChamberServer.exe"
        file.write_bytes(b"unexpected")
        with self.assertRaises(ValueError):
            release.verify(self.bundle, self.pub)

    def test_unsigned_manifest_modification_refused(self):
        path = self.bundle / "w02-release.json"
        payload = json.loads(path.read_text())
        payload["version"] = "2.0.0"
        path.write_bytes(release.canonical(payload))
        with self.assertRaises(Exception):
            release.verify(self.bundle, self.pub)

    def test_unexpected_file_rejected(self):
        (self.bundle / "evil.dll").write_bytes(b"x")
        with self.assertRaisesRegex(ValueError, "unexpected"):
            release.verify(self.bundle, self.pub)

    def test_untrusted_key_refused(self):
        other = Ed25519PrivateKey.generate().public_key()
        different = self.bundle.parent / "wrong.pem"
        different.write_bytes(other.public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
        with self.assertRaises(Exception):
            release.verify(self.bundle, different)

    def test_manifest_traversal_and_casefold(self):
        for name in ("../outside", "C:/escape", "/absolute", "a\\b", "a//b"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                release.validate_entries({name: "a" * 64})

    def test_case_insensitive_collision_rejected(self):
        with self.assertRaisesRegex(ValueError, "collision"):
            release.validate_entries({"ONE.dll": "a" * 64, "one.DLL": "b" * 64})

    def test_downgrade_refused_before_backup(self):
        new = self.bundle.parent / "candidate"
        import shutil
        shutil.copytree(self.bundle, new)
        release.sign(new, "0.9.0", self.priv, source_sha=self.sha)
        backup = self.bundle.parent / "previous"
        with self.assertRaisesRegex(ValueError, "Downgrade"):
            release.stage_update(self.bundle, new, self.pub, backup)
        self.assertFalse(backup.exists())

    def test_upgrade_stages_verified_backup(self):
        new = self.bundle.parent / "candidate"
        import shutil
        shutil.copytree(self.bundle, new)
        release.sign(new, "1.1.0", self.priv, source_sha=self.sha)
        backup = self.bundle.parent / "previous"
        release.stage_update(self.bundle, new, self.pub, backup)
        self.assertEqual(release.verify(backup, self.pub)["version"], "1.0.0")


if __name__ == "__main__":
    unittest.main()
