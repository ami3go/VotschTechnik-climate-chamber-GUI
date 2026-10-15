"""Typed chamber port; NO device protocol, driver, or UI dependencies."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol


class ChamberError(RuntimeError):
    """Application-level error with no implicit hardware state transition."""


class ChamberConnectionError(ChamberError):
    pass


class ChamberTimeoutError(ChamberError):
    pass


class ChamberProtocolError(ChamberError):
    pass


class UnsupportedCapability(ChamberError):
    pass


class ChamberSafetyError(ChamberError):
    pass


class ChamberIdentityMismatch(ChamberError):
    pass


class OperationState(str, Enum):
    STOPPED = "STOPPED"
    RUNNING = "RUNNING"
    UNKNOWN = "UNKNOWN"
    FAULT = "FAULT"


class ReadingQuality(str, Enum):
    GOOD = "GOOD"
    STALE = "STALE"
    ERROR = "ERROR"


def validate_chamber_id(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", value) is None:
        raise ChamberSafetyError("Invalid chamber_id: use 1-64 ASCII letters, numbers, _ or -")
    return value


def finite_temperature(value: float, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ChamberSafetyError("Temperature must be numeric")
    number = float(value)
    if not all(math.isfinite(v) for v in (number, minimum, maximum)):
        raise ChamberSafetyError("Temperature and envelope must be finite")
    if minimum >= maximum or not minimum <= number <= maximum:
        raise ChamberSafetyError("Temperature outside approved capability range")
    return number


@dataclass(frozen=True)
class ChamberIdentity:
    chamber_id: str
    backend_id: str
    manufacturer: str
    model: str
    serial_number: str | None
    is_simulation: bool = False

    def __post_init__(self) -> None:
        validate_chamber_id(self.chamber_id)


@dataclass(frozen=True)
class ChamberCapabilities:
    temperature_min_c: float
    temperature_max_c: float
    supports_start_stop: bool
    supports_running_readback: bool
    supports_setpoint_readback: bool
    supports_ramp_up: bool = False
    supports_ramp_down: bool = False
    ramp_up_range_c_per_min: tuple[float, float] | None = None
    ramp_down_range_c_per_min: tuple[float, float] | None = None
    # (up, down) °C/min when the setpoint READBACK follows a device-side ramp
    # toward a new target (e.g. Vötsch 11002); None = readback is immediate.
    setpoint_readback_ramp_c_per_min: tuple[float, float] | None = None


@dataclass(frozen=True)
class ChamberSnapshot:
    identity: ChamberIdentity
    measured_temperature_c: float | None
    setpoint_temperature_c: float | None
    operation_state: OperationState
    quality: ReadingQuality
    sampled_at_utc: datetime | None


class ChamberBackend(Protocol):
    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def identify(self) -> ChamberIdentity: ...
    def capabilities(self) -> ChamberCapabilities: ...
    def read_status(self) -> ChamberSnapshot: ...
    def set_temperature(self, target_c: float) -> None: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def set_ramp_up(self, rate_c_per_min: float) -> None: ...
    def set_ramp_down(self, rate_c_per_min: float) -> None: ...
