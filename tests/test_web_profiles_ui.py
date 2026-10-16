"""G03-C/G08-min NiceGUI browser-session integration (simulated backend only)."""
import asyncio
from typing import Callable

import pytest


@pytest.fixture(autouse=True)
def _trusted_loopback_test_client(monkeypatch):
    """Exercise NiceGUI pages using the same Host and peer as the W01 loopback server.

    Only the in-process NiceGUI test client is adjusted. Production ASGI Host,
    Origin and client-address validation remains untouched and fail-closed.
    """
    from nicegui.testing.user import User

    original_open = User.open

    async def open_with_localhost(self, path, *, clear_forward_history=True):
        self.http_client.base_url = "http://127.0.0.1:8080"
        return await original_open(self, path,
                                   clear_forward_history=clear_forward_history)

    monkeypatch.setattr(User, "open", open_with_localhost)

from nicegui.testing import User

from chamber_web.security.auth import Role, SecurityStore


async def test_profiles_page_requires_login_and_persists_between_sessions(
    create_user: Callable[[], User], monkeypatch, tmp_path,
) -> None:
    from chamber_web.security import nicegui as security_ui
    from chamber_web.pages.profiles import _grid_columns, get_profile_editor_service

    store = SecurityStore(tmp_path / "security")
    store.bootstrap_admin("test_admin", "StrongAdminPassword#1")
    admin_tokens = store.login("test_admin", "StrongAdminPassword#1")
    store.create_user(admin_tokens.session, admin_tokens.csrf,
                      "test_viewer", "StrongViewerPassword#2", Role.VIEWER)
    monkeypatch.setattr(security_ui, "_store", store)

    # The profile library belongs to the server, but entry is authenticated.
    user = create_user()
    await user.open("/profiles")
    await user.should_see("sign in")
    await user.should_see("Username")

    await user.open("/login")
    user.find("Username").type("test_admin")
    user.find("Password").type("StrongAdminPassword#1")
    user.find("Sign in").click()
    await user.should_see("SIMULATION")
    await user.open("/profiles")
    await user.should_see("Persistent Profiles / Revisions")
    await user.should_see("Profile Library")
    await user.should_see("Profile Editor")
    await user.should_see("Outputs use ON / OFF / UNCHANGED")
    columns = {column["field"]: column for column in _grid_columns()}
    assert columns["chamber_run"]["cellEditorParams"]["values"] == [
        "UNCHANGED", "ON", "OFF",
    ]
    assert {"compressed_air", "dryer", "digital_outputs"} <= columns.keys()
    await user.should_see("New Temperature Profile")
    await user.should_see("Immutable Revision History")
    await user.should_see("Spreadsheet-safe CSV")
    await user.should_see("Saved revisions run only against the simulated chamber")
    await user.should_see("Profile Run")
    await user.should_see("No profile run since server start")

    viewer = create_user()
    await viewer.open("/login")
    viewer.find("Username").type("test_viewer")
    viewer.find("Password").type("StrongViewerPassword#2")
    viewer.find("Sign in").click()
    await viewer.should_see("SIMULATION")
    await viewer.open("/profiles")
    await viewer.should_see("Persistent Profiles / Revisions")

    # No browser page may retain access once the session is revoked.
    store.logout(admin_tokens.session)  # Different admin session: does not revoke browser's token.
    await user.open("/profiles")
    await user.should_see("Persistent Profiles / Revisions")
    assert get_profile_editor_service().chamber_id  # One server-assigned chamber, not browser-defined.


async def test_revoked_profile_page_cannot_be_reentered(
    create_user: Callable[[], User], monkeypatch, tmp_path,
) -> None:
    from chamber_web.security import nicegui as security_ui

    store = SecurityStore(tmp_path / "security")
    store.bootstrap_admin("test_admin", "StrongAdminPassword#1")
    monkeypatch.setattr(security_ui, "_store", store)
    browser_sessions = []
    login = store.login

    def record_login(*args, **kwargs):
        issued = login(*args, **kwargs)
        browser_sessions.append(issued.session)
        return issued

    monkeypatch.setattr(store, "login", record_login)
    user = create_user()
    await user.open("/login")
    user.find("Username").type("test_admin")
    user.find("Password").type("StrongAdminPassword#1")
    user.find("Sign in").click()
    await user.open("/profiles")
    await user.should_see("Persistent Profiles / Revisions")
    store.logout(browser_sessions[0])
    await user.open("/profiles")
    await user.should_see("sign in")


async def test_operator_runs_saved_revision_and_stops_it(
    create_user: Callable[[], User], monkeypatch, tmp_path,
) -> None:
    """Simulated FakeBackend only: the run is server-owned and STOP is verified."""
    from nicegui import ui
    from chamber_web.security import nicegui as security_ui
    from chamber_web.pages.profiles import (get_profile_editor_service,
                                            get_profile_execution_service)

    monkeypatch.setenv("CHAMBER_PROFILE_DB", str(tmp_path / "profiles.sqlite3"))
    get_profile_editor_service.cache_clear()
    store = SecurityStore(tmp_path / "security")
    store.bootstrap_admin("test_admin", "StrongAdminPassword#1")
    monkeypatch.setattr(security_ui, "_store", store)
    editor = get_profile_editor_service()
    draft = editor.edit_step(editor.new_draft(), 0, "dwell_s", "0")
    saved = editor.save(editor.set_metadata(draft, "name", "UI run profile"))

    user = create_user()
    await user.open("/login")
    user.find("Username").type("test_admin")
    user.find("Password").type("StrongAdminPassword#1")
    user.find("Sign in").click()
    await user.should_see("SIMULATION")
    await user.open("/profiles")
    await user.should_see("Profile Run")
    user.find(ui.select).elements.pop().value = saved.profile_id
    user.find("Load").click()
    await user.should_see("Loaded latest persisted revision")
    user.find("Run Loaded Revision").click()
    await user.should_see("Started revision 1 in simulation", retries=50)
    runner = get_profile_execution_service().runner
    assert runner is not None and runner.snapshot.profile_name == "UI run profile"
    await user.should_see("UI run profile rev 1", retries=50)

    user.find("Stop Run").click()
    # STOP runs off the event loop after durable audit writes; Windows CI
    # fsync latency can exceed NiceGUI's default ~0.3 s should_see window.
    for _ in range(200):
        if runner.state is not None and runner.state.value in (
            "CANCELLED", "FAULT", "UNKNOWN",
        ):
            break
        await asyncio.sleep(0.05)
    assert runner.state.value == "CANCELLED"
    await user.should_see("STOP requested", retries=50)
    await user.should_see("CANCELLED", retries=50)
    await user.should_see("request STOP reconciliation in Admin", retries=50)
    get_profile_editor_service.cache_clear()
