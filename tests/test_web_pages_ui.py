"""G02-B NiceGUI page/browser smoke tests (FakeBackend only)."""
from typing import Callable

from nicegui.testing import User


async def test_read_only_routes_and_repeat_browsers(create_user: Callable[[], User], monkeypatch, tmp_path) -> None:
    from chamber_web.security import nicegui as security_ui
    from chamber_web.security.auth import SecurityStore

    store = SecurityStore(tmp_path / "security")
    store.bootstrap_admin("test_admin", "StrongAdminPassword#1")
    monkeypatch.setattr(security_ui, "_store", store)
    captured = []
    original_login = store.login

    def recording_login(*args, **kwargs):
        tokens = original_login(*args, **kwargs)
        captured.append(tokens.session)
        return tokens

    monkeypatch.setattr(store, "login", recording_login)
    user = create_user()
    await user.open("/history")
    await user.should_see("sign in")
    await user.open("/login")
    user.find("Username").type("test_admin")
    user.find("Password").type("StrongAdminPassword#1")
    user.find("Sign in").click()
    await user.should_see("SIMULATION")
    for url, heading in (
        ("/history", "Run History"),
        ("/logs", "Persistent Event Logs"),
        ("/settings", "Server Configuration (read-only)"),
        ("/profiles", "Profiles editor — G03-C"),
    ):
        await user.open(url)
        await user.should_see(heading)
        await user.should_see("SIMULATION")
    await user.open("/history")
    await user.should_see("G07 run recording/history service is not installed.")
    other = create_user()
    await other.open("/logs")
    await other.should_see("sign in")
    await user.open("/logs")
    await user.should_see("G07 persistent event/audit log service is not installed.")
    await user.open("/settings")
    await user.should_see("Control availability")
    await user.should_see("Physical controls disabled")

    # An already-rendered page must not return history after a role or
    # session is revoked; guard callbacks, not only page creation.
    await user.open("/history")
    store.logout(captured[0])
    user.find("Search").click()
    await user.should_see("sign in")

