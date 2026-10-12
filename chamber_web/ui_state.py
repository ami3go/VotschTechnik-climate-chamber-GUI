"""Pure, vendor-neutral formatting of server-owned immutable UI projections."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from chamber_web.domain.chamber import OperationState, ReadingQuality
from chamber_web.services.dashboard import DashboardView


@dataclass(frozen=True)
class TelemetryDisplay:
    chamber_id: str
    identity: str
    mode: str
    measured: str
    setpoint: str
    operation: str
    quality: str
    sampled_utc: str
    message: str
    connected: bool


def project_telemetry(view: DashboardView) -> TelemetryDisplay:
    """Never render stale/fault/invalid telemetry as verified control feedback."""
    good = view.quality is ReadingQuality.GOOD and view.sampled_at_utc is not None
    stamp = view.sampled_at_utc
    if stamp is None or stamp.tzinfo is None:
        good = False
    identity = view.identity
    mode = "SIMULATION" if identity is None or identity.is_simulation else "READ ONLY"
    identity_text = (
        f"{identity.manufacturer} {identity.model} · {identity.backend_id} · {identity.chamber_id}"
        if identity else f"Identity unverified · {view.chamber_id}"
    )
    operation = view.operation_state.value if good else OperationState.UNKNOWN.value
    if view.operation_state is OperationState.FAULT:
        operation = "FAULT"
    # A fault is never interpreted as healthy even with a nominal GOOD reading.
    verified = good and view.operation_state not in (OperationState.FAULT, OperationState.UNKNOWN)
    measured = (f"{view.measured_temperature_c:.1f} °C"
                if verified and view.measured_temperature_c is not None else "— (unverified)")
    setpoint = (f"{view.setpoint_temperature_c:.1f} °C"
                if verified and view.setpoint_temperature_c is not None else "— (unverified)")
    sampled = stamp.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC") if good else "Unavailable"
    message = (view.error or (
        "Equipment fault — operation is unsafe to infer" if operation == "FAULT"
        else "Equipment state unknown — commands locked" if operation == "UNKNOWN"
        else "Read-only server telemetry"))
    return TelemetryDisplay(
        view.chamber_id, identity_text, mode, measured, setpoint,
        operation, view.quality.value, sampled, message, verified
    )


@dataclass(frozen=True)
class CapabilityDisplay:
    temperature_range: str
    start_stop: str
    setpoint_readback: str
    running_readback: str
    ramp_up: str
    ramp_down: str
    controls_locked_reason: str


def project_capabilities(view: DashboardView) -> CapabilityDisplay:
    caps = view.capabilities
    if caps is None:
        return CapabilityDisplay("Unverified", *("Unavailable",) * 5,
                                 "Capabilities not available; all controls disabled")
    supported = lambda enabled: "Supported (read-only)" if enabled else "Unsupported"
    # No setting can unlock physical commands in the G02-B UI.
    reason = ("Physical controls disabled: G08-min authorization, site safety "
              "approval and HIL verification required")
    if view.quality is not ReadingQuality.GOOD:
        reason = "Telemetry unavailable/stale; controls disabled"
    elif view.operation_state in (OperationState.UNKNOWN, OperationState.FAULT):
        reason = "UNKNOWN/FAULT equipment state; controls disabled"
    elif not caps.supports_start_stop:
        reason = "Start/STOP unsupported by this chamber; controls disabled"
    return CapabilityDisplay(
        f"{caps.temperature_min_c:g} to {caps.temperature_max_c:g} °C",
        supported(caps.supports_start_stop),
        supported(caps.supports_setpoint_readback),
        supported(caps.supports_running_readback),
        supported(caps.supports_ramp_up),
        supported(caps.supports_ramp_down),
        reason,
    )


def safe_view(service) -> DashboardView:
    """A temporarily restarting provider cannot crash a NiceGUI refresh callback."""
    try:
        return service.view()
    except Exception:
        return DashboardView(chamber_id=service.chamber_id,
                             error="Server telemetry service unavailable (retrying)")
