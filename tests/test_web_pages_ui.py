"""G02-B NiceGUI page/browser smoke tests (FakeBackend only)."""
from typing import Callable

import pytest
from nicegui import ui
from nicegui.testing import User


def _table_with_column(user: User, field: str):
    """Pick the rendered ui.table whose columns include ``field``."""
    from nicegui import ui
    candidates = [element for element in user.find(ui.table).elements
                  if any(column.get("field") == field for column in element.columns)]
    assert candidates, f"no ui.table with column {field!r} is rendered"
    return candidates[-1]


@pytest.fixture(autouse=True)
def _trusted_loopback_test_client(monkeypatch):
    """Model W01's trusted loopback Host only in the in-process NiceGUI client.

    Do not weaken the production ASGI Host/Origin gate: "testserver" must
    continue to return 403. Other test modules retain their own fixtures.
    """
    original_open = User.open

    async def open_with_localhost(self, path, *, clear_forward_history=True):
        self.http_client.base_url = "http://127.0.0.1:8080"
        return await original_open(
            self, path, clear_forward_history=clear_forward_history
        )

    monkeypatch.setattr(User, "open", open_with_localhost)


async def test_read_only_routes_and_repeat_browsers(create_user: Callable[[], User], monkeypatch, tmp_path) -> None:
    # The composition runtime is process-global and may be imported by another
    # NiceGUI test before this test's HOME fixture takes effect. Pin the G07
    # journal itself before importing the composition root so "empty" is a
    # property of this test, not of suite order.
    monkeypatch.setenv("CHAMBER_RUN_JOURNAL_DIR", str(tmp_path / "run-journal"))
    from chamber_web import main as application
    from chamber_web.security import nicegui as security_ui
    from chamber_web.security.auth import SecurityStore

    store = SecurityStore(tmp_path / "security")
    store.bootstrap_admin("test_admin", "StrongAdminPassword#1")
    monkeypatch.setattr(security_ui, "_store", store)
    monkeypatch.setattr(application._manual_service, "_security", store)
    monkeypatch.setattr(application._manual_service._authorized, "_security", store)
    captured = []
    original_login = store.login

    def recording_login(*args, **kwargs):
        tokens = original_login(*args, **kwargs)
        captured.append(tokens.session)
        return tokens

    monkeypatch.setattr(store, "login", recording_login)
    user = create_user()
    await user.open("/history")
    await user.should_see("Sign in", retries=30)
    await user.open("/login")
    user.find("Username").type("test_admin")
    user.find("Password").type("StrongAdminPassword#1")
    user.find("Sign in").click()
    await user.should_see("SIMULATION", retries=30)
    for url, heading in (
        ("/history", "Run History"),
        ("/logs", "Persistent Event Logs"),
        ("/settings", "Server Configuration (read-only)"),
        ("/profiles", "Persistent Profiles / Revisions"),
        ("/admin", "Operator Lease"),
    ):
        await user.open(url)
        await user.should_see(heading, retries=30)
        await user.should_see("SIMULATION", retries=30)
    await user.open("/history")
    # G07-C readers are wired to the composition-owned journal. Filter on a
    # sentinel that cannot occur so this remains deterministic even when
    # another collection-time composition import already opened its journal.
    user.find("Search recorded run ID or profile").type("__no_such_run__")
    user.find(kind=ui.button, content="Search").click()
    await user.should_see("No recorded runs match this search.", retries=30)
    other = create_user()
    await other.open("/login")
    await other.should_see("Sign in", retries=30)
    await user.open("/logs")
    user.find("Filter recorded messages").type("__no_such_event__")
    user.find(kind=ui.button, content="Apply filters").click()
    await user.should_see("No recorded events match the filters.", retries=30)
    await user.open("/settings")
    await user.should_see("Control availability", retries=30)
    await user.should_see("Physical controls disabled", retries=30)

    # An already-rendered page must not return history after a role or
    # session is revoked; guard callbacks, not only page creation.
    await user.open("/history")
    store.logout(captured[0])
    user.find("Search").click()
    await user.should_see("Sign in", retries=30)


