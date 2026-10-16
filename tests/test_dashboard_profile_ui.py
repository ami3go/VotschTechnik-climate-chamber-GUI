"""Dashboard profile-run NiceGUI integration (FakeBackend only)."""
from __future__ import annotations

import asyncio
from typing import Callable

import pytest
from nicegui import ui
from nicegui.testing import User

from chamber_web.security.auth import Role, SecurityStore


@pytest.fixture(autouse=True)
def _trusted_loopback_test_client(monkeypatch):
    """Follow the production loopback origin policy in in-process browser tests."""
    original_open = User.open

    async def open_with_localhost(self, path, *, clear_forward_history=True):
        self.http_client.base_url = "http://127.0.0.1:8080"
        return await original_open(
            self, path, clear_forward_history=clear_forward_history,
        )

    monkeypatch.setattr(User, "open", open_with_localhost)


async def test_dashboard_starts_saved_revision_shares_state_and_stops(
    create_user: Callable[[], User], monkeypatch, tmp_path,
) -> None:
    from chamber_web.security import nicegui as security_ui
    from chamber_web.pages import profiles as profiles_page

    monkeypatch.setenv("CHAMBER_PROFILE_DB", str(tmp_path / "profiles.sqlite3"))
    profiles_page.get_profile_editor_service.cache_clear()
    monkeypatch.setattr(profiles_page, "_execution_service", None)
    security = SecurityStore(tmp_path / "security")
    security.bootstrap_admin("test_admin", "StrongAdminPassword#1")
    monkeypatch.setattr(security_ui, "_store", security)

    editor = profiles_page.get_profile_editor_service()
    draft = editor.set_metadata(editor.new_draft(), "name", "Dashboard run profile")
    draft = editor.edit_step(draft, 0, "target_temperature_c", "85")
    draft = editor.edit_step(draft, 0, "dwell_s", "0")
    saved = editor.save(draft)

    user = create_user()
    await user.open("/login")
    user.find("Username").type("test_admin")
    user.find("Password").type("StrongAdminPassword#1")
    user.find("Sign in").click()
    await user.should_see("SIMULATION", retries=50)

    await user.open("/")
    await user.should_see("Active Profile")
    await user.should_see("No profile run since server start")
    await user.should_see("Saved profile")
    await user.should_see("Run Profile")

    # The final dashboard select is the saved profile selector (the first is
    # the manual temperature preset). This selects, but does NOT auto-start.
    user.find(ui.select).elements[-1].value = saved.profile_id
    await user.should_see("Dashboard run profile · rev 1", retries=50)
    execution = profiles_page.get_profile_execution_service()
    assert execution.runner is None

    user.find("Run Profile").click()
    await user.should_see("Started saved revision 1 in simulation", retries=50)
    runner = execution.runner
    assert runner is not None
    assert runner.snapshot.profile_id == saved.profile_id
    assert runner.snapshot.revision == 1

    # Navigating away doesn't create a new runner or abandon the run.
    await user.open("/profiles")
    await user.should_see("Dashboard run profile rev 1", retries=50)
    await user.open("/")
    await user.should_see("Dashboard run profile rev 1", retries=50)
    assert execution.runner is runner

    user.find("Stop Run").click()
    await user.should_see("STOP requested", retries=50)
    for _ in range(200):
        if runner.state is not None and runner.state.value in (
            "CANCELLED", "FAULT", "UNKNOWN",
        ):
            break
        await asyncio.sleep(0.05)
    assert runner.state.value == "CANCELLED"
    await user.should_see("CANCELLED", retries=50)
    assert execution.view(security.login("test_admin", "StrongAdminPassword#1").session).stop_latched


async def test_dashboard_viewer_cannot_start_or_stop(
    create_user: Callable[[], User], monkeypatch, tmp_path,
) -> None:
    from chamber_web.security import nicegui as security_ui
    from chamber_web.pages import profiles as profiles_page

    monkeypatch.setenv("CHAMBER_PROFILE_DB", str(tmp_path / "profiles.sqlite3"))
    profiles_page.get_profile_editor_service.cache_clear()
    monkeypatch.setattr(profiles_page, "_execution_service", None)
    security = SecurityStore(tmp_path / "security")
    security.bootstrap_admin("test_admin", "StrongAdminPassword#1")
    admin = security.login("test_admin", "StrongAdminPassword#1")
    security.create_user(
        admin.session, admin.csrf,
        "test_viewer", "StrongViewerPassword#2", Role.VIEWER,
    )
    monkeypatch.setattr(security_ui, "_store", security)
    editor = profiles_page.get_profile_editor_service()
    saved = editor.save(editor.new_draft())

    user = create_user()
    await user.open("/login")
    user.find("Username").type("test_viewer")
    user.find("Password").type("StrongViewerPassword#2")
    user.find("Sign in").click()
    await user.should_see("SIMULATION", retries=50)
    await user.open("/")
    await user.should_see("Run Profile")
    user.find(ui.select).elements[-1].value = saved.profile_id
    await user.should_see("New Temperature Profile · rev 1", retries=50)
    assert not profiles_page.get_profile_execution_service().view(
        security.login("test_viewer", "StrongViewerPassword#2").session
    ).can_start
    assert profiles_page.get_profile_execution_service().runner is None


async def test_dashboard_physical_execution_remains_locked(
    create_user: Callable[[], User], monkeypatch, tmp_path,
) -> None:
    """Even with a saved profile, physical execution is denied at service boundary."""
    from chamber_web.main import get_dashboard_service
    from chamber_web.pages import profiles as profiles_page
    from chamber_web.security import nicegui as security_ui
    from chamber_web.services.profile_execution import ProfileExecutionService

    monkeypatch.setenv("CHAMBER_PROFILE_DB", str(tmp_path / "profiles.sqlite3"))
    profiles_page.get_profile_editor_service.cache_clear()
    security = SecurityStore(tmp_path / "security")
    security.bootstrap_admin("test_admin", "StrongAdminPassword#1")
    monkeypatch.setattr(security_ui, "_store", security)
    editor = profiles_page.get_profile_editor_service()
    editor.save(editor.new_draft())
    isolated = ProfileExecutionService(
        get_dashboard_service().manager, editor.store, security, editor.chamber_id,
        simulation=False,
    )
    monkeypatch.setattr(profiles_page, "_execution_service", isolated)
    user = create_user()
    await user.open("/login")
    user.find("Username").type("test_admin")
    user.find("Password").type("StrongAdminPassword#1")
    user.find("Sign in").click()
    await user.open("/")
    await user.should_see("Physical HIL: profile execution disabled")
    assert not isolated.view(
        security.login("test_admin", "StrongAdminPassword#1").session
    ).can_start
    assert isolated.runner is None
