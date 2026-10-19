"""G05 NiceGUI event integration, browser refresh and read-only viewer smoke."""
from __future__ import annotations

from typing import Callable

import pytest
from nicegui.testing import User


@pytest.fixture(autouse=True)
def _trusted_loopback_test_client(monkeypatch):
    """Use W01's trusted loopback Host in the in-process NiceGUI client.

    The G08 ASGI Host/Origin gate must keep rejecting "testserver" with 403.
    """
    original_open = User.open

    async def open_with_localhost(self, path, *, clear_forward_history=True):
        self.http_client.base_url = "http://127.0.0.1:8080"
        return await original_open(
            self, path, clear_forward_history=clear_forward_history
        )

    monkeypatch.setattr(User, "open", open_with_localhost)


async def test_manual_dashboard_two_browsers_and_authorized_stop(
    create_user: Callable[[], User], monkeypatch, tmp_path,
) -> None:
    from chamber_web import main as application
    from chamber_web.security import nicegui as security_ui
    from chamber_web.security.auth import Role, SecurityStore

    security = SecurityStore(tmp_path / "security")
    security.bootstrap_admin("control_admin", "StrongAdminPassword#1")
    admin = security.login("control_admin", "StrongAdminPassword#1")
    security.create_user(admin.session, admin.csrf, "control_viewer",
                         "StrongViewerPassword#2", Role.VIEWER)
    # NiceGUI's authenticated login store and the composition-root service
    # must share the SAME G08-min authority (never parallel auth state).
    monkeypatch.setattr(security_ui, "_store", security)
    monkeypatch.setattr(application._manual_service, "_security", security)
    monkeypatch.setattr(application._manual_service._authorized, "_security", security)

    first = create_user()
    viewer = create_user()
    await first.open("/login")
    first.find("Username").type("control_admin")
    first.find("Password").type("StrongAdminPassword#1")
    first.find("Sign in").click()
    await first.should_see("SIMULATION ONLY", retries=30)
    await first.open("/admin")
    await first.should_see("Lease state: RELEASED", retries=30)
    await first.should_see("Claim", retries=30)
    await first.should_see("Controller: VERIFIED_STOPPED", retries=30)

    first.find("Claim").click()
    await first.should_see("CONFIRMED", retries=40)
    await first.should_see("Lease state: CLAIMED", retries=30)
    await first.open("/")
    await first.should_see("Web STOP is a best-effort control command", retries=30)

    # A fresh browser page must dispatch as the currently authenticated
    # operator. The lease owner can STOP and then START again without admin
    # reconciliation; STOP itself never requires passing the G04 token.
    first.find("Start").click()
    await first.should_see("CONFIRMED", retries=40)
    first.find("Stop").click()
    await first.should_see("controls ready", retries=40)
    first.find("Start").click()
    await first.should_see("CONFIRMED", retries=40)
    first.find("Stop").click()
    await first.should_see("controls ready", retries=40)
    await first.open("/admin")
    await first.should_see("fence clear", retries=40)
    await first.should_see("Lease state: CLAIMED", retries=40)
    first.find("Release").click()
    await first.should_see("Lease state: RELEASED", retries=40)

    # An independent VIEWER client may read but cannot command the chamber.
    await viewer.open("/login")
    viewer.find("Username").type("control_viewer")
    viewer.find("Password").type("StrongViewerPassword#2")
    viewer.find("Sign in").click()
    await viewer.should_see("SIMULATION ONLY", retries=30)
    await viewer.should_see("read only", retries=30)
    await viewer.open("/admin")
    await viewer.should_see("Chamber Control", retries=30)


async def test_admin_security_profiles_panel_is_role_restricted(
    create_user: Callable[[], User], monkeypatch, tmp_path,
) -> None:
    """Live NiceGUI page must expose new policy controls only to administrators."""
    from chamber_web import main as application
    from chamber_web.security import nicegui as security_ui
    from chamber_web.security.auth import Role, SecurityStore

    security = SecurityStore(tmp_path / "profiles_ui_security")
    security.bootstrap_admin("profile_admin", "StrongAdminPassword#1")
    administrator = security.login("profile_admin", "StrongAdminPassword#1")
    security.create_user(administrator.session, administrator.csrf,
                         "profile_viewer", "StrongViewerPassword#2", Role.VIEWER)
    monkeypatch.setattr(security_ui, "_store", security)
    monkeypatch.setattr(application._manual_service, "_security", security)
    monkeypatch.setattr(application._manual_service._authorized, "_security", security)

    browser = create_user()
    await browser.open("/login")
    browser.find("Username").type("profile_admin")
    browser.find("Password").type("StrongAdminPassword#1")
    browser.find("Sign in").click()
    await browser.should_see("Signed in: profile_admin (ADMIN)", retries=30)
    await browser.open("/admin")
    await browser.should_see("Security Profiles", retries=30)
    await browser.should_see("Account to enroll for PIN login", retries=30)
    await browser.should_see("Apply security profile", retries=30)

    viewer = create_user()
    await viewer.open("/login")
    viewer.find("Username").type("profile_viewer")
    viewer.find("Password").type("StrongViewerPassword#2")
    viewer.find("Sign in").click()
    await viewer.should_see("Signed in: profile_viewer (VIEWER)", retries=30)
    await viewer.open("/admin")
    await viewer.should_see("Chamber Control", retries=30)
