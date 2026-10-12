"""W01-A portable Windows bootstrap and integrity tests (no hardware)."""
from __future__ import annotations

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

from chamber_web import windows_runtime as runtime
from scripts import windows_manifest as manifest


class ReadyHandler(BaseHTTPRequestHandler):
    app_id = runtime.APP_ID
    secret = "test-secret"

    def do_GET(self):
        from urllib.parse import parse_qs, urlparse

        challenge = parse_qs(urlparse(self.path).query).get("challenge", [""])[0]
        answer = hmac.new(self.secret.encode(), challenge.encode(), hashlib.sha256).hexdigest()
        body = json.dumps({"app": self.app_id, "pid": 444, "proof": answer}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


class RuntimeTests(unittest.TestCase):
    def test_bad_port_fails_closed(self):
        for value in ("abc", "80", "65536", "-1"):
            with self.subTest(value=value), mock.patch.dict(
                "os.environ", {"CHAMBER_PORT": value}
            ):
                with self.assertRaises(RuntimeError):
                    runtime.configured_port()

    def test_hmac_proof_and_no_port_trust(self):
        with ThreadingHTTPServer(("127.0.0.1", 0), ReadyHandler) as http:
            thread = threading.Thread(target=http.serve_forever, daemon=True)
            thread.start()
            port = http.server_address[1]
            instance = {"app": runtime.APP_ID, "token": "test-secret", "port": port, "pid": 444}
            try:
                self.assertTrue(runtime.probe(instance))
                # Explicit proxy bypass is required for genuinely offline Windows.
                with mock.patch.dict("os.environ", {
                    "HTTP_PROXY": "http://127.0.0.1:1",
                    "HTTPS_PROXY": "http://127.0.0.1:1", "NO_PROXY": "",
                }):
                    self.assertTrue(runtime.probe(instance))
                self.assertFalse(runtime.probe({**instance, "token": "different"}))
                self.assertFalse(runtime.probe({**instance, "pid": 123}))
                self.assertFalse(runtime.probe({**instance, "app": "foreign"}))
                self.assertTrue(runtime.port_occupied(port))
            finally:
                http.shutdown()
                thread.join(timeout=5)

    def test_oversized_foreign_health_reply_rejected(self):
        class OversizedHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = b"x" * 10000
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except ConnectionError:
                    pass

            def log_message(self, *_args):
                pass

        with ThreadingHTTPServer(("127.0.0.1", 0), OversizedHandler) as http:
            thread = threading.Thread(target=http.serve_forever, daemon=True)
            thread.start()
            try:
                self.assertFalse(runtime.probe({
                    "app": runtime.APP_ID,
                    "token": "test-secret",
                    "pid": 444, "port": http.server_address[1],
                }))
            finally:
                http.shutdown()
                thread.join(timeout=5)

    def test_missing_frozen_module_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "Required packaged module missing"):
            runtime.frozen_self_test(required_modules=("w01_missing_package_xyz",))

    def test_driver_validation_does_not_instantiate_hardware(self):
        from chamber_web.adapters import votsch
        # The package is deliberately not needed for this unit test: exercise
        # the adapter import boundary with a controlled in-memory import.
        import sys
        import types
        fake_module = types.ModuleType("VotschTechnikClimateChamber")
        fake_module.ClimateChamber = lambda: (_ for _ in ()).throw(
            AssertionError("driver was instantiated")
        )
        fake_module.__version__ = "0.2.0-test"
        with mock.patch.dict(sys.modules, {"VotschTechnikClimateChamber": fake_module}):
            self.assertEqual(votsch.verify_bundled_driver_import(), "0.2.0-test")

    def test_missing_driver_is_not_required_for_fake(self):
        from chamber_web.adapters.registry import make_backend
        from chamber_web.domain.config import ChamberConfig

        for adapter_id in ("fake", "alternate_stub"):
            backend = make_backend(ChamberConfig("only", adapter_id),
                                   allow_test_backend=True)
            backend.connect()
            self.assertEqual(backend.identify().chamber_id, "only")
            backend.disconnect()


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bundle = Path(self.tmp.name)
        for entry in (
            "ClimateChamberLauncher.exe",
            "server/ClimateChamberServer.exe",
            "server/_internal/nicegui/assets/runtime.js",
            "server/_internal/chamber_web/assets/style.css",
        ):
            path = self.bundle / entry
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"test-only")

    def test_manifest_detects_tamper_and_unexpected_files(self):
        files = manifest.files_under(self.bundle)
        manifest.check_assets(files)
        (self.bundle / "build-manifest.json").write_text(
            json.dumps({"files": files}), encoding="utf-8"
        )
        (self.bundle / "SHA256SUMS.txt").write_text(
            "".join(f"{digest}  {name}\n" for name, digest in sorted(files.items())),
            encoding="utf-8"
        )
        manifest.verify_manifest(self.bundle)
        (self.bundle / "server/_internal/nicegui/assets/runtime.js").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "Integrity mismatch"):
            manifest.verify_manifest(self.bundle)
        (self.bundle / "server/_internal/nicegui/assets/runtime.js").write_bytes(b"test-only")
        (self.bundle / "unmanifested.dll").write_bytes(b"unexpected")
        with self.assertRaisesRegex(ValueError, "unexpected"):
            manifest.verify_manifest(self.bundle)

    def test_missing_assets_fails(self):
        (self.bundle / "server/_internal/chamber_web/assets/style.css").unlink()
        with self.assertRaisesRegex(ValueError, "CSS missing"):
            manifest.check_assets(manifest.files_under(self.bundle))

    def test_path_traversal_rejected(self):
        (self.bundle / "build-manifest.json").write_text(
            json.dumps({"files": {"../secret.txt": "123"}}), encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "Unsafe manifest path"):
            manifest.verify_manifest(self.bundle)


if __name__ == "__main__":
    unittest.main()
