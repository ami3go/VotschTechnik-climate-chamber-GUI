"""Session-wide isolation of per-user application state.

``chamber_web`` defaults its ownership leases, process locks and security
store to ``~/.chamber_web``. The NiceGUI composition root builds those services
at import time, so a developer's persisted leases/STOP latches (or a parallel
pytest process) would otherwise leak into tests that CI runners never see.
Redirect the home directory before any application module is imported.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

_ISOLATED_HOME = tempfile.mkdtemp(prefix="chamber-web-test-home-")


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
    os.environ["HOME"] = _ISOLATED_HOME
    os.environ["USERPROFILE"] = _ISOLATED_HOME


def pytest_unconfigure(config) -> None:
    shutil.rmtree(_ISOLATED_HOME, ignore_errors=True)
