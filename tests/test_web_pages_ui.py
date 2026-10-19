"""G02-B NiceGUI page/browser smoke tests (FakeBackend only)."""
from typing import Callable

import pytest
from nicegui.testing import User


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
    await user.should_see("G07 run recording/history service is not installed.", retries=30)
    other = create_user()
    await other.open("/logs")
    await other.should_see("Sign in", retries=30)
    await user.open("/logs")
    await user.should_see("G07 persistent event/audit log service is not installed.", retries=30)
    await user.open("/settings")
    await user.should_see("Control availability", retries=30)
    await user.should_see("Physical controls disabled", retries=30)

    # An already-rendered page must not return history after a role or
    # session is revoked; guard callbacks, not only page creation.
    await user.open("/history")
    store.logout(captured[0])
    user.find("Search").click()
    await user.should_see("Sign in", retries=30)


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
