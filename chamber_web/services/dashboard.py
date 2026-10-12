"""Read-only dashboard projection over the one-device, vendor-neutral manager.

G02-A does not implement a controller, profile runner, hardware controls or
physical STOP. A bounded observation cache belongs to the server, not a page.
"""
from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from threading import RLock

from chamber_web.domain.chamber import (
    ChamberCapabilities,
    ChamberError,
    ChamberIdentity,
    ChamberSafetyError,
    ChamberSnapshot,
    OperationState,
    ReadingQuality,
)
from chamber_web.services.chamber_manager import ChamberManager


@dataclass(frozen=True)
class DashboardObservation:
    sampled_at_utc: datetime
    measured_temperature_c: float | None
    setpoint_temperature_c: float | None


@dataclass(frozen=True)
class DashboardView:
    snapshot: ChamberSnapshot
    capabilities: ChamberCapabilities
    observations: tuple[DashboardObservation, ...]
    error: str | None = None


class DashboardService:
    """Single configured device, shared across tabs. No hardware write API.

    Production construction is confined to the fixed FakeBackend bootstrap.
    Other backends can be injected in *separate* test instances to verify that
    the projection and UI are independent of manufacturer-specific DTOs.
    """

    def __init__(self, manager: ChamberManager, chamber_id: str, *,
                 history_limit: int = 240) -> None:
        if manager.configured_ids() != (chamber_id,):
            raise ChamberSafetyError("Dashboard must bind the configured chamber_id")
        if not 1 <= history_limit <= 2000:
            raise ValueError("history_limit must be 1..2000")
        self._manager = manager
        self.chamber_id = chamber_id
        self._observations: deque[DashboardObservation] = deque(maxlen=history_limit)
        self._lock = RLock()
        self._identity: ChamberIdentity | None = None

    def connect(self) -> None:
        """Bootstrap-only connection; called once before serving browser pages."""
        self._manager.connect(self.chamber_id)
        identity = self._manager.status(self.chamber_id).identity
        if identity.chamber_id != self.chamber_id:
            raise ChamberSafetyError("Dashboard identity mismatch")
        self._identity = identity

    def read(self, chamber_id: str) -> DashboardView:
        if chamber_id != self.chamber_id:
            raise ChamberSafetyError("Wrong/stale dashboard chamber_id")
        with self._lock:
            if self._identity is None:
                raise ChamberSafetyError("Dashboard service has not been connected")
            caps = self._manager.capabilities(chamber_id)
            try:
                snapshot = self._manager.status(chamber_id)
                if snapshot.identity != self._identity:
                    raise ChamberSafetyError("Discovered chamber identity changed")
            except ChamberError as exc:
                # Do not re-use a previously GOOD measurement after a read fault.
                snapshot = ChamberSnapshot(
                    self._identity, None, None, OperationState.UNKNOWN,
                    ReadingQuality.ERROR, None,
                )
                return DashboardView(
                    snapshot, caps, tuple(self._observations),
                    f"Status unavailable: {type(exc).__name__}",
                )
            if snapshot.quality is not ReadingQuality.GOOD:
                # A non-GOOD reading cannot be promoted to a current temperature
                # or an assured RUNNING/STOPPED state by the dashboard.
                state = (OperationState.FAULT if snapshot.operation_state
                         is OperationState.FAULT else OperationState.UNKNOWN)
                snapshot = ChamberSnapshot(
                    snapshot.identity, None, None, state,
                    snapshot.quality, None,
                )
                return DashboardView(
                    snapshot, caps, tuple(self._observations),
                    f"Status quality: {snapshot.quality.value}",
                )
            if (snapshot.quality is ReadingQuality.GOOD
                    and snapshot.sampled_at_utc is not None):
                self._observations.append(DashboardObservation(
                    snapshot.sampled_at_utc, snapshot.measured_temperature_c,
                    snapshot.setpoint_temperature_c,
                ))
            return DashboardView(snapshot, caps, tuple(self._observations))

    async def read_async(self, chamber_id: str) -> DashboardView:
        """Never run synchronous backend read methods on NiceGUI's event loop."""
        return await asyncio.to_thread(self.read, chamber_id)
