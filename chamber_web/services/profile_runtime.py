"""Composition-owned G07 run journal for profile execution.

The server composition root (not a NiceGUI page) creates exactly one RunStore
per deployment, reconciles interrupted runs once at startup - offline, without
dispatching any G04 command - and injects a RunRecorder for every profile run.
A journal that cannot initialize or reconcile leaves the runtime fail-closed:
starting a run is refused before any chamber mutation, never retried silently.
"""
from __future__ import annotations

import os
from pathlib import Path
import threading

from chamber_web.domain.chamber import ChamberSafetyError
from chamber_web.persistence.runs import RunRecorder, RunStore


def run_journal_directory() -> Path:
    """Trusted process-owned storage, never a user/browser-selected pathname."""
    configured = os.environ.get("CHAMBER_RUN_JOURNAL_DIR")
    if configured:
        return Path(configured).expanduser()
    if os.name == "nt":
        from chamber_web.windows_runtime import state_dir
        return state_dir() / "runs"
    return Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state"))) / (
        "climate-chamber/runs"
    )


class ProfileRunRuntime:
    """One reconciled run journal per deployment; recording fails closed."""

    def __init__(self, root: str | Path):
        self._lock = threading.Lock()
        self._store: RunStore | None = None
        self.error = ""
        try:
            store = RunStore(root)
            # Offline, exactly once, before any run is accepted. Interrupted
            # PREPARED runs become INTERRUPTED; started runs become UNKNOWN;
            # no G04 command is ever dispatched during reconciliation.
            store.reconcile_startup()
        except Exception as exc:
            self.error = f"Run journal unavailable: {type(exc).__name__}: {exc}"
        else:
            self._store = store

    @property
    def available(self) -> bool:
        return self._store is not None

    def start_blocker(self) -> str:
        """Empty when runs may start; otherwise the fail-closed reason."""
        return self.error

    def sink_factory(self) -> RunRecorder:
        with self._lock:
            store = self._store
        if store is None:
            raise ChamberSafetyError(self.error or "Run journal unavailable")
        return RunRecorder(store)
