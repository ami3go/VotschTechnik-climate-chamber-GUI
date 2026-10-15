"""Explicit, launch-time authorization for ONE supervised physical Vötsch HIL.

Physical I/O stays disabled unless the server process is started with a
COMPLETE ``CHAMBER_HIL_*`` environment. Nothing here is selectable from a
browser, and any partial or invalid configuration refuses to start (fail
closed) instead of silently falling back to, or away from, simulation.

The envelope is a software guard only. A person must be present at the
chamber and the chamber's own controller limits and emergency stop remain
the primary safety layer.
"""
from __future__ import annotations

import ipaddress
import math
from dataclasses import dataclass
from typing import Mapping

from chamber_web.domain.chamber import ChamberSafetyError, validate_chamber_id

ACKNOWLEDGEMENT = "SUPERVISED-PHYSICAL-HIL"
HARD_MIN_C = -40.0
HARD_MAX_C = 130.0
MAX_ENVELOPE_SPAN_C = 30.0

_KEYS = (
    "CHAMBER_HIL_ADDRESS", "CHAMBER_HIL_EXPECTED_SERIAL",
    "CHAMBER_HIL_TEMP_MIN_C", "CHAMBER_HIL_TEMP_MAX_C", "CHAMBER_HIL_ACK",
)


@dataclass(frozen=True)
class HilAuthorization:
    chamber_id: str
    address: str
    expected_serial: str
    temperature_min_c: float
    temperature_max_c: float

    def __post_init__(self) -> None:
        validate_chamber_id(self.chamber_id)
        try:
            ip = ipaddress.ip_address(self.address)
        except ValueError as exc:
            raise ChamberSafetyError("HIL address must be a literal IPv4 address") from exc
        if ip.version != 4 or not ip.is_private or ip.is_loopback or ip.is_unspecified:
            raise ChamberSafetyError("HIL address must be a private, non-loopback IPv4 address")
        if not self.expected_serial or not self.expected_serial.isalnum():
            raise ChamberSafetyError("HIL expected serial number must be alphanumeric")
        lo, hi = self.temperature_min_c, self.temperature_max_c
        if not (math.isfinite(lo) and math.isfinite(hi) and lo < hi):
            raise ChamberSafetyError("HIL temperature envelope must be finite with min < max")
        if lo < HARD_MIN_C or hi > HARD_MAX_C or hi - lo > MAX_ENVELOPE_SPAN_C:
            raise ChamberSafetyError(
                f"HIL envelope must lie within {HARD_MIN_C}..{HARD_MAX_C} °C "
                f"and span at most {MAX_ENVELOPE_SPAN_C} °C")


def hil_authorization_from_env(env: Mapping[str, str]) -> HilAuthorization | None:
    """None when no HIL variable is set; otherwise a complete, valid authorization."""
    present = {key: env.get(key, "").strip() for key in _KEYS}
    if not any(present.values()):
        return None
    missing = [key for key, value in present.items() if not value]
    if missing:
        raise ChamberSafetyError("Incomplete physical HIL configuration: " + ", ".join(missing))
    if present["CHAMBER_HIL_ACK"] != ACKNOWLEDGEMENT:
        raise ChamberSafetyError(
            f"CHAMBER_HIL_ACK must be exactly {ACKNOWLEDGEMENT!r} (person present at chamber)")
    try:
        lo = float(present["CHAMBER_HIL_TEMP_MIN_C"])
        hi = float(present["CHAMBER_HIL_TEMP_MAX_C"])
    except ValueError as exc:
        raise ChamberSafetyError("HIL temperature envelope must be numeric") from exc
    return HilAuthorization(
        env.get("CHAMBER_HIL_CHAMBER_ID", "").strip() or "hil-votsch",
        present["CHAMBER_HIL_ADDRESS"], present["CHAMBER_HIL_EXPECTED_SERIAL"], lo, hi)
