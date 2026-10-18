"""Regression: NiceGUI test isolation across module caching and test order.

``nicegui.testing`` wipes the global app's routes and middleware when a user
simulation starts, but only evicts page-registering modules from ``sys.modules``
when it ends. A composition module imported outside a simulation used to stay
cached, so the next simulation's ``main.py`` re-run was a cached no-op: the
``/login`` route (and the G08 Origin middleware added next to it) had been
erased and never came back, and every browser step failed with ``404``.
These tests fix the order deliberately: the first imports the composition the
way plain unit tests do, the second proves the next simulation still serves the
login page, and the remainder prove middleware and durable lease state do not
accumulate or leak between tests.
"""
from __future__ import annotations

import importlib
from typing import Callable

import pytest
from nicegui.testing import User


@pytest.fixture(autouse=True)
def _trusted_loopback_test_client(monkeypatch):
    """Match the loopback Host/peer the real localhost server presents."""
    original_open = User.open

    async def open_with_localhost(self, path, *, clear_forward_history=True):
        self.http_client.base_url = "http://127.0.0.1:8080"
        return await original_open(self, path,
                                   clear_forward_history=clear_forward_history)

    monkeypatch.setattr(User, "open", open_with_localhost)


def test_composition_imported_outside_a_simulation() -> None:
    """Poison the module cache exactly like a plain unit test does.

    Plain tests import ``chamber_web.ui_pages`` (which pulls in the login page
    and middleware) without ever starting a simulation, so nothing purges the
    module cache afterwards.
    """
    import chamber_web.security.nicegui  # noqa: F401
    import chamber_web.ui_pages  # noqa: F401


async def test_next_simulation_serves_the_login_page(
    create_user: Callable[[], User],
) -> None:
    user = create_user()
    await user.open("/login")
    await user.should_see("Climate Chamber — sign in")


def test_middleware_is_not_stacked_by_module_reimports() -> None:
    from nicegui import core

    from chamber_web.security.http import OriginMiddleware

    import chamber_web.security.nicegui as security_ui

    importlib.reload(security_ui)
    installed = [entry for entry in core.app.user_middleware
                 if entry.cls is OriginMiddleware]
    assert len(installed) == 1


def test_stop_latch_persists_only_for_this_test_home() -> None:
    """First half: an unreconciled STOP durably fences the lease store."""
    from chamber_web.services.ownership import DeviceLease

    lease = DeviceLease("isolation-chamber")
    lease.acquire()
    lease.close()  # not verified_stopped: uncertainty must be persisted


def test_next_test_gets_a_clean_lease_store() -> None:
    """Second half: the per-test home guarantees no cross-test latch."""
    from chamber_web.services.ownership import DeviceLease

    lease = DeviceLease("isolation-chamber")
    lease.acquire()
    try:
        assert lease.needs_reconciliation is False
    finally:
        lease.close(verified_stopped=True)
