"""Server-owned simulated profile execution behind browser authorization.

One ProfileRunner may own the configured chamber. Its task belongs to the
server, so closing or reloading a browser does not stop a run. Every browser
mutation re-authenticates the session and CSRF token. ProfileRunner separately
rejects non-simulated chamber identities before any mutation.
"""
from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass
from typing import Callable

from chamber_web.domain.chamber import ChamberSafetyError
from chamber_web.execution.profile_runner import (
    TERMINAL, Clock, EventSink, ExecutionSnapshot, ProfileRunner, RunParameters, RunState,
)
from chamber_web.persistence.profiles import ProfileStore
from chamber_web.security.auth import Role, SecurityStore
from chamber_web.security.guards import AuthorizedChamber, Permission, require_permission
from chamber_web.services.chamber_manager import ChamberManager


@dataclass(frozen=True)
class RunEventRow:
    sequence: int
    kind: str
    state: str
    step: int
    detail: str
    temperature_c: float | None


@dataclass(frozen=True)
class RunView:
    """Browser-safe projection; never includes credentials or lease tokens."""
    state: str | None
    active: bool
    run_id: str | None
    profile_id: str | None
    profile_name: str | None
    revision: int | None
    operator: str | None
    step: int
    total_steps: int
    target_c: float | None
    elapsed_s: float | None
    reason: str
    stop_latched: bool
    controller_state: str
    simulation: bool
    can_start: bool
    can_stop: bool
    can_pause: bool
    can_resume: bool
    events: tuple[RunEventRow, ...]


