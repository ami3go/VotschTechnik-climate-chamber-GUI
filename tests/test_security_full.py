"""G08 adversarial tests; real hardware and external network never touched."""
from __future__ import annotations

import asyncio
from contextlib import closing
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chamber_web.security.auth import AuthenticationError, AuthorizationError, Role, SecurityStore
from chamber_web.security.backup import (
    BackupError, backup_security_database, stage_security_restore,
    verify_security_backup,
)
from chamber_web.security.deployment import DeploymentError, DeploymentPolicy
from chamber_web.security.http import OriginMiddleware
from chamber_web.security.guards import Permission, require_permission


class HardenedIdentityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.time = [1000000.0]
        self.store = SecurityStore(
            self.root / "security", clock=lambda: self.time[0],
            idle_timeout_s=60, absolute_timeout_s=120,
            password_min_bytes=16, lockout_attempts=3,
            lockout_seconds=70, client_attempts=5,
        )
        self.store.bootstrap_admin("admin_1", "VeryLongStrongPassword#123")
        self.tokens = self.store.login("admin_1", "VeryLongStrongPassword#123")

    def test_session_fixation_replay_and_csrf_token_separation(self):
        """Storage-level fixation boundary; browser cookie rotation is a W02 gate."""
        attacker_chosen = "A" * 44
        with self.assertRaises(AuthenticationError):
            self.store.authenticate(attacker_chosen)
        second = self.store.login("admin_1", "VeryLongStrongPassword#123")
        self.assertNotEqual(second.session, self.tokens.session)
        self.assertNotEqual(second.csrf, self.tokens.csrf)
        with self.assertRaises(AuthorizationError):
            self.store.authenticate(second.session, csrf=self.tokens.csrf,
                                    mutation=True)
        self.store.logout(second.session)
        with self.assertRaises(AuthenticationError):
            self.store.authenticate(second.session, csrf=second.csrf,
                                    mutation=True)
        self.assertEqual(self.store.authenticate(
            self.tokens.session, csrf=self.tokens.csrf, mutation=True).role,
            Role.ADMIN)

    def test_invalid_migration_version_fails_closed(self):
        with closing(sqlite3.connect(self.store.database)) as db:
            db.execute("PRAGMA user_version = 9999")
            db.commit()
        with self.assertRaises(RuntimeError):
            SecurityStore(self.store.directory, clock=lambda: self.time[0])

    def test_invalid_environment_policy_fails_closed(self):
        from unittest.mock import patch
        with patch.dict("os.environ", {"CHAMBER_PASSWORD_MIN_BYTES": "4"}):
            with self.assertRaises(ValueError):
                SecurityStore.from_environment(self.root / "bad-config")
        with patch.dict("os.environ", {"CHAMBER_LOGIN_PEER_ATTEMPTS": "nan"}):
            with self.assertRaises(ValueError):
                SecurityStore.from_environment(self.root / "bad-config-2")

    def test_password_change_revokes_all_concurrent_sessions(self):
        other = self.store.login("admin_1", "VeryLongStrongPassword#123")
        with self.assertRaises(AuthenticationError):
            self.store.change_password(self.tokens.session, self.tokens.csrf,
                                       "wrong-old", "AnotherLongStrongPassword#2")
        self.store.change_password(self.tokens.session, self.tokens.csrf,
                                   "VeryLongStrongPassword#123",
                                   "AnotherLongStrongPassword#2")
        for token in (self.tokens, other):
            with self.assertRaises(AuthenticationError):
                self.store.authenticate(token.session)

    def test_admin_session_revocation_and_role_downgrade(self):
        self.store.create_user(self.tokens.session, self.tokens.csrf, "viewer_1",
                               "VeryLongStrongPassword#456", Role.VIEWER)
        other = self.store.login("viewer_1", "VeryLongStrongPassword#456")
        with self.assertRaises(AuthorizationError):
            require_permission(self.store.authenticate(other.session), Permission.STOP)
        self.store.revoke_sessions(self.tokens.session, self.tokens.csrf, "viewer_1")
        with self.assertRaises(AuthenticationError):
            self.store.authenticate(other.session)

    def test_user_listing_is_admin_only_and_contains_no_credentials(self):
        self.store.create_user(
            self.tokens.session, self.tokens.csrf,
            "viewer_1", "VeryLongStrongPassword#456", Role.VIEWER,
        )
        accounts = self.store.list_users(self.tokens.session)
        self.assertEqual(
            [(account.username, account.role, account.enabled)
             for account in accounts],
            [("admin_1", Role.ADMIN, True), ("viewer_1", Role.VIEWER, True)],
        )
        self.assertFalse(any(
            hasattr(account, field)
            for account in accounts
            for field in ("password", "password_hash")
        ))
        viewer = self.store.login("viewer_1", "VeryLongStrongPassword#456")
        with self.assertRaises(AuthorizationError):
            self.store.list_users(viewer.session)

    def test_configurable_lockout_does_not_extend_locked_interval(self):
        for _ in range(3):
            with self.assertRaises(AuthenticationError):
                self.store.login("admin_1", "wrong")
        self.time[0] += 60
        for _ in range(2):
            with self.assertRaises(AuthenticationError):
                self.store.login("admin_1", "VeryLongStrongPassword#123")
        self.time[0] += 11
        self.assertIsNotNone(self.store.login(
            "admin_1", "VeryLongStrongPassword#123").session)

    def test_ip_rate_limit_before_expensive_hash(self):
        for index in range(5):
            with self.assertRaises(AuthenticationError):
                self.store.login(f"wrong_{index}", "wrong", client_id="192.0.2.9")
        with patch("chamber_web.security.auth._verify_password",
                   side_effect=AssertionError("scrypt must not execute")):
            with self.assertRaises(AuthenticationError):
                self.store.login("admin_1", "VeryLongStrongPassword#123",
                                 client_id="192.0.2.9")
        self.assertIsNotNone(self.store.login(
            "admin_1", "VeryLongStrongPassword#123",
            client_id="192.0.2.10").session)

    def test_backup_tamper_and_restore_sessions_revoked(self):
        path = self.root / "safe.sqlite3"
        backup_security_database(self.store.directory, path)
        verify_security_backup(path)
        destination = stage_security_restore(path, self.root / "restored")
        with closing(sqlite3.connect(destination)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM sessions"
                                        " WHERE revoked=0").fetchone()[0], 0)
        with self.assertRaises(BackupError):
            stage_security_restore(path, self.root / "restored")
        manifest = Path(str(path) + ".manifest.json")
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["size"] += 1
        manifest.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(BackupError):
            verify_security_backup(path)

    def test_audit_export_is_append_only_and_redacted(self):
        self.store.audit(None, "security.config", "SUCCESS",
                         detail="password=hidden csrf=fake")
        destination = self.root / "audit-export.csv"
        output, digest = self.store.export_audit(destination)
        self.assertEqual(output, destination)
        self.assertTrue(destination.is_file())
        self.assertEqual(
            Path(str(destination) + ".sha256").read_text(encoding="ascii"),
            digest + "  " + destination.name + "\n")
        text = destination.read_text(encoding="utf-8")
        self.assertNotIn("hidden", text)
        self.assertNotIn("fake", text)
        self.assertEqual(len(text.splitlines()), len(self.store.audit_records()) + 1)
        with self.assertRaises(FileExistsError):
            self.store.export_audit(destination)

    def test_missing_security_db_cannot_rebootstrap_existing_authority(self):
        # A credential-file-only survivor is evidence that a database was
        # removed, not an invitation to provision a new first administrator.
        self.store.database.unlink()
        with self.assertRaisesRegex(RuntimeError, "database is missing"):
            SecurityStore(self.store.directory, clock=lambda: self.time[0])

    def test_parallel_first_security_store_initialization(self):
        # Two initializers previously saw a freshly created audit key before
        # its first SQLite checkpoint existed and falsely rejected startup.
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier

        directory = self.root / "parallel-initialization"
        barrier = Barrier(6)

        def start(_index):
            barrier.wait()
            return SecurityStore(directory).audit_records()

        with ThreadPoolExecutor(max_workers=6) as executor:
            counts = list(executor.map(start, range(6)))
        self.assertEqual(counts, [[]] * 6)
        SecurityStore(directory).bootstrap_admin(
            "parallel_admin", "AnIndependentLongPassword#10")
        self.assertGreater(len(SecurityStore(directory).audit_records()), 0)

    def test_invalid_database_and_missing_manifest_fail_closed(self):
        bad = self.root / "broken.sqlite3"
        bad.write_bytes(b"not-a-sqlite-database")
        Path(str(bad) + ".manifest.json").write_text("{}", encoding="utf-8")
        with self.assertRaises((sqlite3.DatabaseError, BackupError)):
            stage_security_restore(bad, self.root / "bad")
        path = self.root / "safe.sqlite3"
        backup_security_database(self.store.directory, path)
        Path(str(path) + ".manifest.json").unlink()
        with self.assertRaises(BackupError):
            verify_security_backup(path)