async def test_recorded_runs_and_events_render_from_the_composition_journal(
    create_user: Callable[[], User], monkeypatch, tmp_path,
) -> None:
    """G07-C: /history and /logs project the one owned journal, not fabrications."""
    monkeypatch.setenv("CHAMBER_RUN_JOURNAL_DIR", str(tmp_path / "run-journal"))
    from dataclasses import dataclass
    from uuid import uuid4

    from chamber_web import main as application
    from chamber_web.pages.profiles import get_profile_runtime
    from chamber_web.persistence.runs import RunRecorder
    from chamber_web.security import nicegui as security_ui
    from chamber_web.security.auth import SecurityStore

    store = SecurityStore(tmp_path / "security")
    store.bootstrap_admin("test_admin", "StrongAdminPassword#1")
    monkeypatch.setattr(security_ui, "_store", store)
    monkeypatch.setattr(application._manual_service, "_security", store)
    monkeypatch.setattr(application._manual_service._authorized, "_security", store)

    @dataclass(frozen=True)
    class Identity:
        chamber_id: str
        backend_id: str = "fake"
        manufacturer: str = "Simulator"
        model: str = "Mock"
        serial_number: str = "TEST"
        is_simulation: bool = True

    @dataclass(frozen=True)
    class Snapshot:
        schema_version: int
        run_id: str
        chamber_id: str
        identity: object
        controller_generation: int
        created_at_utc: str
        profile_name: str
        revision: int
        operator_id: str

    @dataclass(frozen=True)
    class Event:
        run_id: str
        chamber_id: str
        sequence: int
        kind: str
        state: str = "PREPARING"
        monotonic_elapsed_s: float = 0.0
        step_index: int = 0
        detail: str = ""
        temperature_c: float | None = None
        quality: str | None = None
        observed_at_utc: str = "2026-10-13T12:00:00+00:00"
        source_sampled_at_utc: str | None = None
        sample_index: int | None = None

    # Seed the exact journal the composition root serves /history and /logs.
    runtime = get_profile_runtime()
    assert runtime.available, runtime.error
    chamber_id = application.get_dashboard_service().view().chamber_id
    recorder = RunRecorder(runtime.store)
    run_id = str(uuid4())
    time = "2026-10-13T12:00:00+00:00"
    recorder.prepare(Snapshot(1, run_id, chamber_id, Identity(chamber_id), 4, time,
                              "Cold soak", 3, "op-7"))
    recorder.emit(Event(run_id, chamber_id, 1, "PREPARED"))
    recorder.emit(Event(run_id, chamber_id, 2, "START_INTENT"))
    recorder.emit(Event(run_id, chamber_id, 3, "STATE", state="FAULT",
                        detail="controller fault observed"))

    user = create_user()
    await user.open("/login")
    user.find("Username").type("test_admin")
    user.find("Password").type("StrongAdminPassword#1")
    user.find("Sign in").click()
    await user.should_see("SIMULATION", retries=30)

    await user.open("/history")
    # Quasar tables render rows client-side, so assert the server-provided rows
    # rather than relying on cell text in the server element tree.
    history_table = _table_with_column(user, "run_id")
    assert any(row["run_id"] == run_id for row in history_table.rows)
    assert any(row["profile"] == "Cold soak · r3" for row in history_table.rows)
    assert any(row["operator"] == "op-7" for row in history_table.rows)

    await user.open("/logs")
    logs_table = _table_with_column(user, "severity")
    assert any(row["message"] == "controller fault observed" for row in logs_table.rows)
    assert any(row["severity"] == "ERROR" for row in logs_table.rows)


async def test_settings_tab_saves_chamber_connection_for_admin(
    create_user: Callable[[], User], monkeypatch, tmp_path,
) -> None:
    from nicegui import ui

    from chamber_web import main as application
    from chamber_web.hil import chamber_settings
    from chamber_web.security import nicegui as security_ui
    from chamber_web.security.auth import SecurityStore

    store = SecurityStore(tmp_path / "security")
    store.bootstrap_admin("test_admin", "StrongAdminPassword#1")
    monkeypatch.setattr(security_ui, "_store", store)
    monkeypatch.setattr(application._manual_service, "_security", store)
    monkeypatch.setattr(application._manual_service._authorized, "_security", store)
    settings_file = tmp_path / "chamber_settings.json"
    monkeypatch.setattr(chamber_settings, "settings_path", lambda: settings_file)

    user = create_user()
    await user.open("/login")
    user.find("Username").type("test_admin")
    user.find("Password").type("StrongAdminPassword#1")
    user.find("Sign in").click()
    await user.should_see("SIMULATION", retries=30)
    await user.open("/settings")
    await user.should_see("Chamber Connection", retries=30)
    await user.should_see("Running: Simulator (no hardware)", retries=30)
    user.find(ui.select).elements.pop().set_value("votsch")
    user.find(kind=ui.input, content="Chamber ID").clear().type("lab-1")
    user.find("IP address (private IPv4)").clear().type("192.168.10.20")
    user.find("Expected serial number").clear().type("ABC123")
    user.find(ui.checkbox).elements.pop().set_value(True)
    user.find("Current administrator password (required to save)").type(
        "StrongAdminPassword#1")
    user.find("Save chamber settings").click()
    await user.should_see("Restart the server to apply them", retries=30)
    saved = chamber_settings.load_settings(settings_file)
    assert (saved.chamber_type, saved.address, saved.expected_serial) == (
        "votsch", "192.168.10.20", "ABC123")
    # The running process is unchanged until restart.
    assert application.active_chamber_authorization()[0] is None
