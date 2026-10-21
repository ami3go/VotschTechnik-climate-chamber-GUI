"""Adversarial W02 air-gap closure checks: no hardware, no network access.

The closure package exists to close the "complete lockfile, hashes and air-gap
wheel closure" release gate. These tests are deliberately hostile: they try to
slip an unpinned requirement, an unhashed artifact, a foreign-platform wheel,
a damaged wheel, a missing wheel and an unapproved license through the tool.
"""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from scripts import w02_closure as closure

PLATFORM = "win_amd64"
PYTHON_TAG = "cp312"

FAKE_WHEELS = {
    "aiofiles-24.1.0-cp312-cp312-win_amd64.whl": ("aiofiles", "24.1.0"),
    "nicegui-3.18.0-cp312-cp312-win_amd64.whl": ("nicegui", "3.18.0"),
    "starlette-0.47.2-py3-none-any.whl": ("starlette", "0.47.2"),
}


def _write_wheel(path: Path, name: str, version: str, *,
                 license_name: str = "MIT", requires_python: str = ">=3.10",
                 payload: bytes = b"mock wheel") -> str:
    """Write a minimal, well-formed wheel and return its SHA-256."""
    dist_info = f"{name.replace('-', '_')}-{version}.dist-info"
    metadata = (
        "Metadata-Version: 2.1\n"
        f"Name: {name}\n"
        f"Version: {version}\n"
        f"License: {license_name}\n"
        f"Requires-Python: {requires_python}\n"
        "\n"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{name}/__init__.py", "VERSION = %r\n" % version)
        archive.writestr(f"{dist_info}/METADATA", metadata)
        archive.writestr(f"{dist_info}/WHEEL",
                         "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: false\n"
                         "Tag: %s-%s-%s\n" % (PYTHON_TAG, PYTHON_TAG, PLATFORM))
    return closure.sha256_file(path)


class ClosureLockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def _artifacts(self) -> list[closure.Artifact]:
        artifacts = []
        for filename, (name, version) in FAKE_WHEELS.items():
            digest = _write_wheel(self.root / filename, name, version)
            artifacts.append(closure.Artifact(
                name=name, version=version, filename=filename, sha256=digest,
                url="https://files.pythonhosted.org/" + filename,
                requires_python=">=3.10", license="MIT"))
        return artifacts

    def test_lock_round_trip_is_pinned_and_hashed(self):
        artifacts = self._artifacts()
        text = closure.render_lock(artifacts, target="win_amd64-cp312",
                                   python_version="3.12",
                                   requirements_sha256="b" * 64)
        entries = closure.parse_lock(text)
        self.assertEqual(len(entries), len(artifacts))
        self.assertIn(("nicegui", "3.18.0", artifacts[1].sha256), entries)
        # Every entry carries a hash, so pip --require-hashes accepts the file.
        for _, _, digest in entries:
            self.assertRegex(digest, r"^[0-9a-f]{64}$")

    def test_unpinned_requirement_is_refused(self):
        with self.assertRaisesRegex(closure.ClosureError, "not pinned"):
            closure.parse_lock("# comment\nnicegui>=3.18.0\n")

    def test_requirement_without_hash_is_refused(self):
        with self.assertRaisesRegex(closure.ClosureError, "without a hash"):
            closure.parse_lock("nicegui==3.18.0 \\\n")

    def test_duplicate_distribution_is_refused(self):
        with self.assertRaisesRegex(closure.ClosureError, "duplicate"):
            closure.parse_lock(
                "nicegui==3.18.0 \\\n    --hash=sha256:" + "a" * 64 + "\n"
                "NiceGUI==3.18.0 \\\n    --hash=sha256:" + "b" * 64 + "\n")

    def test_malformed_hash_is_refused(self):
        with self.assertRaises(closure.ClosureError):
            closure.parse_lock("nicegui==3.18.0 \\\n    --hash=sha256:zz\n")

    def test_empty_closure_is_refused(self):
        with self.assertRaisesRegex(closure.ClosureError, "empty"):
            closure.parse_lock("# only comments\n")


class ClosureWheelhouseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.wheelhouse = self.root / "wheelhouse"
        self.wheelhouse.mkdir()
        self.artifacts = []
        for filename, (name, version) in FAKE_WHEELS.items():
            digest = _write_wheel(self.wheelhouse / filename, name, version)
            self.artifacts.append(closure.Artifact(
                name=name, version=version, filename=filename, sha256=digest,
                url="https://example.invalid/" + filename,
                requires_python=">=3.10", license="MIT"))
        self.entries = [(item.name, item.version, item.sha256)
                        for item in self.artifacts]

    def test_matching_wheelhouse_verifies(self):
        closure.verify_wheelhouse(self.entries, self.wheelhouse,
                                  platform_tags=(PLATFORM,), python_tag=PYTHON_TAG)

    def test_damaged_wheel_is_refused(self):
        (self.wheelhouse / "nicegui-3.18.0-cp312-cp312-win_amd64.whl").write_bytes(
            b"tampered")
        with self.assertRaisesRegex(closure.ClosureError, "damaged"):
            closure.verify_wheelhouse(self.entries, self.wheelhouse,
                                      platform_tags=(PLATFORM,), python_tag=PYTHON_TAG)

    def test_missing_wheel_is_refused(self):
        (self.wheelhouse / "aiofiles-24.1.0-cp312-cp312-win_amd64.whl").unlink()
        with self.assertRaisesRegex(closure.ClosureError, "missing"):
            closure.verify_wheelhouse(self.entries, self.wheelhouse,
                                      platform_tags=(PLATFORM,), python_tag=PYTHON_TAG)

    def test_unexpected_artifact_is_refused(self):
        (self.wheelhouse / "extra-1.0.0-py3-none-any.whl").write_bytes(b"x")
        with self.assertRaisesRegex(closure.ClosureError, "unexpected"):
            closure.verify_wheelhouse(self.entries, self.wheelhouse,
                                      platform_tags=(PLATFORM,), python_tag=PYTHON_TAG)

    def test_foreign_platform_wheel_is_refused(self):
        path = self.wheelhouse / "linuxpkg-1.0.0-cp312-cp312-manylinux_2_17_x86_64.whl"
        _write_wheel(path, "linuxpkg", "1.0.0")
        with self.assertRaisesRegex(closure.ClosureError, "platform tag"):
            closure.verify_wheelhouse(self.entries, self.wheelhouse,
                                      platform_tags=(PLATFORM,), python_tag=PYTHON_TAG)

    def test_foreign_python_tag_is_refused(self):
        path = self.wheelhouse / "oldpkg-1.0.0-cp310-cp310-win_amd64.whl"
        _write_wheel(path, "oldpkg", "1.0.0")
        with self.assertRaisesRegex(closure.ClosureError, "python/abi tags"):
            closure.verify_wheelhouse(self.entries, self.wheelhouse,
                                      platform_tags=(PLATFORM,), python_tag=PYTHON_TAG)

    def test_missing_wheelhouse_directory_is_refused(self):
        with self.assertRaisesRegex(closure.ClosureError, "missing"):
            closure.verify_wheelhouse(self.entries, self.root / "absent",
                                      platform_tags=(PLATFORM,), python_tag=PYTHON_TAG)

    def test_pure_python_wheel_is_accepted(self):
        path = self.wheelhouse / "purepkg-1.0.0-py3-none-any.whl"
        _write_wheel(path, "purepkg", "1.0.0")
        entries = self.entries + [("purepkg", "1.0.0",
                                   closure.sha256_file(path))]
        closure.verify_wheelhouse(entries, self.wheelhouse,
                                  platform_tags=(PLATFORM,), python_tag=PYTHON_TAG)

    def test_stable_abi_wheel_for_an_older_floor_is_accepted(self):
        path = self.wheelhouse / "abipkg-1.0.0-cp310-abi3-win_amd64.whl"
        _write_wheel(path, "abipkg", "1.0.0")
        entries = self.entries + [("abipkg", "1.0.0",
                                   closure.sha256_file(path))]
        closure.verify_wheelhouse(entries, self.wheelhouse,
                                  platform_tags=(PLATFORM,), python_tag=PYTHON_TAG)

    def test_stable_abi_wheel_for_a_newer_floor_is_refused(self):
        path = self.wheelhouse / "toonew-1.0.0-cp313-abi3-win_amd64.whl"
        _write_wheel(path, "toonew", "1.0.0")
        entries = self.entries + [("toonew", "1.0.0",
                                   closure.sha256_file(path))]
        with self.assertRaisesRegex(closure.ClosureError, "stable-ABI"):
            closure.verify_wheelhouse(entries, self.wheelhouse,
                                      platform_tags=(PLATFORM,), python_tag=PYTHON_TAG)

    def test_compound_foreign_platform_tag_is_refused(self):
        path = (self.wheelhouse
                / "compound-1.0.0-cp312-cp312-manylinux1_x86_64.manylinux_2_28_x86_64.whl")
        _write_wheel(path, "compound", "1.0.0")
        with self.assertRaisesRegex(closure.ClosureError, "platform tag"):
            closure.verify_wheelhouse(self.entries, self.wheelhouse,
                                      platform_tags=(PLATFORM,), python_tag=PYTHON_TAG)

    def test_manifest_must_agree_with_the_closure(self):
        manifest = self.root / "manifest.json"
        payload = {"schema": closure.SCHEMA, "artifacts": [
            {"name": item.name, "version": item.version,
             "filename": item.filename, "sha256": item.sha256}
            for item in self.artifacts]}
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        closure.verify_manifest(self.artifacts, manifest)
        payload["artifacts"][0]["sha256"] = "c" * 64
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(closure.ClosureError, "hash mismatch"):
            closure.verify_manifest(self.artifacts, manifest)


class ClosureSbomTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def _artifacts(self) -> list[closure.Artifact]:
        artifacts = []
        for filename, (name, version) in FAKE_WHEELS.items():
            digest = "d" * 64
            artifacts.append(closure.Artifact(
                name=name, version=version, filename=filename, sha256=digest,
                url="https://example.invalid/" + filename,
                requires_python=">=3.10", license="MIT"))
        return artifacts

    def test_sbom_covers_exactly_the_runtime_closure(self):
        artifacts = self._artifacts()
        document = closure.render_sbom(artifacts, version="1.0.0",
                                       target="win_amd64-cp312", python_version="3.12")
        self.assertEqual(document["specVersion"], "1.5")
        names = {component["name"] for component in document["components"]}
        self.assertEqual(names, {"aiofiles", "nicegui", "starlette"})
        scope = {item["value"] for item in document["metadata"]["properties"]
                 if item["name"] == "w02:inventory-scope"}
        self.assertEqual(scope, {"locked-runtime-closure"})

    def test_sbom_is_deterministic(self):
        artifacts = self._artifacts()
        first = closure.render_sbom(artifacts, version="1.0.0",
                                    target="win_amd64-cp312", python_version="3.12")
        second = closure.render_sbom(list(reversed(artifacts)), version="1.0.0",
                                     target="win_amd64-cp312", python_version="3.12")
        self.assertEqual(json.dumps(first, sort_keys=True),
                         json.dumps(second, sort_keys=True))

    def test_no_license_is_self_approved(self):
        rows = closure.render_license_rows(self._artifacts())
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(row[3], "REVIEW_REQUIRED")

    def test_missing_license_is_reported_as_noassertion(self):
        artifacts = self._artifacts()
        artifacts[0] = closure.Artifact(
            name=artifacts[0].name, version=artifacts[0].version,
            filename=artifacts[0].filename, sha256=artifacts[0].sha256,
            url=artifacts[0].url, requires_python="", license="")
        rows = closure.render_license_rows(artifacts)
        self.assertEqual(rows[0][2], "NOASSERTION")
        document = closure.render_sbom(artifacts, version="1.0.0",
                                       target="win_amd64-cp312", python_version="3.12")
        component = next(item for item in document["components"]
                         if item["name"] == artifacts[0].name)
        self.assertNotIn("licenses", component)


class ClosureToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_cross_platform_resolution_is_refused(self):
        """A foreign platform would resolve the wrong markers; refuse it."""
        with self.assertRaises(closure.ClosureError):
            closure.main(["build", "--requirements", str(self.root / "req.txt"),
                          "--wheelhouse", str(self.root / "wh")])

    def test_unknown_target_is_refused(self):
        with self.assertRaises(closure.ClosureError):
            closure.main(["verify", "--wheelhouse", str(self.root),
                          "--lock", str(self.root / "lock"),
                          "--target", "linux-x86_64"])

    def test_lock_inside_the_wheelhouse_is_refused(self):
        """The wheelhouse holds artifacts only; the lock describes them."""
        wheelhouse = self.root / "wheelhouse"
        wheelhouse.mkdir()
        with self.assertRaisesRegex(closure.ClosureError, "inside the wheelhouse"):
            closure.main(["build", "--requirements", str(self.root / "req.txt"),
                          "--wheelhouse", str(wheelhouse),
                          "--lock", str(wheelhouse / "built.lock"),
                          "--manifest", str(self.root / "manifest.json")])

    def test_cross_platform_resolution_is_refused_before_any_download(self):
        """A foreign platform would resolve the wrong markers; refuse it."""
        with self.assertRaisesRegex(closure.ClosureError, "natively on the target"):
            closure.main(["build", "--requirements", str(self.root / "req.txt"),
                          "--wheelhouse", str(self.root / "wh"),
                          "--lock", str(self.root / "lock"),
                          "--manifest", str(self.root / "manifest.json")])

    def test_verify_rejects_a_lock_without_hashes(self):
        lock = self.root / "lock"
        lock.write_text("nicegui==3.18.0\n", encoding="utf-8")
        with self.assertRaises(closure.ClosureError):
            closure.main(["verify", "--wheelhouse", str(self.root), "--lock", str(lock)])

    def test_sbom_command_refuses_a_lock_manifest_disagreement(self):
        manifest = self.root / "manifest.json"
        manifest.write_text(json.dumps({
            "schema": closure.SCHEMA, "python_tag": "cp312",
            "artifacts": [{"name": "nicegui", "version": "3.18.0",
                           "filename": "nicegui-3.18.0-cp312-cp312-win_amd64.whl",
                           "sha256": "e" * 64}]}), encoding="utf-8")
        lock = self.root / "lock"
        lock.write_text(
            "nicegui==3.18.0 \\\n    --hash=sha256:" + "f" * 64 + "\n", encoding="utf-8")
        with self.assertRaises(closure.ClosureError):
            closure.main(["sbom", "--lock", str(lock), "--manifest", str(manifest),
                          "--sbom-out", str(self.root / "sbom.json"),
                          "--licenses-out", str(self.root / "licenses.csv")])


if __name__ == "__main__":
    unittest.main()
