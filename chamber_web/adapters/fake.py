"""Deterministic, explicitly simulated backend; no sockets or hardware."""
from __future__ import annotations

from datetime import datetime, timezone

from chamber_web.domain.chamber import (
    ChamberCapabilities, ChamberIdentity, ChamberSnapshot, OperationState,
    ReadingQuality, UnsupportedCapability, finite_temperature,
)


class FakeBackend:
    # Safe pre-connect marker: never opens a physical connection.
    simulation_only = True
    def __init__(self, chamber_id: str, *, minimum: float = -40, maximum: float = 130):
        self._identity = ChamberIdentity(chamber_id, "fake", "SIMULATION", "Fake", None, True)
        self._caps = ChamberCapabilities(
            minimum, maximum, True, True, True,
            digital_outputs=tuple(
                (number, {1: "Chamber run", 7: "Compressed air", 8: "Dryer"}.get(
                    number, f"Digital output {number}"))
                for number in range(1, 17)
            ),
        )
        self._connected = False
        self._running = False
        self._target = 25.0
        self._measured = 25.0
        self._digital_outputs = {number: False for number in range(1, 17)}

    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False
        self._running = False
        self._digital_outputs[1] = False

    def identify(self) -> ChamberIdentity:
        return self._identity

    def capabilities(self) -> ChamberCapabilities:
        return self._caps

    def read_status(self) -> ChamberSnapshot:
        return ChamberSnapshot(
            self._identity, self._measured if self._connected else None,
            self._target if self._connected else None,
            (OperationState.RUNNING if self._running else OperationState.STOPPED)
            if self._connected else OperationState.UNKNOWN,
            ReadingQuality.GOOD if self._connected else ReadingQuality.ERROR,
            datetime.now(timezone.utc) if self._connected else None,
        )

    def set_temperature(self, target_c: float) -> None:
        if not self._connected:
            raise UnsupportedCapability("Fake backend is not connected")
        self._target = finite_temperature(
            target_c, self._caps.temperature_min_c, self._caps.temperature_max_c
        )

    def start(self) -> None:
        if not self._connected:
            raise UnsupportedCapability("Fake backend is not connected")
        self._running = True
        self._digital_outputs[1] = True

    def stop(self) -> None:
        self._running = False
        self._digital_outputs[1] = False

    def read_digital_output(self, number: int) -> bool:
        if not self._connected or number not in self._digital_outputs:
            raise UnsupportedCapability("Digital output is unavailable")
        return self._digital_outputs[number]

    def set_digital_output(self, number: int, state: bool) -> None:
        if not self._connected or number not in self._digital_outputs or type(state) is not bool:
            raise UnsupportedCapability("Digital output is unavailable")
        if number == 1:
            self._running = state
        self._digital_outputs[number] = state

    def set_ramp_up(self, rate_c_per_min: float) -> None:
        raise UnsupportedCapability("Fake backend does not certify hardware gradients")

    def set_ramp_down(self, rate_c_per_min: float) -> None:
        raise UnsupportedCapability("Fake backend does not certify hardware gradients")
