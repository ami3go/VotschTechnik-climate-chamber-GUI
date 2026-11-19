"""Pre-production desktop runtime: configuration, state and probe boundaries."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

from chamber_web import desktop_runtime as runtime
from chamber_web import windows_runtime


class PreProductionProbe(BaseHTTPRequestHandler):
    secret = "preproduction-secret"

    def do_GET(self):
        challenge = parse_qs(urlparse(self.path).query).get("challenge", [""])[0]
        proof = hmac.new(self.secret.encode(), challenge.encode(),
                         hashlib.sha256).hexdigest()
        body = json.dumps({
            "app": runtime.APP_ID, "pid": 777, "proof": proof,
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


class ConfigTests(unittest.TestCase):
    def test_allowlisted_values_and_quotes(self):
        values = runtime.parse_config(
            "# comment\n\nCHAMBER_PORT=8091\n"
            'CHAMBER_NETWORK_MODE="localhost"\n'
            "CHAMBER_HIL_ADDRESS='192.168.0.11'\n"
        )
        self.assertEqual(values, {
            "CHAMBER_PORT": "8091",
            "CHAMBER_NETWORK_MODE": "localhost",
            "CHAMBER_HIL_ADDRESS": "192.168.0.11",
        })

    def test_foreign_or_malformed_keys_fail_closed(self):
        for bad in (
            "PATH=/usr/bin",
            "CHAMBER_BAD-KEY=1",
            "CHAMBER_lower=1",
            "NOEQUALS",
            "CHAMBER_PORT=1\nCHAMBER_PORT=2",
            "CHAMBER_PORT=" + "x" * 5000,
            "CHAMBER_PORT=1\x00",
        ):
            with self.subTest(bad=bad[:40]), self.assertRaises(ValueError):
                runtime.parse_config(bad)

    def test_process_environment_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "chamber.env"
            path.write_text("CHAMBER_PORT=8091\nCHAMBER_WITNESS=x\n", encoding="utf-8")
            with mock.patch.dict("os.environ", {"CHAMBER_PORT": "9000"}, clear=False):
                target, applied = runtime.load_environment(path)
            self.assertEqual(target, path)
            self.assertEqual(applied, ["CHAMBER_WITNESS"])

    def test_missing_file_applies_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            target, applied = runtime.load_environment(Path(tmp) / "missing.env")
        self.assertEqual(applied, [])
        self.assertFalse(target.exists())

    def test_oversized_or_symlinked_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "chamber.env"
            path.write_text("CHAMBER_PORT=8091\n" * 5000, encoding="utf-8")
            with self.assertRaises(RuntimeError):
                runtime.load_environment(path)
            link = Path(tmp) / "link.env"
            try:
                link.symlink_to(path)
            except OSError:
                self.skipTest("symlinks unavailable")
            with self.assertRaises(RuntimeError):
                runtime.load_environment(link)


class StateTests(unittest.TestCase):
    def test_state_namespace_and_override(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict("os.environ", {"CHAMBER_STATE_DIR": tmp}, clear=False):
                self.assertEqual(windows_runtime.state_dir("App"), Path(tmp))
                self.assertEqual(windows_runtime.state_dir("W01"), Path(tmp))
                self.assertEqual(windows_runtime.instance_path("App"),
                                 Path(tmp) / "instance.json")

    def test_probe_is_bound_to_the_variant_app_id(self):
        with ThreadingHTTPServer(("127.0.0.1", 0), PreProductionProbe) as http:
            thread = threading.Thread(target=http.serve_forever, daemon=True)
            thread.start()
            instance = {
                "app": runtime.APP_ID, "token": PreProductionProbe.secret,
                "port": http.server_address[1], "pid": 777,
            }
            try:
                self.assertTrue(windows_runtime.probe(
                    instance, app_id=runtime.APP_ID))
                self.assertFalse(windows_runtime.probe(instance))
                self.assertFalse(windows_runtime.probe(
                    {**instance, "app": windows_runtime.APP_ID},
                    app_id=runtime.APP_ID))
            finally:
                http.shutdown()
                thread.join(timeout=5)

    def test_launcher_url_uses_public_origin_when_configured(self):
        with mock.patch.dict("os.environ", {
            "CHAMBER_PORT": "8090",
            "CHAMBER_PUBLIC_ORIGIN": "https://chamber.example:8443",
        }, clear=False):
            self.assertEqual(runtime.launcher_url(), "https://chamber.example:8443/")
        with mock.patch.dict("os.environ", {"CHAMBER_PORT": "8090"}, clear=True):
            self.assertEqual(runtime.launcher_url(), "http://127.0.0.1:8090/")


class RevisionStampTests(unittest.TestCase):
    def test_driver_commit_is_parsed_from_the_reviewed_requirement(self):
        from scripts import build_revision
        self.assertRegex(build_revision.driver_commit(), r"^[0-9a-f]{40}$")

    def test_dirty_worktree_refuses_to_stamp(self):
        from scripts import build_revision

        def fake_git(*arguments):
            return "b" * 40 if arguments[0] == "rev-parse" else " M tracked.py"

        with mock.patch.object(build_revision, "_git", side_effect=fake_git), \
                self.assertRaisesRegex(SystemExit, "dirty"):
            build_revision.gui_commit()

    def test_explicit_commit_must_be_a_full_sha(self):
        from scripts import build_revision
        self.assertEqual(build_revision.gui_commit("A" * 40), "a" * 40)
        with self.assertRaises(SystemExit):
            build_revision.gui_commit("abc123")


if __name__ == "__main__":
    unittest.main()


class ProcessLockTests(unittest.TestCase):
    def test_lock_is_exclusive_and_released(self):
        from chamber_web.windows_runtime import process_lock

        with tempfile.TemporaryDirectory() as tmp:
            os.environ["CHAMBER_STATE_DIR"] = tmp
            with process_lock("server.lock", state_name="App"), \
                    self.assertRaises(RuntimeError), \
                    process_lock("server.lock", state_name="App",
                                 wait_seconds=0.1):
                pass
            with process_lock("server.lock", state_name="App"):
                pass

    def test_preproduction_defaults_to_port_8090(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("CHAMBER_PORT", None)
            os.environ.pop("CHAMBER_PUBLIC_ORIGIN", None)
            self.assertEqual(runtime.config_path().name, "chamber.env")
            self.assertEqual(runtime.launcher_url(), "http://127.0.0.1:8090/")
