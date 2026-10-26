"""Composition-owned G07 run journal wiring (simulation-only tests)."""
from __future__ import annotations

import json
import os
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from chamber_web.adapters.fake import FakeBackend
from chamber_web.domain.chamber import ChamberSafetyError
from chamber_web.domain.config import ChamberConfig
from chamber_web.execution.profile_runner import TERMINAL, ProfileRunner, RunParameters, RunState
from chamber_web.persistence.profiles import ProfileStore
from chamber_web.security.auth import SecurityStore
from chamber_web.services.chamber_manager import ChamberManager
from chamber_web.services.profile_editor import ProfileEditorService
from chamber_web.services.profile_execution import ProfileExecutionService
from chamber_web.services.profile_runtime import ProfileRunRuntime, run_journal_directory


class ProfileRunRuntimeTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.security = SecurityStore(self.root / "auth")
        self.security.bootstrap_admin("test_admin", "StrongAdminPassword#1")
        self.operator = self.security.login("test_admin", "StrongAdminPassword#1")
        self.backend = FakeBackend("unit-chamber")
        self.manager = ChamberManager(
            [ChamberConfig("unit-chamber", "fake")],
            backend_factory=lambda config, **kwargs: self.backend,
            lease_directory=self.root / "ownership",
        )
        self.manager.connect("unit-chamber")
        self.addCleanup(self.manager.disconnect, "unit-chamber")
        self.profiles = ProfileStore(self.root / "profiles.sqlite")
        editor = ProfileEditorService(self.profiles, "unit-chamber")
        draft = editor.edit_step(editor.new_draft(), 0, "dwell_s", "0")
        self.saved = editor.save(draft)

    def _drain(self, runner):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if runner.advance() in TERMINAL:
                break
            time.sleep(0.005)
        return runner.state

    def _service(self, runtime) -> ProfileExecutionService:
        service = ProfileExecutionService(
            self.manager, self.profiles, self.security, "unit-chamber",
            simulation=True, sink_factory=runtime.sink_factory,
            start_blocker=runtime.start_blocker,
            parameters=RunParameters(poll_s=0.05, max_gap_s=1, max_age_s=1),
        )

        def close_runner():
            runner = service.runner
            if runner is not None and runner.state in TERMINAL:
                runner.close()
        self.addCleanup(close_runner)
        return service

    def test_runtime_records_run_and_keeps_intents_durable_before_commands(self):
        runtime = ProfileRunRuntime(self.root / "journal")
        self.assertTrue(runtime.available, runtime.error)
        service = self._service(runtime)
        snapshot = service.start(
            self.operator.session, self.operator.csrf, self.saved.profile_id, 1,
        )
        self.assertEqual(self._drain(service.runner), RunState.COMPLETED)
        store = runtime._store
        run = store.get_run("unit-chamber", snapshot.run_id)
        self.assertEqual(run["lifecycle"], "COMPLETED")
        store.verify_artifacts("unit-chamber", snapshot.run_id)
        events = store.list_events("unit-chamber", snapshot.run_id, limit=500)
        kinds = [event["kind"] for event in events]
        self.assertEqual(kinds[0], "PREPARED")
        self.assertLess(kinds.index("START_INTENT"), kinds.index("SETPOINT_INTENT"))
        self.assertLess(kinds.index("SETPOINT_INTENT"), kinds.index("SAMPLE"))
        self.assertIn("TERMINAL", kinds)
        with store._read() as db:
            row = db.execute(
                "SELECT payload_json FROM events WHERE run_id=? AND kind='SAMPLE' "
                "ORDER BY sequence LIMIT 1", (snapshot.run_id,),
            ).fetchone()
        payload = json.loads(row["payload_json"])
        self.assertIsNotNone(payload["setpoint_temperature_c"])
        self.assertEqual(
            payload["controller_generation"], snapshot.controller_generation,
        )

    def test_runtime_reconciles_abandoned_prepared_run_on_restart(self):
        runtime = ProfileRunRuntime(self.root / "journal")
        runner = ProfileRunner(
            self.manager, self.profiles,
            authorize=lambda action, chamber: "test-operator",
            sink=runtime.sink_factory(),
        )
        self.addCleanup(runner._stop_executor.shutdown, wait=False)
        snapshot = runner.start("unit-chamber", self.saved.profile_id, revision=1)
        # Simulated crash: PREPARED committed, no command intent, no terminal.
        restarted = ProfileRunRuntime(self.root / "journal")
        self.assertTrue(restarted.available, restarted.error)
        run = restarted._store.get_run("unit-chamber", snapshot.run_id)
        self.assertEqual(run["lifecycle"], "INTERRUPTED")
        events = restarted._store.list_events("unit-chamber", snapshot.run_id, limit=50)
        self.assertEqual(events[-1]["kind"], "RECOVERY")
        self.assertEqual(events[-1]["state"], "INTERRUPTED")

    def test_unavailable_journal_blocks_start_before_mutation(self):
        blocked = self.root / "journal-file"
        blocked.write_text("not a directory", encoding="utf-8")
        runtime = ProfileRunRuntime(blocked)
        self.assertFalse(runtime.available)
        self.assertIn("Run journal unavailable", runtime.error)
        with self.assertRaisesRegex(ChamberSafetyError, "Run journal unavailable"):
            runtime.sink_factory()
        service = self._service(runtime)
        view = service.view(self.operator.session)
        self.assertFalse(view.can_start)
        self.assertIn("Run journal unavailable", view.reason)
        with self.assertRaisesRegex(ChamberSafetyError, "Run journal unavailable"):
            service.start(
                self.operator.session, self.operator.csrf, self.saved.profile_id, 1,
            )
        self.assertIsNone(service.runner)
        self.assertFalse(self.backend._running)
        self.assertFalse(self.manager.health("unit-chamber").stop_latched)

    def test_page_composition_getter_injects_recording_runtime(self):
        import sys
        from types import ModuleType

        from chamber_web.pages import profiles as profiles_page

        runtime = ProfileRunRuntime(self.root / "journal")
        self.addCleanup(setattr, profiles_page, "_execution_service", None)
        self.addCleanup(setattr, profiles_page, "_profile_runtime", None)
        editor = SimpleNamespace(store=self.profiles, chamber_id="unit-chamber")
        # Stubbed composition module: the real main.py builds its own
        # controller and must not be imported by a unit test.
        stub_main = ModuleType("chamber_web.main")
        stub_main.get_dashboard_service = lambda: SimpleNamespace(manager=self.manager)
        stub_main.profile_execution_is_simulation = lambda: True
        stub_main.profile_execution_supervision = lambda: None
        stub_main.profile_execution_lab = lambda: None
        # The getter binds the G05 manual guard only when its composition
        # SecurityStore matches the page's (see profiles.py); an isolated
        # test that swaps the store must degrade to manual_guard=None.
        stub_main.get_profile_manual_guard = lambda: SimpleNamespace(_security=None)
        with patch.dict(sys.modules, {"chamber_web.main": stub_main}), \
                patch.object(profiles_page, "get_profile_editor_service", lambda: editor), \
                patch.object(profiles_page, "get_security", lambda: self.security):
            profiles_page._execution_service = None
            profiles_page._profile_runtime = runtime
            service = profiles_page.get_profile_execution_service()
        snapshot = service.start(
            self.operator.session, self.operator.csrf, self.saved.profile_id, 1,
        )
        self.assertEqual(self._drain(service.runner), RunState.COMPLETED)
        self.assertEqual(
            runtime._store.get_run("unit-chamber", snapshot.run_id)["lifecycle"],
            "COMPLETED",
        )
        service.runner.close()

    def test_run_journal_directory_honors_env_override(self):
        target = self.root / "custom-journal"
        with patch.dict(os.environ, {"CHAMBER_RUN_JOURNAL_DIR": str(target)}):
            self.assertEqual(run_journal_directory(), target)


if __name__ == "__main__":
    unittest.main()
