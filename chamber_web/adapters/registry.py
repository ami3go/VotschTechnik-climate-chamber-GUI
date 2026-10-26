"""Explicit backend registry/factory; never import arbitrary modules from UI input."""
from __future__ import annotations

import math
import os

from chamber_web.domain.chamber import ChamberSafetyError
from chamber_web.domain.config import ChamberConfig


def simulated_ramp_range() -> tuple[float, float] | None:
    """Opt-in simulated gradient range, e.g. ``CHAMBER_SIM_RAMP_C_PER_MIN=0.1,10``."""
    raw = os.environ.get("CHAMBER_SIM_RAMP_C_PER_MIN", "").strip()
    if not raw or raw.lower() in {"off", "none", "0"}:
        return None
    parts = [part.strip() for part in raw.split(",")]
    try:
        low, high = (float(part) for part in parts)
    except (TypeError, ValueError) as exc:
        raise ChamberSafetyError("Invalid simulated gradient range") from exc
    if (len(parts) != 2 or not math.isfinite(low) or not math.isfinite(high)
            or not 0 < low <= high <= 60):
        raise ChamberSafetyError("Invalid simulated gradient range")
    return low, high


def make_backend(config: ChamberConfig, *, allow_test_backend: bool = False):
    # Only this adapter registry checks model-specific connection requirements.
    if config.backend_id == "votsch" and not config.address:
        raise ChamberSafetyError("Vötsch endpoint required")
    if config.backend_id != "votsch" and config.address:
        raise ChamberSafetyError("Unexpected endpoint for simulation backend")
    # Localized imports keep services/domain independent of manufacturer modules.
    if config.backend_id == "fake":
        from .fake import FakeBackend
        return FakeBackend(config.chamber_id,
                           ramp_range_c_per_min=simulated_ramp_range())
    if config.backend_id == "votsch":
        from .votsch import VotschBackend
        return VotschBackend(config.chamber_id, config.address or "")
    if config.backend_id == "alternate_stub" and allow_test_backend:
        from .alternate_stub import AlternateStubBackend
        return AlternateStubBackend(config.chamber_id)
    raise ChamberSafetyError("Test-only backend cannot be configured for production")
