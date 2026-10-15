"""Adversarial W02 signature/inventory/update checks: no hardware access."""
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts import w02_release as release
from scripts import w02_target_verifier as target_verifier
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


    def test_w01_verifier_requires_explicit_signed_sidecar_allowlist(self):
        # Standalone W01 verification must not begin accepting unsigned extras.
        with self.assertRaisesRegex(ValueError, "Integrity mismatch"):
            windows_manifest.verify_manifest(self.bundle)
        self.assertEqual(release.verify(self.bundle, self.pub)["schema"], 2)

    def test_missing_file_and_truncated_signature_rejected(self):
        missing = self.bundle / "server/_internal/nicegui/assets/runtime.js"
        missing.unlink()
        with self.assertRaises(ValueError):
            release.verify(self.bundle, self.pub)
        missing.write_bytes(b"mock bytes")
        (self.bundle / "w02-release.sig").write_text("AAAA", encoding="ascii")
        with self.assertRaises(Exception):
            release.verify(self.bundle, self.pub)

    def test_sign_refuses_mismatched_legacy_w01_inventory(self):
        (self.bundle / "ClimateChamberLauncher.exe").write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "Integrity mismatch"):
            release.sign(self.bundle, "2.0.0", self.priv, source_sha=self.sha)

    def test_windows_reserved_names_and_directory_collisions(self):
        unsafe = ("CON.txt", "aux", "lpt1.data", "data/trailing.",
                  "data/name ", "dir/foo?.dll", "data/DEL\\x00")
        for name in unsafe:
            with self.subTest(name=name), self.assertRaises(ValueError):
                release.validate_entries({name: "a" * 64})
        for entries in (
            {"Folder": "a" * 64, "folder/a.txt": "b" * 64},
            {"Folder/a.txt": "a" * 64, "folder": "b" * 64},
        ):
            with self.assertRaisesRegex(ValueError, "collision"):
                release.validate_entries(entries)

    def test_external_trust_root_enforced(self):
        embedded = self.bundle / "publisher.pem"
        embedded.write_bytes(self.pub.read_bytes())
        with self.assertRaisesRegex(ValueError, "outside"):
            release.verify(self.bundle, embedded)

    def test_fresh_install_minimum_version_policy(self):
        self.assertEqual(release.verify(self.bundle, self.pub, minimum_version="1.0.0")["version"], "1.0.0")
        with self.assertRaisesRegex(ValueError, "minimum version"):
            release.verify(self.bundle, self.pub, minimum_version="1.0.1")
        with self.assertRaisesRegex(ValueError, "minimum version"):
            release.verify(self.bundle, self.pub, minimum_version="1.0.0-rc1")
        with self.assertRaisesRegex(ValueError, "Invalid"):
            release.verify(self.bundle, self.pub, minimum_version="not-a-version")

    def test_refuse_backup_destination_inside_installed_bundle(self):
        import shutil
        candidate = self.bundle.parent / "candidate"
        shutil.copytree(self.bundle, candidate)
        release.sign(candidate, "1.1.0", self.priv, source_sha=self.sha)
        with self.assertRaisesRegex(ValueError, "overlap"):
            release.stage_update(self.bundle, candidate, self.pub, self.bundle / "backup")
        self.assertFalse((self.bundle / "backup").exists())

    def test_refuse_symlink_in_signed_inventory(self):
        external = self.bundle.parent / "external.dat"
        external.write_bytes(b"x")
        link = self.bundle / "unsafe.link"
        try:
            link.symlink_to(external)
        except (OSError, NotImplementedError):
            self.skipTest("No permission to create a symlink")
        with self.assertRaisesRegex(ValueError, "symlink"):
            release.verify(self.bundle, self.pub)

    def test_signature_sidecar_is_not_an_authentication_key(self):
        with self.assertRaisesRegex(ValueError, "signatures"):
            release.validate_entries({"w02-release.sig": "a" * 64})


    def test_sbom_license_and_provenance_are_explicitly_unapproved(self):
        output = self.bundle.parent / "supply-chain"
        output.mkdir()
        packages = [
            {"name": "nicegui", "version": "3.18.0", "license": "MIT"},
            {"name": "unknown-package", "version": "1.0", "license": ""},
        ]
        windows_manifest.write_supply_chain_reports(
            output, installed=packages, version="1.0.0", include_driver=False,
            web_sha256="a" * 64, driver_sha256="b" * 64)
        sbom = json.loads((output / "sbom.cdx.json").read_text(encoding="utf-8"))
        self.assertEqual(sbom["bomFormat"], "CycloneDX")
        self.assertEqual(sbom["specVersion"], "1.5")
        self.assertEqual(len(sbom["components"]), 2)
        self.assertIn("unapproved-build-environment-not-runtime-closure",
                      json.dumps(sbom))
        licenses = (output / "THIRD_PARTY_LICENSES.csv").read_text(encoding="utf-8")
        self.assertIn("REVIEW_REQUIRED", licenses)
        self.assertIn("unknown-package", licenses)
        provenance = json.loads((output / "build-provenance.json").read_text(encoding="utf-8"))
        self.assertEqual(provenance["dependency_closure"], "UNVERIFIED")
        self.assertEqual(provenance["publisher_signature"], "NOT_ISSUED")


    def test_reparse_point_flag_rejected_on_old_windows_python(self):
        # Unlike Path.is_junction(), st_file_attributes exists in Python 3.10.
        from types import SimpleNamespace
        from unittest import mock

        class Junction:
            @staticmethod
            def is_symlink():
                return False

            @staticmethod
            def lstat():
                return SimpleNamespace(st_file_attributes=1024)

        with mock.patch.object(windows_manifest.stat, "FILE_ATTRIBUTE_REPARSE_POINT",
                               1024, create=True):
            self.assertTrue(windows_manifest.unsafe_reparse(Junction()))


    def _signed_archive(self, location=None, *, mutate=None):
        zip_path = location or (self.bundle.parent / "candidate.zip")
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
            for file in sorted(self.bundle.rglob("*")):
                if file.is_file():
                    name = "signed-bundle/" + file.relative_to(self.bundle).as_posix()
                    zipped.writestr(name, mutate(name, file.read_bytes()) if mutate else
                                    file.read_bytes())
        return zip_path

    def test_offline_archive_verifier_stages_only_signed_bytes(self):
        archive = self._signed_archive()
        install = self.bundle.parent / "installed"
        result = target_verifier.verify_archive(
            archive, install, self.pub, minimum_version="1.0.0")
        self.assertEqual(result["version"], "1.0.0")
        self.assertEqual(release.verify(install, self.pub)["version"], "1.0.0")
        self.assertFalse(install.with_name("installed.pending").exists())
        with self.assertRaisesRegex(ValueError, "already exists"):
            target_verifier.verify_archive(archive, install, self.pub,
                                           minimum_version="1.0.0")

    def test_archive_tampering_fails_without_installing(self):
        archive = self._signed_archive(
            mutate=lambda name, content:
            b"MODIFIED" if name.endswith("ClimateChamberServer.exe") else content)
        install = self.bundle.parent / "installed"
        with self.assertRaises(ValueError):
            target_verifier.verify_archive(archive, install, self.pub, minimum_version="1.0.0")
        self.assertFalse(install.exists())
        self.assertFalse(install.with_name("installed.pending").exists())

    def test_archive_zip_slip_and_casefold_duplicate_fails_pre_extract(self):
        for name in ("signed-bundle/../escape.dll", "signed-bundle/C:/escape.dll",
                     "signed-bundle/server\\evil.dll", "other-root/file.dll"):
            archive = self.bundle.parent / ("bad-" + str(len(name)) + ".zip")
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("signed-bundle/w02-release.json", b"{}")
                zipped.writestr("signed-bundle/w02-release.sig", b"AA")
                zipped.writestr(name, b"evil")
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    target_verifier.verify_archive(
                        archive, self.bundle.parent / "install", self.pub, minimum_version="1.0.0")
                self.assertFalse((self.bundle.parent / "install").exists())
        archive = self.bundle.parent / "duplicate.zip"
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("signed-bundle/w02-release.json", b"{}")
            zipped.writestr("signed-bundle/w02-release.sig", b"AA")
            zipped.writestr("signed-bundle/ONE.dll", b"A")
            zipped.writestr("signed-bundle/one.DLL", b"B")
        with self.assertRaisesRegex(ValueError, "collision"):
            target_verifier.verify_archive(archive, self.bundle.parent / "install",
                                           self.pub, minimum_version="1.0.0")

    def test_archive_requires_external_minimum_version_and_trust_key(self):
        archive = self._signed_archive()
        dest = self.bundle.parent / "install"
        with self.assertRaisesRegex(ValueError, "minimum version"):
            target_verifier.verify_archive(archive, dest, self.pub, minimum_version="")
        with self.assertRaisesRegex(ValueError, "minimum version"):
            target_verifier.verify_archive(archive, dest, self.pub, minimum_version="2.0.0")
        self.assertFalse(dest.exists())
        wrong = self.bundle.parent / "wrong.pem"
        wrong.write_bytes(Ed25519PrivateKey.generate().public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
        with self.assertRaises(Exception):
            target_verifier.verify_archive(archive, dest, wrong, minimum_version="1.0.0")
        self.assertFalse(dest.exists())


    def test_signing_key_can_never_be_in_unsigned_release(self):
        leaked_key = self.bundle / "operator-signing-key.pem"
        leaked_key.write_bytes(self.priv.read_bytes())
        with self.assertRaisesRegex(ValueError, "Private signing key"):
            release.sign(self.bundle, "2.0.0", leaked_key, source_sha=self.sha)
        self.assertFalse((self.bundle / "w02-release.json").read_bytes().find(b'"version":"2.0.0"') >= 0)


if __name__ == "__main__":
    unittest.main()
