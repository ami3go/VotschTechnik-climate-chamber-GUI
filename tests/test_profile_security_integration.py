"""End-to-end simulated G03-C/G06-A/G08-min authorization and STOP regression.

Only FakeBackend is constructed. No real chamber, vendor driver or HIL used.
"""
from __future__ import annotations

import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from chamber_web.adapters.fake import FakeBackend
from chamber_web.domain.config import ChamberConfig
from chamber_web.execution.profile_runner import ProfileRunner, RunState
from chamber_web.persistence.profiles import ProfileStore
from chamber_web.security.auth import AuthenticationError, AuthorizationError, Role, SecurityStore
from chamber_web.security.guards import AuthorizedChamber, Permission
from chamber_web.services.chamber_manager import ChamberManager
from chamber_web.services.profile_editor import ProfileEditorService


class ProfileSecurityIntegrationTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.security = SecurityStore(root / "auth")
        self.security.bootstrap_admin("test_admin", "StrongAdminPassword#1")
        self.admin = self.security.login("test_admin", "StrongAdminPassword#1")
        for name, role in (("test_operator", Role.OPERATOR), ("test_viewer", Role.VIEWER)):
            self.security.create_user(self.admin.session, self.admin.csrf,
                                      name, "LongUniqueSecret#123", role)
        self.operator = self.security.login("test_operator", "LongUniqueSecret#123")
        self.viewer = self.security.login("test_viewer", "LongUniqueSecret#123")
        self.active = self.viewer
        self.backend = FakeBackend("simulated-chamber")
        self.manager = ChamberManager(
            [ChamberConfig("simulated-chamber", "fake")],
            backend_factory=lambda config, **kwargs: self.backend,
            lease_directory=root / "controller",
        )
        self.manager.connect("simulated-chamber")
        self.addCleanup(self.manager.disconnect, "simulated-chamber")
        self.store = ProfileStore(root / "profiles.sqlite3")
        self.editor = ProfileEditorService(self.store, "simulated-chamber")
        self.guarded = AuthorizedChamber(self.manager, self.security)
        self.runner = ProfileRunner(
            self.manager, self.store,
            authorize=lambda action, cid: self.guarded.authorize(
                self.active.session, self.active.csrf,
                Permission.PROFILE_RUN, chamber_id=cid).username,
        )
        self.addCleanup(self.runner.close)

    def test_saved_revision_authentication_revocation_and_cancel_verified_stop(self):
        draft = self.editor.new_draft()
        draft = self.editor.edit_step(draft, 0, "dwell_s", "0")
        saved = self.editor.save(draft)
        historical = self.editor.open(saved.profile_id, revision=1)
        self.assertEqual(historical.profile, saved.profile)
        # Persist a newer immutable revision; run preparation chooses an exact revision.
        edited = self.editor.edit_step(saved, 0, "notes", "Revised notes")
        revision2 = self.editor.save(edited)
        self.assertEqual(revision2.viewed_revision, 2)
        self.assertNotEqual(
            self.editor.open(saved.profile_id, revision=1).profile,
            self.editor.open(saved.profile_id, revision=2).profile,
        )
        with self.assertRaises(AuthorizationError):
            self.runner.start("simulated-chamber", saved.profile_id, revision=1)
        self.assertFalse(self.backend._running)
        with self.assertRaises(AuthorizationError):
            self.guarded.stop(self.viewer.session, self.viewer.csrf, "simulated-chamber")
        self.assertFalse(self.backend._running)

        self.active = self.operator
        snapshot = self.runner.start("simulated-chamber", saved.profile_id, revision=1)
        self.assertEqual(snapshot.profile_id, saved.profile_id)
        self.assertEqual(snapshot.revision, 1)
        self.runner.advance()  # Start on FakeBackend only.
        self.assertTrue(self.backend._running)
        self.security.disable_user(
            self.admin.session, self.admin.csrf, "test_operator",
        )
        with self.assertRaises(AuthenticationError):
            self.runner.cancel("simulated-chamber")
        self.assertTrue(self.backend._running)  # Denied request did not dispatch STOP.
        self.active = self.admin
        self.runner.cancel("simulated-chamber")
        for _ in range(200):
            state = self.runner.advance()
            if state in (RunState.CANCELLED, RunState.UNKNOWN, RunState.FAULT):
                break
            time.sleep(0.005)
        self.assertEqual(self.runner.state, RunState.CANCELLED)
        self.assertFalse(self.backend._running)
        self.assertTrue(self.manager.health("simulated-chamber").stop_latched)
        records = self.security.audit_records()
        self.assertTrue(any(row[1] == "DENIED" for row in records))
        self.assertTrue(any(row[0] == Permission.PROFILE_RUN.value
                            and row[1] == "AUTHORIZED" for row in records))
