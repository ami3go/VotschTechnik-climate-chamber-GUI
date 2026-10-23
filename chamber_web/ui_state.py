"""Pure, vendor-neutral formatting of server-owned immutable UI projections."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timezone
import math

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
    mode = ("IDENTITY UNVERIFIED" if identity is None else
            "SIMULATION" if identity.is_simulation else "PHYSICAL HIL")
    identity_text = (
        f"{identity.manufacturer} {identity.model} · {identity.backend_id} · {identity.chamber_id}"
        if identity else f"Identity unverified · {view.chamber_id}"
    )
    can_read_running = bool(view.capabilities and view.capabilities.supports_running_readback)
    operation = (view.operation_state.value if good and can_read_running
                 else OperationState.UNKNOWN.value)
    if good and view.operation_state is OperationState.FAULT:
        operation = "FAULT"
    # A fault is never interpreted as healthy even with a nominal GOOD reading.
    verified = good and operation not in (OperationState.FAULT.value, OperationState.UNKNOWN.value)
    measured = (f"{view.measured_temperature_c:.1f} °C"
                if verified and view.measured_temperature_c is not None else "— (unverified)")
    setpoint = (f"{view.setpoint_temperature_c:.1f} °C"
                if (verified and view.capabilities and view.capabilities.supports_setpoint_readback
                    and view.setpoint_temperature_c is not None) else "— (unverified)")
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
class ChamberIdentityDisplay:
    """Dashboard card: explicit active device, endpoint and identity provenance."""
    chamber: str
    ip_address: str
    serial_number: str
    identity_status: str


def project_chamber_identity(
    view: DashboardView, *, configured_address: str | None = None,
    expected_serial: str | None = None,
) -> ChamberIdentityDisplay:
    """Display server-owned configuration without inventing verified hardware.

    The authoritative physical IP and serial pin come from launch-time HIL
    configuration, never untrusted UI fields or a browser discovery result.
    Readback supplies model and verified identity only when current/GOOD and
    matching the configured chamber and serial. Failure or stale telemetry
    retains clearly labeled *configured* details, not a connected claim.
    """
    if configured_address is None:
        return ChamberIdentityDisplay(
            chamber=f"Simulator · {view.chamber_id}",
            ip_address="Not applicable (simulation)",
            serial_number="Not applicable (simulation)",
            identity_status="Simulation — no physical chamber connected",
        )

    identity = view.identity
    matching = (
        identity is not None
        and not identity.is_simulation
        and identity.backend_id == "votsch"
        and identity.chamber_id == view.chamber_id
        and bool(expected_serial)
        and identity.serial_number == expected_serial
    )
    verified = (
        matching
        and view.quality is ReadingQuality.GOOD
        and view.sampled_at_utc is not None
        and view.sampled_at_utc.tzinfo is not None
    )
    if matching:
        chamber = f"{identity.manufacturer} {identity.model} · {view.chamber_id}"
    else:
        chamber = f"Vötsch chamber · {view.chamber_id}"
    status = (
        "Live identity verified" if verified
        else "Identity last seen — live status unverified"
        if matching else "Configured identity — not yet verified"
    )
    return ChamberIdentityDisplay(
        chamber=chamber,
        ip_address=configured_address,
        serial_number=expected_serial or "Not configured",
        identity_status=status,
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
    if (caps is None or not math.isfinite(caps.temperature_min_c)
            or not math.isfinite(caps.temperature_max_c)
            or caps.temperature_min_c >= caps.temperature_max_c):
        return CapabilityDisplay("Unverified", *("Unavailable",) * 5,
                                 "Capabilities not available; all controls disabled")
    def supported(enabled):
        return "Supported (read-only)" if enabled else "Unsupported"
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
