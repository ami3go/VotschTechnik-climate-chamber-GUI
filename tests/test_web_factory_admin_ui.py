"""NiceGUI factory sign-in and administrator credential control smoke."""
from __future__ import annotations

from typing import Callable

import pytest
from nicegui.testing import User


@pytest.fixture(autouse=True)
def _trusted_loopback_test_client(monkeypatch):
    original_open = User.open

    async def open_with_localhost(self, path, *, clear_forward_history=True):
        self.http_client.base_url = "http://127.0.0.1:8080"
        return await original_open(self, path,
                                   clear_forward_history=clear_forward_history)

    monkeypatch.setattr(User, "open", open_with_localhost)


async def test_factory_admin_login_change_password_and_relogin(
    create_user: Callable[[], User], monkeypatch, tmp_path,
) -> None:
    from chamber_web import main as application
    from chamber_web.security import nicegui as security_ui
    from chamber_web.security.auth import SecurityStore

    store = SecurityStore(tmp_path / "security")
    store.provision_factory_admin()
    monkeypatch.setattr(security_ui, "_store", store)
    monkeypatch.setattr(application._manual_service, "_security", store)
    monkeypatch.setattr(application._manual_service._authorized, "_security", store)

    user = create_user()
    await user.open("/login")
    await user.should_see("Factory credentials in use")
    user.find("Username").type("admin")
    user.find("Password").type("admin")
    user.find("Sign in").click()
    await user.should_see("Signed in: admin (ADMIN)")
    await user.open("/admin")
    await user.should_see("Administrator Credentials")
    await user.should_see("Change username")
    await user.should_see("New 6–12 digit PIN")
    user.find("Current administrator password").type("admin")
    user.find("New administrator password (12+ bytes)").type("DifferentPassword#123")
    user.find("Repeat new administrator password").type("DifferentPassword#123")
    user.find("Change password").click()
    await user.should_see("sign in", retries=30)
    await user.open("/login")
    user.find("Username").type("admin")
    user.find("Password").type("DifferentPassword#123")
    user.find("Sign in").click()
    await user.should_see("Signed in: admin (ADMIN)")
    assert store.factory_credentials_active() == (False, True)
