"""Fail-closed tests for the stdlib-only W02 build-tool bootstrap."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import w02_build_bootstrap as bootstrap


class _Response(io.BytesIO):
    def __init__(self, payload: bytes, url: str):
        super().__init__(payload)
        self._url = url

    def geturl(self) -> str:
        return self._url


class BuildBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.requirements = self.root / "requirements-w02-build.txt"
        self.lock = self.root / "requirements-w02-build.lock"
        self.manifest = self.root / "w02-build-closure-manifest.json"
        self.payloads = {
            "alpha-1.0-py3-none-any.whl": b"alpha wheel",
            "beta-2.0-py3-none-win_amd64.whl": b"beta wheel",
        }
        self.requirements.write_text("alpha==1.0\nbeta==2.0\n", encoding="utf-8")
        records = []
        lock_lines = []
        for filename, payload in self.payloads.items():
            name, version = filename.split("-", 2)[:2]
            digest = hashlib.sha256(payload).hexdigest()
            url = "https://files.pythonhosted.org/packages/test/" + filename
            records.append({"name": name, "version": version, "filename": filename,
                            "sha256": digest, "url": url})
            lock_lines.extend([f"{name}=={version} \\",
                               f"    --hash=sha256:{digest}"])
        self.lock.write_text("\n".join(lock_lines) + "\n", encoding="utf-8")
        self.manifest.write_text(json.dumps({
            "schema": 1,
            "target": "win_amd64-cp312",
            "platform": ["win_amd64"],
            "python_tag": "cp312",
            "requirements": self.requirements.name,
            "requirements_sha256": bootstrap.canonical_sha256(self.requirements),
            "artifacts": records,
        }), encoding="utf-8")

    def test_exact_reviewed_inventory_hydrates_atomically(self):
        by_url = {"https://files.pythonhosted.org/packages/test/" + name: payload
                  for name, payload in self.payloads.items()}

        def open_reviewed(url, timeout):
            self.assertEqual(timeout, 60)
            return _Response(by_url[url], url)

        wheelhouse = self.root / "wheelhouse"
        with patch.object(bootstrap, "urlopen", side_effect=open_reviewed):
            bootstrap.hydrate(self.requirements, self.lock, self.manifest, wheelhouse)
        self.assertEqual({path.name for path in wheelhouse.iterdir()}, set(self.payloads))

    def test_hash_failure_leaves_no_partial_wheelhouse(self):
        wheelhouse = self.root / "wheelhouse"
        with patch.object(bootstrap, "urlopen",
                          side_effect=lambda url, timeout: _Response(b"tampered", url)):
            with self.assertRaisesRegex(bootstrap.BootstrapError, "hash mismatch"):
                bootstrap.hydrate(self.requirements, self.lock, self.manifest, wheelhouse)
        self.assertFalse(wheelhouse.exists())

    def test_redirect_untrusted_url_and_input_drift_are_refused(self):
        wheelhouse = self.root / "wheelhouse"
        with patch.object(bootstrap, "urlopen", side_effect=lambda url, timeout:
                          _Response(b"ignored", url + "?redirected")):
            with self.assertRaisesRegex(bootstrap.BootstrapError, "redirected"):
                bootstrap.hydrate(self.requirements, self.lock, self.manifest, wheelhouse)
        payload = json.loads(self.manifest.read_text(encoding="utf-8"))
        payload["artifacts"][0]["url"] = "https://example.com/alpha.whl"
        self.manifest.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(bootstrap.BootstrapError, "untrusted"):
            bootstrap.reviewed_artifacts(self.requirements, self.lock, self.manifest)
        self.requirements.write_text("alpha==1.1\nbeta==2.0\n", encoding="utf-8")
        with self.assertRaisesRegex(bootstrap.BootstrapError, "input mismatch"):
            bootstrap.reviewed_artifacts(self.requirements, self.lock, self.manifest)

    def test_missing_extra_unpinned_and_nonempty_destination_are_refused(self):
        payload = json.loads(self.manifest.read_text(encoding="utf-8"))
        payload["artifacts"].pop()
        self.manifest.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(bootstrap.BootstrapError, "different inventories"):
            bootstrap.reviewed_artifacts(self.requirements, self.lock, self.manifest)
        self.requirements.write_text("alpha>=1.0\n", encoding="utf-8")
        with self.assertRaisesRegex(bootstrap.BootstrapError, "not exactly pinned"):
            bootstrap.input_pins(self.requirements)


if __name__ == "__main__":
    unittest.main()
