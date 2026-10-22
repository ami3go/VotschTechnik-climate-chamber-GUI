"""Deterministic, explicitly simulated backend; no sockets or hardware."""
from __future__ import annotations

import math
import time
from datetime import datetime, timezone

from chamber_web.domain.chamber import (
    ChamberCapabilities, ChamberIdentity, ChamberSnapshot, OperationState,
    ReadingQuality, UnsupportedCapability, finite_temperature,
)


class FakeBackend:
    # Safe pre-connect marker: never opens a physical connection.
    simulation_only = True
    def __init__(self, chamber_id: str, *, minimum: float = -40, maximum: float = 130,
                 slew_c_per_s: float = 0.0,
                 ramp_range_c_per_min: tuple[float, float] | None = None):
        if (isinstance(slew_c_per_s, bool) or
                not isinstance(slew_c_per_s, (int, float)) or
                not math.isfinite(slew_c_per_s) or not 0 <= slew_c_per_s <= 10):
            raise ValueError("Simulated slew must be finite, 0..10 °C/s")
        if ramp_range_c_per_min is not None and (
                not isinstance(ramp_range_c_per_min, tuple) or
                len(ramp_range_c_per_min) != 2 or
                any(isinstance(v, bool) or not isinstance(v, (int, float)) or
                    not math.isfinite(v) or not 0 < v <= 60
                    for v in ramp_range_c_per_min) or
                ramp_range_c_per_min[0] > ramp_range_c_per_min[1]):
            raise ValueError("Simulated gradient range must be finite, 0..60 °C/min")
        self._ramp_range = ramp_range_c_per_min
        self._gradient_up: float | None = None
        self._gradient_down: float | None = None
        self._slew = float(slew_c_per_s)
        self._slewed_at = time.monotonic()
        self._identity = ChamberIdentity(chamber_id, "fake", "SIMULATION", "Fake", None, True)
        self._caps = ChamberCapabilities(
            minimum, maximum, True, True, True,
            supports_ramp_up=ramp_range_c_per_min is not None,
            supports_ramp_down=ramp_range_c_per_min is not None,
            ramp_up_range_c_per_min=ramp_range_c_per_min,
            ramp_down_range_c_per_min=ramp_range_c_per_min,
            setpoint_readback_ramp_c_per_min=(
                (ramp_range_c_per_min[0], ramp_range_c_per_min[0])
                if ramp_range_c_per_min is not None else None),
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

    def _advance_simulation(self) -> None:
        now = time.monotonic()
        elapsed, self._slewed_at = now - self._slewed_at, now
        if self._slew and self._running and self._connected:
            distance = self._target - self._measured
            change = self._slew * max(0.0, elapsed)
            self._measured = (self._target if abs(distance) <= change else
                              self._measured + math.copysign(change, distance))

    def read_status(self) -> ChamberSnapshot:
        self._advance_simulation()
        return ChamberSnapshot(
            self._identity, self._measured if self._connected else None,
            self._target if self._connected else None,
            (OperationState.RUNNING if self._running else OperationState.STOPPED)
            if self._connected else OperationState.UNKNOWN,
            ReadingQuality.GOOD if self._connected else ReadingQuality.ERROR,
            datetime.now(timezone.utc) if self._connected else None,
            gradient_up_c_per_min=self._gradient_up if self._connected else None,
            gradient_down_c_per_min=self._gradient_down if self._connected else None,
        )

    def set_temperature(self, target_c: float) -> None:
        self._advance_simulation()
        if not self._connected:
            raise UnsupportedCapability("Fake backend is not connected")
        self._target = finite_temperature(
            target_c, self._caps.temperature_min_c, self._caps.temperature_max_c
        )

    def start(self) -> None:
        self._advance_simulation()
        if not self._connected:
            raise UnsupportedCapability("Fake backend is not connected")
        self._running = True
        self._digital_outputs[1] = True

    def stop(self) -> None:
        self._advance_simulation()
        self._running = False
        self._digital_outputs[1] = False

    def read_digital_output(self, number: int) -> bool:
        if not self._connected or number not in self._digital_outputs:
            raise UnsupportedCapability("Digital output is unavailable")
        return self._digital_outputs[number]

    def set_digital_output(self, number: int, state: bool) -> None:
        self._advance_simulation()
        if not self._connected or number not in self._digital_outputs or type(state) is not bool:
            raise UnsupportedCapability("Digital output is unavailable")
        if number == 1:
            self._running = state
        self._digital_outputs[number] = state

    def _checked_ramp(self, rate_c_per_min: float) -> float:
        if not self._connected or self._ramp_range is None:
            raise UnsupportedCapability("Simulated gradients are not enabled")
        if (isinstance(rate_c_per_min, bool) or
                not isinstance(rate_c_per_min, (int, float)) or
                not math.isfinite(rate_c_per_min)):
            raise UnsupportedCapability("Invalid simulated gradient")
        low, high = self._ramp_range
        if not low <= float(rate_c_per_min) <= high:
            raise UnsupportedCapability("Simulated gradient outside supported range")
        return float(rate_c_per_min)

    def set_ramp_up(self, rate_c_per_min: float) -> None:
        self._gradient_up = self._checked_ramp(rate_c_per_min)

    def set_ramp_down(self, rate_c_per_min: float) -> None:
        self._gradient_down = self._checked_ramp(rate_c_per_min)
