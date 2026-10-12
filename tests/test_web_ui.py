"""G08-min NiceGUI login gate: no anonymous access to the dashboard."""
from typing import Callable

from nicegui.testing import User


async def test_anonymous_dashboard_redirects_to_login(create_user: Callable[[], User]) -> None:
    user = create_user()
    await user.open("/")
    await user.should_see("Climate Chamber")
    await user.should_see("sign in")
    await user.should_see("Username")
    await user.should_see("Password")

 
async def test_login_refresh_logout_and_other_browser(
    create_user: Callable[[], User], monkeypatch, tmp_path,
) -> None:
    from chamber_web.security import nicegui as security_ui
    from chamber_web.security.auth import SecurityStore

    store = SecurityStore(tmp_path / "security")
    store.bootstrap_admin("test_admin", "StrongAdminPassword#1")
    monkeypatch.setattr(security_ui, "_store", store)

    first = create_user()
    second = create_user()
    await first.open("/login")
    first.find("Username").type("test_admin")
    first.find("Password").type("StrongAdminPassword#1")
    first.find("Sign in").click()
    await first.should_see("SIMULATION")
    await first.should_see("Signed in: test_admin (ADMIN)")

    await second.open("/")
    await second.should_see("sign in")
    # A browser page reload preserves the signed cookie and DB session.
    await first.open("/")
    await first.should_see("Signed in: test_admin (ADMIN)")
    first.find("Sign out").click()
    await first.should_see("sign in")
    await first.open("/")
    await first.should_see("sign in")
