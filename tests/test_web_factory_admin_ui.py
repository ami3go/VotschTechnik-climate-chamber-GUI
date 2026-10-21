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
    await user.should_see("Factory administrator password and PIN are still active", retries=30)
    user.find("Username").type("admin")
    user.find("Password").type("admin")
    user.find("Sign in").click()
    await user.should_see("Signed in: admin (ADMIN)", retries=30)
    await user.open("/admin")
    await user.should_see("Administrator Credentials", retries=30)
    await user.should_see("Change username", retries=30)
    await user.should_see("New 6–12 digit PIN", retries=30)
    user.find("Current administrator password").type("admin")
    user.find("New administrator password (12+ bytes)").type("DifferentPassword#123")
    user.find("Repeat new administrator password").type("DifferentPassword#123")
    user.find("Change password").click()
    await user.should_see("sign in", retries=30)
    # Emulate a server restart with a newly constructed persistent store, not
    # merely a second browser interaction with the same in-memory instance.
    restarted = SecurityStore(tmp_path / "security")
    assert restarted.provision_factory_admin() is False
    assert restarted.factory_credentials_active() == (False, True)
    monkeypatch.setattr(security_ui, "_store", restarted)
    monkeypatch.setattr(application._manual_service, "_security", restarted)
    monkeypatch.setattr(application._manual_service._authorized, "_security", restarted)
    await user.open("/login")
    await user.should_see("Administrator password has been changed", retries=30)
    await user.should_see("Only the factory PIN is still active", retries=30)
    user.find("Username").type("admin")
    user.find("Password").type("DifferentPassword#123")
    user.find("Sign in").click()
    await user.should_see("Signed in: admin (ADMIN)", retries=30)
    assert restarted.factory_credentials_active() == (False, True)


async def test_admin_can_create_enabled_operator_from_user_accounts_panel(
    create_user: Callable[[], User], monkeypatch, tmp_path,
) -> None:
    from chamber_web import main as application
    from chamber_web.security import nicegui as security_ui
    from chamber_web.security.auth import Role, SecurityStore

    store = SecurityStore(tmp_path / "security")
    store.bootstrap_admin("test_admin", "StrongAdminPassword#1")
    monkeypatch.setattr(security_ui, "_store", store)
    monkeypatch.setattr(application._manual_service, "_security", store)
    monkeypatch.setattr(application._manual_service._authorized, "_security", store)

    user = create_user()
    await user.open("/login")
    user.find("Username").type("test_admin")
    user.find("Password").type("StrongAdminPassword#1")
    user.find("Sign in").click()
    await user.open("/admin")
    await user.should_see("User Accounts", retries=30)
    user.find("New account username").type("operator_1")
    user.find("New account password (12+ bytes)").type(
        "StrongOperatorPassword#2"
    )
    user.find("Repeat new account password").type(
        "StrongOperatorPassword#2"
    )
    user.find("Create enabled user").click()
    await user.should_see("User created and enabled.", retries=30)

    operator = store.login("operator_1", "StrongOperatorPassword#2")
    assert store.authenticate(operator.session).role is Role.OPERATOR
    accounts = store.list_users(store.login(
        "test_admin", "StrongAdminPassword#1"
    ).session)
    assert any(
        account.username == "operator_1"
        and account.role is Role.OPERATOR
        and account.enabled
        for account in accounts
    )
