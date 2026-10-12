"""v1 one-instance manager. No fleet runtime, no production hardware activation.

G01 routing is intentionally limited to a single serialized mock instance.
A production ChamberController with leases/fencing must replace this seam at G04.
"""
from __future__ import annotations

from threading import RLock
from typing import Callable

from chamber_web.domain.chamber import (
    ChamberBackend, ChamberSafetyError, OperationState, ReadingQuality,
    validate_chamber_id,
)
from chamber_web.domain.config import ChamberConfig


class ChamberManager:
    def __init__(self, configurations: list[ChamberConfig], *,
                 backend_factory: Callable, allow_test_backend=False):
        if len(configurations) != 1:
            raise ChamberSafetyError("v1 requires exactly one configured chamber; "
                                     "multiple physical devices are not supported")
        self._config = configurations[0]
        self._lock = RLock()
        self._backend: ChamberBackend = backend_factory(
            self._config, allow_test_backend=allow_test_backend
        )
        self._connected = False
        self._stop_latched = False

    def configured_ids(self) -> tuple[str, ...]:
        return (self._config.chamber_id,)

    def _backend_for_id(self, chamber_id: str) -> ChamberBackend:
        validate_chamber_id(chamber_id)
        if chamber_id != self._config.chamber_id:
            raise ChamberSafetyError("Wrong/stale chamber_id: operation refused")
        return self._backend

    def get(self, chamber_id: str) -> "ChamberManager":
        """Return the guarded controller facade, never a raw backend."""
        self._backend_for_id(chamber_id)
        return self

    def connect(self, chamber_id: str) -> None:
        with self._lock:
            backend = self._backend_for_id(chamber_id)
            if self._connected:
                return
            backend.connect()
            if backend.identify().chamber_id != chamber_id:
                backend.disconnect()
                raise ChamberSafetyError("Backend identity mismatch")
            self._connected = True

    def disconnect(self, chamber_id: str) -> None:
        with self._lock:
            backend = self._backend_for_id(chamber_id)
            try:
                backend.disconnect()
            finally:
                self._connected = False
                self._stop_latched = True

    def status(self, chamber_id: str):
        with self._lock:
            return self._backend_for_id(chamber_id).read_status()

    def capabilities(self, chamber_id: str):
        """Read backend capabilities through the ID-guarded manager facade."""
        with self._lock:
            return self._backend_for_id(chamber_id).capabilities()

    def set_temperature(self, chamber_id: str, target_c: float) -> None:
        with self._lock:
            backend = self._guard_mutation(chamber_id)
            caps = backend.capabilities()
            if not caps.supports_setpoint_readback:
                raise ChamberSafetyError("Cannot control without setpoint readback")
            backend.set_temperature(target_c)

    def start(self, chamber_id: str) -> None:
        with self._lock:
            backend = self._guard_mutation(chamber_id)
            caps = backend.capabilities()
            if not caps.supports_start_stop or not caps.supports_running_readback:
                raise ChamberSafetyError("Backend not certified for run control")
            backend.start()

    def stop(self, chamber_id: str) -> None:
        with self._lock:
            backend = self._backend_for_id(chamber_id)
            self._stop_latched = True
            if not self._connected:
                raise ChamberSafetyError("STOP cannot be verified: not connected")
            backend.stop()

    def _guard_mutation(self, chamber_id: str) -> ChamberBackend:
        backend = self._backend_for_id(chamber_id)
        if not self._connected or self._stop_latched:
            raise ChamberSafetyError("Operation blocked: disconnected or STOP-latched")
        return backend

    def reconcile_stop(self, chamber_id: str) -> None:
        with self._lock:
            backend = self._backend_for_id(chamber_id)
            snapshot = backend.read_status()
            if not self._connected or snapshot.quality is not ReadingQuality.GOOD or (
                snapshot.operation_state is not OperationState.STOPPED
            ):
                raise ChamberSafetyError("STOP not verified; manual reconciliation required")
            self._stop_latched = False
