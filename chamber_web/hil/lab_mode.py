"""Isolated-lab unattended mode for ONE physical Vötsch chamber.

For a closed lab network (server, laptop and chamber only) a single
launch-time acknowledgement enables physical profile execution:
``CHAMBER_LAB_MODE=ISOLATED-LAB-UNATTENDED``.

What still applies in lab mode:

* the complete ``CHAMBER_HIL_*`` authorization (serial pin re-verified on
  every read, private chamber IPv4, software envelope);
* G08 sign-in and roles (only Administrator/Operator may run profiles);
* G04 single-owner leases, generation fencing and verified STOP;
* G06 step/run deadlines, telemetry freshness/identity checks, setpoint
  convergence supervision and a STOP on any uncertainty;
* G07 run journal (a broken journal still refuses starts).

The chamber's own limits and emergency stop remain the primary safety layer.
An administrator can enable it in Settings (saved server-side, applied at the
next server start) or set the environment variable directly; a browser request
cannot toggle the mode of a running server.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Mapping

from chamber_web.domain.chamber import ChamberSafetyError

ENV_LAB_MODE = "CHAMBER_LAB_MODE"
ENV_MEASURED_MARGIN = "CHAMBER_LAB_MEASURED_MARGIN_C"
ENV_GRADIENTS = "CHAMBER_LAB_GRADIENTS"
LAB_ACKNOWLEDGEMENT = "ISOLATED-LAB-UNATTENDED"
# Stable 64-hex binding recorded for the admitted lab run.
LAB_RUN_BINDING = hashlib.sha256(LAB_ACKNOWLEDGEMENT.encode("ascii")).hexdigest()
DEFAULT_MEASURED_MARGIN_C = 5.0
MAX_MEASURED_MARGIN_C = 10.0


@dataclass(frozen=True)
class LabMode:
    # Measured air temperature may overshoot the software envelope by this
    # much (e.g. -41.2 °C while holding -40 °C) without aborting a run.
    measured_margin_c: float = DEFAULT_MEASURED_MARGIN_C
    # Profile ramp_up/ramp_down columns write the chamber's gradient settings.
    gradients: bool = True

    def __post_init__(self) -> None:
        margin = self.measured_margin_c
        if (isinstance(margin, bool) or not isinstance(margin, (int, float)) or
                not math.isfinite(margin) or not 0 <= margin <= MAX_MEASURED_MARGIN_C):
            raise ChamberSafetyError(
                f"Lab measured margin must be 0..{MAX_MEASURED_MARGIN_C} °C")
        if type(self.gradients) is not bool:
            raise ChamberSafetyError("Lab gradient switch must be boolean")


def lab_mode_from_env(env: Mapping[str, str], *, hil_present: bool) -> LabMode | None:
    """None unless explicitly enabled; any partial/invalid value fails closed."""
    raw = env.get(ENV_LAB_MODE, "").strip()
    extras = [key for key in (ENV_MEASURED_MARGIN, ENV_GRADIENTS) if env.get(key, "").strip()]
    if not raw:
        if extras:
            raise ChamberSafetyError(
                ", ".join(extras) + f" requires {ENV_LAB_MODE}={LAB_ACKNOWLEDGEMENT}")
        return None
    if raw != LAB_ACKNOWLEDGEMENT:
        raise ChamberSafetyError(f"{ENV_LAB_MODE} must be exactly {LAB_ACKNOWLEDGEMENT!r}")
    if not hil_present:
        raise ChamberSafetyError(
            f"{ENV_LAB_MODE} requires a complete CHAMBER_HIL_* chamber authorization")
    margin_raw = env.get(ENV_MEASURED_MARGIN, "").strip()
    try:
        margin = float(margin_raw) if margin_raw else DEFAULT_MEASURED_MARGIN_C
    except ValueError as exc:
        raise ChamberSafetyError("Lab measured margin must be numeric") from exc
    gradients_raw = env.get(ENV_GRADIENTS, "").strip().lower() or "on"
    if gradients_raw not in ("on", "off"):
        raise ChamberSafetyError(f"{ENV_GRADIENTS} must be on or off")
    return LabMode(measured_margin_c=margin, gradients=gradients_raw == "on")
