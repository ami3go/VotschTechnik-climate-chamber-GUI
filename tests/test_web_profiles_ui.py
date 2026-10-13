"""G03-C/G08-min NiceGUI browser-session integration (simulated backend only)."""
from typing import Callable

from nicegui.testing import User

from chamber_web.security.auth import Role, SecurityStore


async def test_profiles_page_requires_login_and_persists_between_sessions(
    create_user: Callable[[], User], monkeypatch, tmp_path,
) -> None:
    from chamber_web.security import nicegui as security_ui
    from chamber_web.pages.profiles import get_profile_editor_service

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
    await user.should_see("New Temperature Profile")
    await user.should_see("Immutable Revision History")
    await user.should_see("Spreadsheet-safe CSV")
    await user.should_see("No execution controls")

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