class ProfileExecutionService:
    def __init__(self, manager: ChamberManager, store: ProfileStore,
                 security: SecurityStore, chamber_id: str, *, simulation: bool,
                 sink_factory: Callable[[], EventSink | None] | None = None,
                 parameters: RunParameters | None = None,
                 clock: Clock | None = None):
        if chamber_id not in manager.configured_ids():
            raise ChamberSafetyError("Profile execution chamber is not configured")
        if type(simulation) is not bool:
            raise ValueError("Trusted simulation mode must be boolean")
        self._manager = manager
        self._store = store
        self._security = security
        self._chamber_id = chamber_id
        self._simulation = simulation
        self._guard = AuthorizedChamber(manager, security)
        self._sink_factory = sink_factory
        self._parameters = parameters or RunParameters()
        self._clock = clock
        self._lock = threading.RLock()
        self._caller = threading.local()
        self._runner: ProfileRunner | None = None
        self._started_at: float | None = None
        self._task: asyncio.Task | None = None

    @property
    def chamber_id(self) -> str:
        return self._chamber_id

    @property
    def runner(self) -> ProfileRunner | None:
        with self._lock:
            return self._runner

    def _authorize(self, action: str, chamber_id: str) -> str:
        session, csrf = getattr(self._caller, "tokens", (None, None))
        return self._guard.authorize(
            session, csrf, Permission.PROFILE_RUN, chamber_id=chamber_id,
        ).username

    def _preauthorize(self, session: str | None, csrf: str | None) -> None:
        # Authorize before inspecting active-run state, then ProfileRunner
        # rechecks at its mutation boundary while the caller context is set.
        self._guard.authorize(
            session, csrf, Permission.PROFILE_RUN, chamber_id=self._chamber_id,
        )

    def _as_caller(self, session: str | None, csrf: str | None, call: Callable):
        self._caller.tokens = (session, csrf)
        try:
            return call()
        finally:
            self._caller.tokens = (None, None)

    def _active_runner(self) -> ProfileRunner:
        runner = self.runner
        if runner is None or runner.state is None or runner.state in TERMINAL:
            raise ChamberSafetyError("No active profile run")
        return runner

    def start(self, session: str | None, csrf: str | None,
              profile_id: str, revision: int) -> ExecutionSnapshot:
        """Authorize and prepare an exact saved revision; call off the event loop."""
        self._preauthorize(session, csrf)
        if not self._simulation:
            raise ChamberSafetyError("Profile execution is disabled outside simulation")
        if type(revision) is not int or revision < 1:
            raise ValueError("Choose a saved revision")
        with self._lock:
            previous = self._runner
            if (previous is not None and previous.state is not None and
                    previous.state not in TERMINAL):
                raise ChamberSafetyError("A profile run is already active")
            runner = ProfileRunner(
                self._manager, self._store, authorize=self._authorize,
                sink=self._sink_factory() if self._sink_factory else None,
                clock=self._clock,
            )
            try:
                snapshot = self._as_caller(session, csrf, lambda: runner.start(
                    self._chamber_id, profile_id, revision=revision,
                    parameters=self._parameters,
                ))
            except BaseException:
                runner.close()
                raise
            if previous is not None:
                previous.close()
            self._runner = runner
            self._started_at = time.monotonic()
            return snapshot

    async def start_async(self, session: str | None, csrf: str | None,
                          profile_id: str, revision: int) -> ExecutionSnapshot:
        snapshot = await asyncio.to_thread(
            self.start, session, csrf, profile_id, revision,
        )
        runner = self.runner
        assert runner is not None
        self._task = asyncio.get_running_loop().create_task(
            runner.run_until_terminal(), name="profile-run-" + snapshot.run_id,
        )
        return snapshot

    def cancel(self, session: str | None, csrf: str | None) -> None:
        """Any PROFILE_RUN user may request STOP; lease ownership is not required."""
        self._preauthorize(session, csrf)
        runner = self._active_runner()
        self._as_caller(session, csrf, lambda: runner.cancel(self._chamber_id))

    def pause(self, session: str | None, csrf: str | None) -> None:
        self._preauthorize(session, csrf)
        runner = self._active_runner()
        self._as_caller(session, csrf, lambda: runner.pause(self._chamber_id))

    def resume(self, session: str | None, csrf: str | None) -> None:
        self._preauthorize(session, csrf)
        runner = self._active_runner()
        self._as_caller(session, csrf, lambda: runner.resume(self._chamber_id))

    def view(self, session: str | None) -> RunView:
        """Return cached controller/run state; passive refresh never renews a session."""
        actor = self._security.authenticate(session, touch=False)
        require_permission(actor, Permission.READ)
        health = self._manager.health(self._chamber_id)
        with self._lock:
            runner, started_at = self._runner, self._started_at
        may_run = actor.role in (Role.ADMIN, Role.OPERATOR)
        state = runner.state if runner is not None else None
        active = state is not None and state not in TERMINAL
        snapshot = runner.snapshot if runner is not None else None
        step, total = runner.progress if runner is not None else (0, 0)
        target = None
        if snapshot is not None and total:
            steps = snapshot.steps * snapshot.repeat_count
            target = float(steps[min(step, total - 1)].target_temperature_c)
        events = tuple(
            RunEventRow(
                event.sequence, event.kind, event.state.value,
                event.step_index + 1, event.detail, event.temperature_c,
            )
            for event in (runner.events[-50:] if runner is not None else ())
            if event.kind != "SAMPLE"
        )
        mine = snapshot is not None and snapshot.operator_id == actor.username
        return RunView(
            state.value if state is not None else None, active,
            snapshot.run_id if snapshot else None,
            snapshot.profile_id if snapshot else None,
            snapshot.profile_name if snapshot else None,
            snapshot.revision if snapshot else None,
            snapshot.operator_id if snapshot else None,
            min(step + 1, total), total, target,
            (time.monotonic() - started_at) if started_at is not None and snapshot else None,
            runner.reason if runner is not None else "",
            health.stop_latched, health.state, self._simulation,
            may_run and self._simulation and not active and not health.stop_latched and
            health.connected and health.state == "VERIFIED_STOPPED",
            may_run and active and state is not RunState.STOP_REQUESTED,
            may_run and mine and state in (
                RunState.REACHING, RunState.STABILIZING, RunState.DWELLING,
            ),
            may_run and mine and state is RunState.PAUSED,
            events,
        )

    async def shutdown(self) -> None:
        """On server shutdown, issue trusted STOP before disconnecting the backend."""
        runner = self.runner
        if runner is not None and runner.state is not None and runner.state not in TERMINAL:
            await asyncio.to_thread(self._manager.stop, self._chamber_id)
        if self._task is not None and not self._task.done():
            try:
                await asyncio.wait_for(asyncio.shield(self._task), timeout=10)
            except (asyncio.TimeoutError, Exception):
                self._task.cancel()
        runner = self.runner
        if runner is not None and (runner.state is None or runner.state in TERMINAL):
            runner.close()
