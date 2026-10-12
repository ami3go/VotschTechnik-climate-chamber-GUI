"""Read-only server-owned dashboard projection (G02-A).

All backend reads execute in a worker thread. No NiceGUI client owns a chamber
or can issue a command through this service. A later controller will implement
authenticated, fenced mutations; this module deliberately offers none.
"""
from __future__ import annotations

import asyncio
import math
import time
from collections import deque
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from chamber_web.domain.chamber import (
    ChamberCapabilities, ChamberIdentity, ChamberSafetyError,
    OperationState, ReadingQuality, validate_chamber_id,
)

if TYPE_CHECKING:
    from chamber_web.services.chamber_manager import ChamberManager


@dataclass(frozen=True)
class TemperatureSample:
    time_utc: datetime
    measured_c: float
    target_c: float | None


@dataclass(frozen=True)
class DashboardView:
    chamber_id: str
    identity: ChamberIdentity | None = None
    capabilities: ChamberCapabilities | None = None
    measured_temperature_c: float | None = None
    setpoint_temperature_c: float | None = None
    operation_state: OperationState = OperationState.UNKNOWN
    quality: ReadingQuality = ReadingQuality.ERROR
    sampled_at_utc: datetime | None = None
    error: str | None = "Awaiting server telemetry"


class DashboardService:
    """One per server process; clients consume the same immutable projection.

    The owning process connects a deliberate test backend during bootstrap.
    Pages only read view()/recent_samples(); polling continues with no browser
    attached. An injected manager is never connected or mutated by this class.
    """

    def __init__(self, manager: ChamberManager, chamber_id: str, *,
                 poll_interval_s: float = 1.0, stale_after_s: float = 5.0,
                 disconnect_on_close: bool = False):
        self.chamber_id = validate_chamber_id(chamber_id)
        # Validate the route before a backend call can occur.
        manager.get(chamber_id)
        if poll_interval_s <= 0 or stale_after_s <= 0:
            raise ValueError("Polling and stale deadlines must be positive")
        self._manager = manager
        self._disconnect_on_close = disconnect_on_close
        self._interval = poll_interval_s
        self._stale_after = stale_after_s
        self._view = DashboardView(chamber_id)
        self._samples: deque[TemperatureSample] = deque(maxlen=1500)
        self._last_good_at: float | None = None
        self._poll_lock = asyncio.Lock()
        self._task: asyncio.Task | None = None

    def _read(self):
        return (self._manager.status(self.chamber_id),
                self._manager.capabilities(self.chamber_id))

    async def poll_once(self) -> DashboardView:
        """Get a new snapshot off the UI event loop; serialize overlapping polls."""
        async with self._poll_lock:
            try:
                snapshot, caps = await asyncio.to_thread(self._read)
                if snapshot.identity.chamber_id != self.chamber_id:
                    raise ChamberSafetyError("Telemetry identity mismatch")
                if snapshot.quality is not ReadingQuality.GOOD:
                    raise ChamberSafetyError("Unusable chamber reading")
                measured, target = (snapshot.measured_temperature_c,
                                    snapshot.setpoint_temperature_c)
                if measured is None or not math.isfinite(measured) or (
                    target is not None and not math.isfinite(target)
                ):
                    raise ChamberSafetyError("Invalid/nonfinite telemetry")
                if snapshot.sampled_at_utc is None or snapshot.sampled_at_utc.tzinfo is None:
                    raise ChamberSafetyError("Missing timezone-aware sample timestamp")
                sample_age_s = (datetime.now(timezone.utc) -
                                snapshot.sampled_at_utc.astimezone(timezone.utc)).total_seconds()
                if not -self._stale_after <= sample_age_s <= self._stale_after:
                    raise ChamberSafetyError("Expired or future-dated telemetry")
                self._view = DashboardView(
                    chamber_id=self.chamber_id,
                    identity=snapshot.identity,
                    capabilities=caps,
                    measured_temperature_c=measured,
                    setpoint_temperature_c=target,
                    operation_state=snapshot.operation_state,
                    quality=ReadingQuality.GOOD,
                    sampled_at_utc=snapshot.sampled_at_utc,
                    error=None,
                )
                self._samples.append(TemperatureSample(snapshot.sampled_at_utc, measured, target))
                self._last_good_at = time.monotonic()
            except Exception as exc:
                # Fail closed: don't display the previous value or running state
                # as a current verified reading after a transport failure.
                self._view = replace(
                    self._view, measured_temperature_c=None,
                    setpoint_temperature_c=None, operation_state=OperationState.UNKNOWN,
                    quality=ReadingQuality.ERROR, sampled_at_utc=None,
                    error=f"Telemetry unavailable ({type(exc).__name__})",
                )
            return self._view

    def view(self) -> DashboardView:
        """Atomic immutable snapshot, with an independent stale-age watchdog."""
        current = self._view
        if current.quality is ReadingQuality.GOOD and (
            self._last_good_at is None or time.monotonic() - self._last_good_at > self._stale_after
        ):
            return replace(current, measured_temperature_c=None,
                           setpoint_temperature_c=None,
                           operation_state=OperationState.UNKNOWN,
                           quality=ReadingQuality.STALE,
                           error="Telemetry stale; chamber state unverified")
        return current

    def recent_samples(self) -> tuple[TemperatureSample, ...]:
        return tuple(self._samples)

    async def _poll_forever(self) -> None:
        while True:
            await self.poll_once()
            await asyncio.sleep(self._interval)

    async def start(self) -> None:
        if self._task is None or self._task.done():
            await self.poll_once()
            self._task = asyncio.create_task(self._poll_forever())

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._disconnect_on_close:
            await asyncio.to_thread(self._manager.disconnect, self.chamber_id)
            self._disconnect_on_close = False
