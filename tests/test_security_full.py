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

    def test_recovery_is_single_use_and_offline_revokes_all_sessions(self):
        second = self.store.login("admin_1", "VeryLongStrongPassword#123")
        recovery = self.store.issue_recovery_token(
            self.tokens.session, self.tokens.csrf, lifetime_s=100)
        with closing(sqlite3.connect(self.store.database)) as db:
            text = str(db.execute("SELECT token_hash FROM recovery_tokens").fetchall())
            self.assertNotIn(recovery, text)
        with self.assertRaises(AuthenticationError):
            self.store.recover_admin_offline("bad-token", "admin_1",
                                             "AnotherLongStrongPassword#2")
        self.store.recover_admin_offline(recovery, "admin_1",
                                         "AnotherLongStrongPassword#2")
        for token in (self.tokens, second):
            with self.assertRaises(AuthenticationError):
                self.store.authenticate(token.session)
        with self.assertRaises(AuthenticationError):
            self.store.recover_admin_offline(recovery, "admin_1",
                                             "AnotherLongStrongPassword#3")
        with self.assertRaises(AuthenticationError):
            self.store.login("admin_1", "VeryLongStrongPassword#123")
        self.assertIsNotNone(self.store.login(
            "admin_1", "AnotherLongStrongPassword#2").session)

    def test_recovery_expiration_role_and_failed_consumption(self):
        token = self.store.issue_recovery_token(
            self.tokens.session, self.tokens.csrf, lifetime_s=61)
        self.time[0] += 62
        with self.assertRaises(AuthenticationError):
            self.store.recover_admin_offline(token, "admin_1",
                                             "AnotherLongStrongPassword#2")
        self.tokens = self.store.login("admin_1", "VeryLongStrongPassword#123")
        self.store.create_user(self.tokens.session, self.tokens.csrf,
                               "viewer_1", "VeryLongStrongPassword#456", Role.VIEWER)
        token2 = self.store.issue_recovery_token(
            self.tokens.session, self.tokens.csrf, lifetime_s=61)
        with self.assertRaises(AuthenticationError):
            self.store.recover_admin_offline(token2, "viewer_1",
                                             "AnotherLongStrongPassword#2")
        # A failed use MUST NOT consume the credential.
        self.store.recover_admin_offline(token2, "admin_1",
                                         "AnotherLongStrongPassword#2")

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
        verify_security_backup(self.store.directory, path)
        destination = stage_security_restore(
            self.store.directory, path, self.root / "restored")
        with closing(sqlite3.connect(destination)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM sessions"
                                        " WHERE revoked=0").fetchone()[0], 0)
            self.assertEqual(db.execute(
                "SELECT count(*) FROM recovery_tokens").fetchone()[0], 0)
        with self.assertRaises(BackupError):
            stage_security_restore(self.store.directory, path, self.root / "restored")
        manifest = Path(str(path) + ".manifest.json")
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["payload"]["size"] += 1
        manifest.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(BackupError):
            verify_security_backup(self.store.directory, path)

    def test_audit_hmac_detects_tampering_and_survives_restart(self):
        self.store.audit(None, "security.config", "SUCCESS",
                         detail="password=hidden csrf=fake")
        self.assertGreater(self.store.verify_audit_integrity(), 1)
        with closing(sqlite3.connect(self.store.database)) as db:
            row = db.execute("SELECT detail FROM audit ORDER BY sequence DESC"
                             " LIMIT 1").fetchone()[0]
            self.assertNotIn("hidden", row)
            self.assertNotIn("fake", row)
            db.execute("UPDATE audit SET detail='tampered' WHERE sequence=("
                       " SELECT max(sequence) FROM audit)")
            db.commit()
        from chamber_web.security.audit_integrity import AuditIntegrityError
        with self.assertRaises(AuditIntegrityError):
            self.store.verify_audit_integrity()
        with self.assertRaises(AuditIntegrityError):
            SecurityStore(self.store.directory, clock=lambda: self.time[0])

    def test_audit_retention_is_bounded_and_checkpointed(self):
        other = SecurityStore(self.store.directory,
                              clock=lambda: self.time[0], audit_max_rows=100)
        for index in range(120):
            other.audit(None, "safety.check", "DENIED", detail=str(index))
        self.assertLessEqual(other.verify_audit_integrity(), 100)
        restarted = SecurityStore(self.store.directory,
                                  clock=lambda: self.time[0], audit_max_rows=100)
        self.assertEqual(restarted.verify_audit_integrity(), 100)

    def test_invalid_database_and_missing_key_fail_closed(self):
        bad = self.root / "broken.sqlite3"
        bad.write_bytes(b"not-a-sqlite-database")
        with self.assertRaises((sqlite3.DatabaseError, BackupError)):
            stage_security_restore(self.store.directory, bad, self.root / "bad")
        path = self.root / "safe.sqlite3"
        backup_security_database(self.store.directory, path)
        (self.store.directory / "backup_signing_key").unlink()
        with self.assertRaises(BackupError):
            verify_security_backup(self.store.directory, path)


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

    def test_rejects_insecure_lan_and_invalid_certificate(self):
        base = {"CHAMBER_NETWORK_MODE": "lan",
                "CHAMBER_BIND_HOST": "192.168.1.10",
                "CHAMBER_PUBLIC_ORIGIN": "https://chamber.local:8443",
                "CHAMBER_PORT": "8443",
                "CHAMBER_ALLOWED_CLIENT_CIDRS": "192.168.1.0/24"}
        with self.assertRaises(DeploymentError):
            DeploymentPolicy.from_env(base)
        with tempfile.TemporaryDirectory() as temp:
            cert = Path(temp) / "cert.pem"
            key = Path(temp) / "key.pem"
            cert.write_text("invalid certificate")
            key.write_text("invalid private key")
            with self.assertRaises(DeploymentError):
                DeploymentPolicy.from_env({
                    **base, "CHAMBER_TLS_CERT": str(cert),
                    "CHAMBER_TLS_KEY": str(key)})

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
