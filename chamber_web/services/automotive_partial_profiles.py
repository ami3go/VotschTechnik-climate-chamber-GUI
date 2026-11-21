"""Conservative reported-range matching for partial automotive thermal drafts.

Coverage counts the *specified temperature setpoints* only. It does NOT measure
normative test coverage, validated slew/transfer rate, dwell accuracy, DUT
bias/operation, humidity, safety, or the real chamber's certified performance.
Every resulting draft is explicitly marked unapproved; runner refuses it.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from chamber_web.domain.chamber import ChamberCapabilities
from chamber_web.domain.profile import (
    ParsedProfile, ProfileStep, MAX_STEPS,
    UNAPPROVED_AUTOMOTIVE_TEMPLATE_PREFIX,
)
from chamber_web.services.profile_editor import EditorDraft, validate_editor_profile
from chamber_web.services.automotive_profile_templates import find_method

MIN_COVERAGE_PERCENT = Decimal("85")
# Bounded list: never invent full standard qualification for battery shock,
# humidity, thermal-shock transfers or long semiconductor endurance.
PARTIAL_METHOD_IDS = frozenset({"ISO-STEP", "LV-K-02", "LV-K-03"})
_MAX_BUDGET_SECONDS = Decimal("1209600")  # G06: 14-day absolute watchdog


@dataclass(frozen=True)
class PartialCoverage:
    method_id: str
    label: str
    possible_points: int
    supported_points: int
    percentage: Decimal
    missing_targets_c: tuple[Decimal, ...]
    meets_threshold: bool
    comment: str


def _number(value: object, label: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{label} must be supplied explicitly")
    try:
        result = Decimal(str(value).strip())
    except (ValueError, TypeError, InvalidOperation) as exc:
        raise ValueError("Invalid " + label) from exc
    if not result.is_finite() or (positive and result <= 0):
        raise ValueError(f"{label} must be a finite " + (
            "positive number" if positive else "number"))
    return result


def _range_step(start: Decimal, end: Decimal, increment: int) -> tuple[Decimal, ...]:
    if (increment > 0 and end < start) or (increment < 0 and end > start):
        raise ValueError("Invalid temperature stepping order")
    if (end - start) % Decimal(increment) != 0:
        raise ValueError("Temperature ends must align to exact 5 °C steps")
    count = int((end - start) / Decimal(increment))
    if count > MAX_STEPS:
        raise ValueError("Too many temperature steps for current profile schema")
    return tuple(start + Decimal(increment) * index for index in range(count + 1))


def thermal_targets(method_id: str, *, tmin_c: object = None,
                    tmax_c: object = None) -> tuple[Decimal, ...]:
    """Known temperature points only; no guessed ramps or severity values."""
    find_method(method_id)  # only source-catalogue methods
    if method_id == "LV-K-02":
        return _range_step(Decimal("-55"), Decimal("85"), 5)
    if method_id == "LV-K-03":
        return (Decimal("-55"),)
    if method_id == "ISO-STEP":
        low = _number(tmin_c, "ISO Tmin")
        high = _number(tmax_c, "ISO Tmax")
        room = Decimal("20")
        if not Decimal("-1000") <= low < room < high <= Decimal("1000"):
            raise ValueError("ISO Tmin must be below 20°C and Tmax above 20°C")
        # Full up/down sweep, 5°C intervals, including repeated extrema.
        points = (
            _range_step(room, low, -5)
            + _range_step(low, high, 5)[1:]
            + _range_step(high, room, -5)[1:]
        )
        if len(points) > MAX_STEPS:
            raise ValueError("ISO stepped profile exceeds 200 allowed steps")
        return points
    raise ValueError("Method is not eligible for partial temperature-only matching")


def assess_partial_coverage(
    method_id: str, capabilities: ChamberCapabilities | None, *,
    tmin_c: object = None, tmax_c: object = None,
) -> PartialCoverage:
    """Evaluate 85% of *setpoint occurrences*, never normative test compliance."""
    targets = thermal_targets(method_id, tmin_c=tmin_c, tmax_c=tmax_c)
    if capabilities is None:
        raise ValueError("Chamber-reported capabilities unavailable")
    low = _number(capabilities.temperature_min_c, "Reported chamber minimum")
    high = _number(capabilities.temperature_max_c, "Reported chamber maximum")
    if low >= high:
        raise ValueError("Invalid chamber temperature envelope")
    supported = tuple(t for t in targets if low <= t <= high)
    missing = tuple(t for t in targets if not low <= t <= high)
    fraction = Decimal(len(supported)) * 100 / Decimal(len(targets))
    enough = fraction >= MIN_COVERAGE_PERCENT
    method = find_method(method_id)
    comment = (
        "PARTIALLY — temperature-setpoint coverage ONLY. Other requirements "
        "(source revision, ramp timing, DUT electrical state, measurements, "
        "recovery, and facility qualification) are NOT checked. "
        + ("OEM values are third-party examples, not controlled norms. "
           if method.evidence != "verified_public" else "")
        + "Chamber-reported limits are NOT verified physical specifications. "
        + (f"Required setpoints omitted: {', '.join(str(t) for t in sorted(set(missing)))} °C."
           if missing else "All extracted setpoints are within the reported envelope.")
    )
    return PartialCoverage(
        method_id=method_id, label="(partially)",
        possible_points=len(targets), supported_points=len(supported),
        percentage=fraction.quantize(Decimal("0.1")), missing_targets_c=missing,
        meets_threshold=enough, comment=comment,
    )


def partial_candidate_draft(
    method_id: str, capabilities: ChamberCapabilities | None, *,
    tmin_c: object = None, tmax_c: object = None,
    dwell_s: object = None, tolerance_c: object = None,
    stabilize_s: object = None, reach_timeout_s: object = None,
) -> EditorDraft:
    """Build *unapproved* draft only when >=85% setpoints fit reported limits.

    No implicit substitute setpoints. Unsupported points are omitted and
    recorded in the profile metadata; it cannot be run in any mode.
    """
    coverage = assess_partial_coverage(
        method_id, capabilities, tmin_c=tmin_c, tmax_c=tmax_c)
    if not coverage.meets_threshold:
        raise ValueError(
            f"Only {coverage.percentage}% of specified temperature setpoints are "
            "within the reported chamber limits; >=85% is required")
    duration = _number(dwell_s, "Exposure duration", positive=True)
    tolerance = _number(tolerance_c, "Temperature tolerance", positive=True)
    stabilization = _number(stabilize_s, "DUT stabilization", positive=True)
    reach = _number(reach_timeout_s, "Reach watchdog", positive=True)
    if reach < stabilization:
        raise ValueError("Reach watchdog must cover DUT stabilization")
    if method_id == "LV-K-03" and duration != Decimal("172800"):
        raise ValueError(
            "K-03 source example uses 48 h; enter 172800 seconds explicitly")
    if method_id == "LV-K-02" and not Decimal("300") <= duration <= Decimal("600"):
        raise ValueError(
            "K-02 source example lists 5–10 min steps; choose 300..600 seconds")
    # Conservative preflight. Actual G06 step budgets and live chamber limits
    # are independently checked, and every draft still remains non-executable.
    targets = thermal_targets(method_id, tmin_c=tmin_c, tmax_c=tmax_c)
    low = Decimal(str(capabilities.temperature_min_c))
    high = Decimal(str(capabilities.temperature_max_c))
    supported = [t for t in targets if low <= t <= high]
    if Decimal(len(supported)) * (duration + stabilization + reach + Decimal("15")) + 30 > _MAX_BUDGET_SECONDS:
        raise ValueError("Partial candidate exceeds 14-day G06 watchdog ceiling")
    method = find_method(method_id)
    note_prefix = UNAPPROVED_AUTOMOTIVE_TEMPLATE_PREFIX + method_id
    steps = tuple(
        ProfileStep(
            index, True, target, None, None, tolerance,
            stabilization, duration, reach,
            f"{note_prefix} PARTIALLY (temperature setpoints only). "
            f"Step {index}/{len(supported)}; DUT mode {method.dut_state}.",
            "ON",
        )
        for index, target in enumerate(supported, 1)
    )
    profile = ParsedProfile(
        steps,
        migration_warning=(note_prefix + " PARTIALLY; " + coverage.comment),
        name=f"{method_id} (partially)",
        description=(
            f"UNAPPROVED / PARTIALLY: {coverage.supported_points}/"
            f"{coverage.possible_points} setpoints ({coverage.percentage}%). "
            f"Source {method.source_url}. "
            f"Missing targets: {', '.join(str(t) for t in coverage.missing_targets_c) or 'none'}. "
            "NOT compliant: no verified DUT electrical modes, rate, recovery, "
            "manufacturer procedure or physical facility qualification."
        ),
    )
    return EditorDraft(validate_editor_profile(profile), dirty=True)
