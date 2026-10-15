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
import tempfile

_ISOLATED_HOME = tempfile.mkdtemp(prefix="chamber-web-test-home-")


def pytest_configure(config) -> None:
    os.environ["HOME"] = _ISOLATED_HOME
    os.environ["USERPROFILE"] = _ISOLATED_HOME


def pytest_unconfigure(config) -> None:
    shutil.rmtree(_ISOLATED_HOME, ignore_errors=True)