class HardenedNetworkTests(unittest.TestCase):
    def test_default_is_loopback_only(self):
        pol = DeploymentPolicy.from_env({})
        self.assertEqual(pol.mode, "localhost")
        self.assertTrue(pol.allows_client("127.0.0.1"))
        self.assertTrue(pol.allows_client("::1"))
        self.assertFalse(pol.allows_client("192.168.1.2"))
        with self.assertRaises(DeploymentError):
            DeploymentPolicy.from_env({"CHAMBER_BIND_HOST": "0.0.0.0"})
        with self.assertRaises(DeploymentError):
            DeploymentPolicy.from_env({
                "CHAMBER_ALLOWED_ORIGINS": "http://attacker.invalid:8080"})

    def test_lab_is_plain_http_private_only(self):
        policy = DeploymentPolicy.from_env({
            "CHAMBER_NETWORK_MODE": "lab",
            "CHAMBER_BIND_HOST": "192.168.1.10",
            "CHAMBER_PORT": "8080",
            "CHAMBER_ALLOWED_CLIENT_CIDRS": "192.168.1.0/24",
        })
        self.assertTrue(policy.is_lab)
        self.assertIn("http://192.168.1.10:8080", policy.allowed_origins)
        self.assertTrue(policy.allows_client("192.168.1.42"))
        self.assertFalse(policy.allows_client("192.168.2.42"))
        for env in (
            {"CHAMBER_NETWORK_MODE": "lan"},
            {"CHAMBER_NETWORK_MODE": "lab",
             "CHAMBER_PUBLIC_ORIGIN": "https://chamber.local:8080"},
            {"CHAMBER_NETWORK_MODE": "lab",
             "CHAMBER_ALLOWED_CLIENT_CIDRS": "0.0.0.0/0"},
        ):
            with self.subTest(env=env), self.assertRaises(DeploymentError):
                DeploymentPolicy.from_env(env)

    @staticmethod
    def probe(kind, headers, *, client=("127.0.0.1", 12345), method="GET"):
        emitted = []

        async def app(scope, receive, send):
            emitted.append({"type": "accepted"})
            if kind == "http":
                await send({"type": "http.response.start", "status": 200,
                            "headers": []})
                await send({"type": "http.response.body", "body": b"ok"})

        async def send(event):
            emitted.append(event)

        scope = {"type": kind, "method": method, "path": "/_nicegui_ws/socket.io",
                 "client": client, "headers": headers}
        policy = DeploymentPolicy.from_env({})
        asyncio.run(OriginMiddleware(app,
                    allowed_origins=policy.allowed_origins, deployment=policy)(
                        scope, lambda: None, send))
        return emitted

    def test_host_rebinding_and_unauthorized_peer(self):
        self.assertEqual(self.probe(
            "http", [(b"host", b"attacker.invalid:8080")])[0]["status"], 403)
        self.assertEqual(self.probe("http",
            [(b"host", b"127.0.0.1:8080")],
            client=("192.0.2.22", 4321))[0]["status"], 403)
        self.assertEqual(self.probe("http", [
            (b"host", b"127.0.0.1:8080"),
            (b"host", b"attacker.invalid:8080")])[0]["status"], 403)

    def test_rejects_forged_testserver_host_even_during_unit_testing(self):
        self.assertEqual(self.probe(
            "http", [(b"host", b"testserver")])[0]["status"], 403)
        self.assertEqual(self.probe(
            "websocket", [(b"host", b"testserver"),
                          (b"origin", b"http://testserver")])[0]["code"], 1008)

    def test_websocket_origin_and_cross_site_replay(self):
        base = [(b"host", b"127.0.0.1:8080")]
        for headers in (base, base + [(b"origin", b"http://evil.invalid:8080")],
                        base + [(b"origin", b"http://127.0.0.1:8080"),
                                (b"sec-fetch-site", b"cross-site")]):
            self.assertEqual(self.probe("websocket", headers)[0]["code"], 1008)
        self.assertEqual(self.probe("websocket", base + [
            (b"origin", b"http://127.0.0.1:8080")])[0]["type"], "accepted")

    def test_security_headers_on_valid_response(self):
        events = self.probe("http", [(b"host", b"127.0.0.1:8080")])
        response = next(row for row in events if row.get("type") == "http.response.start")
        keys = {k for k, _ in response["headers"]}
        self.assertIn(b"x-frame-options", keys)
        self.assertIn(b"x-content-type-options", keys)
        self.assertIn(b"cache-control", keys)


if __name__ == "__main__":
    unittest.main()
