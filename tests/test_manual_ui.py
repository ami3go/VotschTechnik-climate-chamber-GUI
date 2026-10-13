"""G05 NiceGUI event integration, browser refresh and read-only viewer smoke."""
from __future__ import annotations

from typing import Callable

from nicegui.testing import User


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
    await first.should_see("SIMULATION ONLY")
    await first.should_see("Claim")
    await first.should_see("Controller: VERIFIED_STOPPED")
    await first.should_see("Web STOP is a best-effort control command")

    first.find("Claim").click()
    await first.should_see("CONFIRMED")
    await first.open("/")
    await first.should_see("you hold control")

    await viewer.open("/login")
    viewer.find("Username").type("control_viewer")
    viewer.find("Password").type("StrongViewerPassword#2")
    viewer.find("Sign in").click()
    await viewer.should_see("SIMULATION ONLY")
    await viewer.should_see("read only")

    # After browser refresh the server-owned owner identity survives, and an
    # ADMIN can STOP without the currently active operator lease token.
    first.find("Stop").click()
    await first.should_see("CONFIRMED")
    await first.should_see("STOP/reconciliation required")
