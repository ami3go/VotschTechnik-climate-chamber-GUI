"""Isolation of per-user application state.

``chamber_web`` defaults its ownership leases, process locks and security
store to ``~/.chamber_web``. The NiceGUI composition root builds those services
at import time, so a developer's persisted leases/STOP latches (or a parallel
pytest process) would otherwise leak into tests that CI runners never see.
Redirect the home directory before any application module is imported, and
give every test its own home on top of that so combined test order can never
leak durable leases, latches, sessions or SQLite stores between tests.
"""
from __future__ import annotations

import importlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

_ISOLATED_HOME = tempfile.mkdtemp(prefix="chamber-web-test-home-")
# Captured before isolation: opt-in hardware tests share the REAL cross-process
# device lock so they can never run concurrently with a live HIL server.
REAL_HOME = str(Path.home())


def _default_playwright_browsers() -> str:
    """Playwright's default browser cache, resolved against the REAL home."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return str(Path(base) / "ms-playwright")
    if sys.platform == "darwin":
        return str(Path.home() / "Library" / "Caches" / "ms-playwright")
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return str(Path(base) / "ms-playwright")


def pytest_configure(config) -> None:
    # Keep already-installed browsers reachable; only application state moves.
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", _default_playwright_browsers())
    os.environ.setdefault("CHAMBER_TEST_REAL_HOME", REAL_HOME)
    os.environ["HOME"] = _ISOLATED_HOME
    os.environ["USERPROFILE"] = _ISOLATED_HOME


def pytest_unconfigure(config) -> None:
    shutil.rmtree(_ISOLATED_HOME, ignore_errors=True)


@pytest.fixture(autouse=True)
def _isolated_user_state(tmp_path, monkeypatch) -> None:
    """Give every test its own home directory for durable application state.

    ``chamber_web`` defaults ownership leases, the security store, the NiceGUI
    session storage and the profile SQLite files under the user home. Session
    isolation alone is not enough: an authorized STOP in one test durably
    fences the shared ownership lease, so a later browser test renders
    "STOP latch active" with disabled run controls. A per-test home makes
    leases, stores, locks and cookies independent by construction, so
    independent and combined test order agree.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))


def _rebind_cached_submodules() -> None:
    """Rebind cached ``chamber_web`` submodules into their parent packages.

    NiceGUI's simulation teardown evicts each page module *and every parent
    package* from ``sys.modules`` while non-page submodules (domain, security,
    services, ...) stay cached. The next re-import of ``chamber_web`` therefore
    builds an empty package object whose attributes are missing, so
    ``mock.patch("chamber_web.domain...")`` or ``from chamber_web.security
    import bootstrap`` fails with AttributeError even though the submodules
    exist. Rebinding each cached submodule to its parent chain restores a
    consistent package without re-executing any module body.
    """
    if not any(name.startswith("chamber_web.") for name in list(sys.modules)):
        return
    for qualified in list(sys.modules):
        if not qualified.startswith("chamber_web."):
            continue
        if sys.modules.get(qualified) is None:
            continue
        parts = qualified.split(".")
        for depth in range(1, len(parts)):
            parent_name = ".".join(parts[:depth])
            child_name = parts[depth]
            parent = sys.modules.get(parent_name)
            if parent is None:
                parent = importlib.import_module(parent_name)
            child = sys.modules.get(".".join(parts[:depth + 1]))
            if child is not None and getattr(parent, child_name, None) is not child:
                setattr(parent, child_name, child)


# The NiceGUI composition root registers pages and middleware while these
# modules import. The module cache must be rebuilt for every test so that each
# user simulation re-registration is deterministic regardless of test order.
_COMPOSITION_MODULES = (
    "chamber_web.main",
    "chamber_web.ui_pages",
    "chamber_web.security.nicegui",
    "chamber_web.pages.profiles",
    "chamber_web.pages.chamber_config",
)


@pytest.fixture(autouse=True)
def _fresh_nicegui_composition() -> None:
    """Rebuild the NiceGUI composition root before each test.

    ``nicegui.testing`` wipes the global app's routes and middleware whenever a
    user simulation starts, but only evicts modules that re-registered from
    ``sys.modules`` when it ends. A composition module imported outside a
    simulation (plain unit tests import ``chamber_web.ui_pages``) stays cached
    with its import-time ``/login`` page and G08 Origin middleware erased, so
    later simulations execute ``main.py`` as a cached no-op and browser steps
    fail with 404 on ``/login``. Evicting the composition modules per test
    makes each simulation re-import and re-register them in any order. The
    middleware stack is also cleared: a finished simulation leaves it built,
    which would make the next import-time ``add_middleware`` fail with
    Starlette's "application has started" error. The parent-package attribute
    is deleted too, otherwise ``from chamber_web import main`` would silently
    return the stale module object. Finally, cached submodules are rebound into
    their parents because NiceGUI's teardown may have evicted the parent
    packages while leaving the submodules cached.
    """
    if "nicegui" in sys.modules:
        from nicegui import core

        core.app.middleware_stack = None
        for qualified in _COMPOSITION_MODULES:
            module = sys.modules.pop(qualified, None)
            if module is None:
                continue
            parent_name, _, attribute = qualified.rpartition(".")
            parent = sys.modules.get(parent_name)
            if parent is not None and getattr(parent, attribute, None) is module:
                delattr(parent, attribute)
    _rebind_cached_submodules()
    yield


@pytest.fixture(autouse=True)
def _release_leaked_device_leases() -> None:
    """Drop in-process lease bookkeeping a test cannot release itself.

    Plain tests that import the composition root acquire the single in-process
    device lease, but only a NiceGUI lifespan shutdown releases it.
    ``frozen_self_test`` imports ``chamber_web.main`` on purpose to prove the
    frozen bundle imports, so its test leaves the module-global ``_IN_PROCESS``
    registry populated; every later controller in the session would then fail
    with "v1 allows only one active controller per process" purely because of
    test order. Per-test homes already isolate the lock files themselves; the
    abandoned composition is collected (and its handles closed) when the next
    test evicts the module cache.
    """
    yield
    from chamber_web.services import ownership

    with ownership._MUTEX:
        ownership._IN_PROCESS.clear()


@pytest.fixture(autouse=True)
def _isolate_cached_browser_execution(monkeypatch) -> None:
    """Per-test isolation when NiceGUI tests inject different SecurityStores.

    In production the G08 authority is process-stable; tests replace it on
    each browser test. A prior test's server-owned runner must never hold the
    next test's authority or profile library. No forced NiceGUI imports for
    hardware-only or domain-only test modules.
    """
    pages = sys.modules.get("chamber_web.pages.profiles")
    if pages is not None:
        monkeypatch.setattr(pages, "_execution_service", None)
        pages.get_profile_editor_service.cache_clear()
