"""G08-min mock-only authorization, concurrency, sessions and forgery tests."""
from __future__ import annotations

import asyncio
from contextlib import closing
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from chamber_web.adapters.fake import FakeBackend
from chamber_web.domain.config import ChamberConfig
from chamber_web.security.bootstrap import interactive_bootstrap
from chamber_web.security.auth import (
    AuthenticationError, AuthorizationError, Role, SecurityStore,
)
from chamber_web.security.guards import (
    AuthorizedChamber, Permission, require_permission,
)
from chamber_web.security.http import OriginMiddleware, authorize_http_mutation, valid_origin
from chamber_web.services.chamber_manager import ChamberManager


class SecurityCoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = [1_000_000.0]
        self.security = SecurityStore(Path(self.temp.name) / "security",
                                      clock=lambda: self.now[0],
                                      idle_timeout_s=60, absolute_timeout_s=120)
        self.security.bootstrap_admin("admin_1", "StrongAdminPassword#1")
        self.admin = self.security.login("admin_1", "StrongAdminPassword#1")

    def add_user(self, username, role):
        self.security.create_user(self.admin.session, self.admin.csrf,
                                  username, "StrongSecretPassword#2", role)
        return self.security.login(username, "StrongSecretPassword#2")

    def test_noninteractive_bootstrap_is_denied(self):
        with patch("chamber_web.security.bootstrap.sys.stdin") as fake_stdin:
            fake_stdin.isatty.return_value = False
            self.assertEqual(interactive_bootstrap(Path(self.temp.name) / "forbidden"), 2)

    def test_offline_bootstrap_is_atomic_and_never_repeatable(self):
        self.assertTrue(self.security.is_bootstrapped())
        with self.assertRaises(AuthorizationError):
            self.security.bootstrap_admin("another_admin", "StrongAdminPassword#1")
        with closing(sqlite3.connect(self.security.database)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM users").fetchone()[0], 1)
            self.assertNotIn("StrongAdminPassword", str(
                db.execute("SELECT password_hash FROM users").fetchone()[0]))

    def test_concurrent_initial_bootstrap_single_winner(self):
        directory = Path(self.temp.name) / "other_security"
        start = threading.Event()
        success = []
        errors = []

        def worker(username):
            service = SecurityStore(directory)
            start.wait()
            try:
                service.bootstrap_admin(username, "StrongAdminPassword#1")
                success.append(username)
            except AuthorizationError as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(f"admin_{n}",))
                   for n in range(2)]
        for thread in threads:
            thread.start()
        start.set()
        for thread in threads:
            thread.join(timeout=8)
            self.assertFalse(thread.is_alive())
        self.assertEqual(len(success), 1)
        self.assertEqual(len(errors), 1)

    def test_login_expiry_browser_refresh_restart_and_logout(self):
        self.assertEqual(self.security.authenticate(self.admin.session).role, Role.ADMIN)
        self.now[0] += 10
        self.assertEqual(self.security.authenticate(self.admin.session).role, Role.ADMIN)
        # A new storage object/process can read existing sessions after a restart.
        restarted = SecurityStore(self.security.directory, clock=lambda: self.now[0],
                                  idle_timeout_s=60, absolute_timeout_s=120)
        self.assertEqual(restarted.authenticate(self.admin.session).username, "admin_1")
        restarted.logout(self.admin.session)
        with self.assertRaises(AuthenticationError):
            self.security.authenticate(self.admin.session)
        tokens = self.security.login("admin_1", "StrongAdminPassword#1")
        self.now[0] += 60
        with self.assertRaises(AuthenticationError):
            restarted.authenticate(tokens.session)

    def test_passive_browser_polling_cannot_extend_idle_session(self):
        for _ in range(3):
            self.now[0] += 15
            self.assertEqual(
                self.security.authenticate(self.admin.session, touch=False).role,
                Role.ADMIN,
            )
        self.now[0] += 15
        with self.assertRaises(AuthenticationError):
            self.security.authenticate(self.admin.session, touch=False)

    def test_absolute_expiry_even_with_continuous_activity(self):
        for _ in range(3):
            self.now[0] += 30
            self.assertEqual(self.security.authenticate(self.admin.session).role, Role.ADMIN)
        self.now[0] += 30
        with self.assertRaises(AuthenticationError):
            self.security.authenticate(self.admin.session)

    def test_password_policy_and_lockout(self):
        with self.assertRaises(ValueError):
            self.security.create_user(self.admin.session, self.admin.csrf,
                                      "shortpw", "weak", Role.VIEWER)
        for _ in range(5):
            with self.assertRaises(AuthenticationError):
                self.security.login("admin_1", "wrong-password")
        with self.assertRaises(AuthenticationError):
            self.security.login("admin_1", "StrongAdminPassword#1")
        self.now[0] += 901
        self.assertEqual(self.security.login("admin_1", "StrongAdminPassword#1").session != "", True)

    def test_revoked_admin_cannot_mutate_after_pretransaction_authentication(self):
        # Deterministic simulation of another admin revoking authority between
        # the preliminary session check and BEGIN IMMEDIATE write fencing.
        original = self.security.authenticate

        def demote_after_auth(*args, **kwargs):
            actor = original(*args, **kwargs)
            with closing(sqlite3.connect(self.security.database)) as db:
                db.execute("UPDATE users SET role='VIEWER' WHERE username='admin_1'")
                db.commit()
            return actor

        with patch.object(self.security, "authenticate",
                          side_effect=demote_after_auth):
            with self.assertRaises(AuthorizationError):
                self.security.create_user(
                    self.admin.session, self.admin.csrf,
                    "injected_user", "StrongSecretPassword#2", Role.ADMIN)
        with closing(sqlite3.connect(self.security.database)) as db:
            self.assertEqual(db.execute(
                "SELECT count(*) FROM users WHERE username='injected_user'"
            ).fetchone()[0], 0)
        self.assertIn(("user.admin", "DENIED", None, "admin_1",
                       "stale or unauthorized administrator"),
                      self.security.audit_records())

    def test_role_permissions_and_no_escalation(self):
        viewer = self.add_user("viewer_1", Role.VIEWER)
        operator = self.add_user("operator_1", Role.OPERATOR)
        view_actor = self.security.authenticate(viewer.session)
        op_actor = self.security.authenticate(operator.session)
        require_permission(view_actor, Permission.READ)
        require_permission(op_actor, Permission.STOP)
        with self.assertRaises(AuthorizationError):
            require_permission(view_actor, Permission.CHAMBER_CONTROL)
        with self.assertRaises(AuthorizationError):
            require_permission(op_actor, Permission.SETTINGS)
        with self.assertRaises(AuthorizationError):
            self.security.create_user(viewer.session, viewer.csrf,
                                      "attacker", "StrongSecretPassword#2", Role.ADMIN)
        with self.assertRaises(AuthorizationError):
            self.security.change_role(operator.session, operator.csrf,
                                      "operator_1", Role.ADMIN)
        with self.assertRaises(AuthorizationError):
            self.security.change_role(self.admin.session, self.admin.csrf,
                                      "admin_1", Role.VIEWER)
        self.security.change_role(self.admin.session, self.admin.csrf,
                                  "viewer_1", Role.OPERATOR)
        with self.assertRaises(AuthenticationError):
            self.security.authenticate(viewer.session)  # Role changes revoke sessions.
        self.security.disable_user(self.admin.session, self.admin.csrf, "operator_1")
        with self.assertRaises(AuthenticationError):
            self.security.authenticate(operator.session)

    def test_mutation_requires_session_and_csrf(self):
        with self.assertRaises(AuthenticationError):
            self.security.authenticate(None, csrf=self.admin.csrf, mutation=True)
        with self.assertRaises(AuthorizationError):
            self.security.authenticate(self.admin.session, csrf="forged", mutation=True)
        with self.assertRaises(AuthorizationError):
            self.security.authenticate(self.admin.session, mutation=True)
        self.assertEqual(self.security.authenticate(
            self.admin.session, csrf=self.admin.csrf, mutation=True).role, Role.ADMIN)

    def test_concurrent_sessions_revalidate_role(self):
        viewer = self.add_user("viewer_1", Role.VIEWER)
        operator = self.add_user("operator_1", Role.OPERATOR)
        start = threading.Event()
        results = []

        def worker(tokens, desired):
            start.wait()
            actor = self.security.authenticate(tokens.session, csrf=tokens.csrf, mutation=True)
            try:
                require_permission(actor, desired)
                results.append("allowed")
            except AuthorizationError:
                results.append("denied")

        a = threading.Thread(target=worker, args=(viewer, Permission.STOP))
        b = threading.Thread(target=worker, args=(operator, Permission.STOP))
        a.start()
        b.start()
        start.set()
        a.join(5)
        b.join(5)
        self.assertCountEqual(results, ["denied", "allowed"])

    def test_authz_guard_rejects_all_unauthorized_mutations_and_audits(self):
        calls = []

        class Manager:
            def stop(self, chamber_id):
                calls.append(chamber_id)

        facade = AuthorizedChamber(Manager(), self.security)
        viewer = self.add_user("viewer_1", Role.VIEWER)
        for tokens in (None, viewer):
            with self.assertRaises((AuthenticationError, AuthorizationError)):
                facade.stop(tokens.session if tokens else None,
                            tokens.csrf if tokens else None, "device-1")
        self.assertEqual(calls, [])
        facade.stop(self.admin.session, self.admin.csrf, "device-1")
        self.assertEqual(calls, ["device-1"])
        self.assertIn(("chamber.stop", "INTENT", "device-1", "admin_1", ""),
                      self.security.audit_records())
        self.assertTrue(any(row[1] == "DENIED" for row in self.security.audit_records()))

    def test_durable_intent_fail_closed_before_device_write(self):
        called = []

        class Manager:
            def stop(self, chamber_id):
                called.append(chamber_id)

        facade = AuthorizedChamber(Manager(), self.security)
        original = self.security.audit

        def fail_intent(actor, action, outcome, *args, **kwargs):
            if outcome == "INTENT":
                raise OSError("simulated disk full")
            return original(actor, action, outcome, *args, **kwargs)

        with patch.object(self.security, "audit", side_effect=fail_intent):
            with self.assertRaises(OSError):
                facade.execute(self.admin.session, self.admin.csrf, "device-1", "stop")
        self.assertEqual(called, [])

    def test_mock_controller_stop_bypasses_lease_not_authorization(self):
        viewer = self.add_user("viewer_1", Role.VIEWER)
        operator = self.add_user("operator_1", Role.OPERATOR)
        manager = ChamberManager(
            [ChamberConfig("device-1", "fake")],
            backend_factory=lambda cfg, allow_test_backend=False: FakeBackend(cfg.chamber_id),
            lease_directory=Path(self.temp.name) / "device_owner",
        )
        self.addCleanup(lambda: manager.disconnect("device-1"))
        manager.connect("device-1")
        guarded = AuthorizedChamber(manager, self.security)
        owner_token = guarded.execute(self.admin.session, self.admin.csrf,
                                      "device-1", "claim_operator", "admin_1")
        guarded.execute(self.admin.session, self.admin.csrf, "device-1",
                        "start", operator_token=owner_token)
        with self.assertRaises(AuthorizationError):
            guarded.stop(viewer.session, viewer.csrf, "device-1")
        with self.assertRaises(AuthorizationError):
            guarded.execute(operator.session, operator.csrf, "device-1",
                            "start", operator_token=owner_token)
        with self.assertRaises(AuthorizationError):
            guarded.execute(operator.session, operator.csrf, "device-1",
                            "release_operator", owner_token)
        with self.assertRaises(AuthorizationError):
            guarded.execute(operator.session, operator.csrf, "device-1",
                            "set_temperature", 30)
        # Operator does NOT know admin's G04 ownership token, but may STOP.
        guarded.stop(operator.session, operator.csrf, "device-1")
        self.assertTrue(manager.health("device-1").stop_latched)
        self.assertEqual(manager.health("device-1").state, "VERIFIED_STOPPED")
        with self.assertRaises(AuthorizationError):
            guarded.execute(operator.session, operator.csrf,
                            "device-1", "reconcile_stop")
        guarded.execute(self.admin.session, self.admin.csrf,
                        "device-1", "reconcile_stop")


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.origins = frozenset({"http://127.0.0.1:8080"})

    def test_exact_origin_host_and_no_downgrade(self):
        self.assertTrue(valid_origin("http://127.0.0.1:8080", "127.0.0.1:8080",
                                     self.origins))
        for origin, host in [
            ("http://evil.invalid:8080", "127.0.0.1:8080"),
            ("null", "127.0.0.1:8080"),
            (None, "127.0.0.1:8080"),
            ("http://127.0.0.1:8080", "attacker.invalid:8080"),
            ("http://127.0.0.1:8080/extra", "127.0.0.1:8080"),
            ("https://127.0.0.1:8080", "127.0.0.1:8080"),
            ("http://127.0.0.1:8080@evil.invalid", "evil.invalid"),
        ]:
            self.assertFalse(valid_origin(origin, host, self.origins))

    @staticmethod
    def exercise(scope):
        events = []

        async def app(scope, receive, send):
            events.append({"type": "accepted"})

        async def send(event):
            events.append(event)

        asyncio.run(OriginMiddleware(app,
                    allowed_origins=frozenset({"http://127.0.0.1:8080"}))(
                        scope, lambda: None, send))
        return events

    @staticmethod
    def scope(kind, method="GET", *, origin=None, path="/_nicegui_ws/socket.io",
              extra=None):
        headers = [(b"host", b"127.0.0.1:8080")]
        if origin is not None:
            headers.append((b"origin", origin.encode()))
        if extra:
            headers.extend(extra)
        return {"type": kind, "method": method, "path": path, "headers": headers}

    def test_websocket_requires_trusted_origin(self):
        for origin in (None, "http://evil.invalid:8080", "null"):
            events = self.exercise(self.scope("websocket", origin=origin))
            self.assertEqual(events[0]["type"], "websocket.close")
            self.assertEqual(events[0]["code"], 1008)
        self.assertEqual(self.exercise(self.scope(
            "websocket", origin="http://127.0.0.1:8080"))[0]["type"], "accepted")

    def test_http_post_forgery_and_unregistered_mutation(self):
        for origin in (None, "http://evil.invalid:8080"):
            events = self.exercise(self.scope("http", "POST", origin=origin))
            self.assertEqual(events[0]["status"], 403)
        events = self.exercise(self.scope("http", "POST",
                               origin="http://127.0.0.1:8080",
                               path="/api/command"))
        self.assertEqual(events[0]["status"], 403)
        events = self.exercise(self.scope("http", "POST",
                               origin="http://127.0.0.1:8080"))
        self.assertEqual(events[0]["type"], "accepted")
        events = self.exercise(self.scope("http", "POST",
                               origin="http://127.0.0.1:8080",
                               extra=[(b"sec-fetch-site", b"cross-site")]))
        self.assertEqual(events[0]["status"], 403)

    def test_http_endpoint_explicit_csrf_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            sec = SecurityStore(Path(folder))
            sec.bootstrap_admin("test_admin", "StrongAdminPassword#1")
            tokens = sec.login("test_admin", "StrongAdminPassword#1")
            request = SimpleNamespace(headers={"x-csrf-token": "forged"})
            with self.assertRaises(AuthorizationError):
                authorize_http_mutation(request, sec, tokens.session, Permission.SETTINGS)
            request.headers["x-csrf-token"] = tokens.csrf
            self.assertEqual(authorize_http_mutation(
                request, sec, tokens.session, Permission.SETTINGS).role, Role.ADMIN)


if __name__ == "__main__":
    unittest.main()
