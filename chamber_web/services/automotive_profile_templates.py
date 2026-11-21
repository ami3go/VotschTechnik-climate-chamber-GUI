"""Read-only OEM/ISO thermal method catalogue and deliberately unapproved profile drafts.

The bundled CSVs are the 2026-11-21 research extraction, not normative
specifications. This module never performs chamber or DUT I/O. Only simple
single-temperature exposure methods can be mapped to the current G03 schema;
all others remain inspectable as research records.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path

from chamber_web.domain.profile import (
    ParsedProfile, ProfileStep, UNAPPROVED_AUTOMOTIVE_TEMPLATE_PREFIX,
)
from chamber_web.services.profile_editor import EditorDraft, validate_editor_profile

_ASSETS = Path(__file__).resolve().parent.parent / "assets"
_METHODS_CSV = _ASSETS / "automotive_temperature_profile_methods_2026.csv"
_STANDARDS_CSV = _ASSETS / "automotive_temperature_profile_index_2026.csv"

# Exact, reviewed shape mappings only. Other 54 methods intentionally stay
# preview-only: no invented transition rate, soak, humidity or DUT power policy.
# (target, dwell seconds), where None means a controlled value must be supplied.
_SINGLE_SOAK = {
    "ISO-COLD-STORAGE": (Decimal("-40"), Decimal("86400")),
    "ISO-COLD-OP": (None, Decimal("86400")),
    "ISO-HOT-STORAGE": (Decimal("85"), Decimal("172800")),
    "ISO-HOT-OP": (None, Decimal("345600")),
    "IEC-COLD-METHOD": (None, None),
    "IEC-DRY-HEAT-METHOD": (None, None),
}


@dataclass(frozen=True)
class MethodTemplate:
    id: str
    standard: str
    method: str
    temperatures: str
    sequence: str
    cycles: str
    dut_state: str
    equipment: str
    evidence: str
    source_url: str
    missing: str
    comment: str

    @property
    def can_make_draft(self) -> bool:
        """Only an unapproved, non-runnable candidate, never a runnable recipe."""
        return self.id in _SINGLE_SOAK


@dataclass(frozen=True)
class StandardTemplate:
    id: str
    standard: str
    category: str
    test_family: str
    extraction_state: str
    method_ids: tuple[str, ...]
    source_url: str
    comment: str


def _read_csv(filename: Path) -> list[dict[str, str]]:
    with filename.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


@lru_cache(maxsize=1)
def method_templates() -> tuple[MethodTemplate, ...]:
    rows = _read_csv(_METHODS_CSV)
    records = []
    ids = set()
    for row in rows:
        identifier = row["id"]
        if identifier in ids or not identifier or row["execution_approved"].lower() != "false":
            raise ValueError("Invalid/approved research method catalogue")
        if not row["source_url"].startswith("https://"):
            raise ValueError("Temperature method has no HTTPS source")
        ids.add(identifier)
        records.append(MethodTemplate(
            identifier, row["standard"], row["method"], row["temperature_levels_c"],
            row["sequence"], row["cycles"], row["dut_state"], row["equipment"],
            row["evidence"], row["source_url"], row["missing"], row["comment"],
        ))
    if len(records) != 60 or not set(_SINGLE_SOAK) <= ids:
        raise ValueError("Incomplete automotive method catalogue")
    return tuple(records)


@lru_cache(maxsize=1)
def standard_templates() -> tuple[StandardTemplate, ...]:
    method_ids = {item.id for item in method_templates()}
    rows = _read_csv(_STANDARDS_CSV)
    records = []
    ids = set()
    for row in rows:
        identifier = row["record_id"]
        refs = tuple(k for k in row["profile_ids"].split(";") if k)
        if identifier in ids or not identifier or not set(refs) <= method_ids:
            raise ValueError("Invalid standard-to-method references")
        if not row["source_url"].startswith("https://"):
            raise ValueError("Automotive standard has no HTTPS source")
        ids.add(identifier)
        records.append(StandardTemplate(
            identifier, row["standard"], row["category"],
            row["temperature_test_family"], row["extraction_state"],
            refs, row["source_url"], row["comment"],
        ))
    if len(records) != 86:
        raise ValueError("Incomplete automotive standards catalogue")
    return tuple(records)


def find_method(method_id: str) -> MethodTemplate:
    if not isinstance(method_id, str):
        raise ValueError("Unknown automotive template")
    for method in method_templates():
        if method.id == method_id:
            return method
    raise ValueError("Unknown automotive template")


def _required_decimal(value: object, label: str, *, zero_ok: bool = False) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ValueError(label + " must be explicitly provided")
    try:
        number = Decimal(str(value).strip())
    except (ValueError, TypeError, InvalidOperation) as exc:
        raise ValueError("Invalid " + label) from exc
    if not number.is_finite() or (number < 0 if zero_ok else number <= 0):
        raise ValueError(label + " must be a finite " +
                         ("non-negative" if zero_ok else "positive") + " number")
    return number


def candidate_draft(method_id: str, *, target_c: object = None,
                    dwell_s: object = None, tolerance_c: object = None,
                    stabilize_s: object = None,
                    reach_timeout_s: object = None) -> EditorDraft:
    """Make an UNSAVED and NON-RUNNABLE candidate for explicit operator review.

    No default tolerance, ramp, reach deadline, or externally powered DUT state
    is invented. The G06 execution layer independently rejects this provenance.
    """
    method = find_method(method_id)
    if not method.can_make_draft:
        raise ValueError(
            "This method needs controlled OEM parameters and/or equipment the "
            "temperature-only profile runner cannot represent")
    fixed_target, fixed_dwell = _SINGLE_SOAK[method_id]
    if fixed_target is not None and target_c is not None:
        raise ValueError("Do not override the published fixed temperature")
    if fixed_dwell is not None and dwell_s is not None:
        raise ValueError("Do not override the published fixed dwell")
    target = fixed_target if fixed_target is not None else _required_decimal(
        target_c, "DUT-selected temperature")
    if fixed_target is None and not Decimal("-1000") <= target <= Decimal("1000"):
        raise ValueError("Target exceeds portable editor bounds")
    duration = fixed_dwell if fixed_dwell is not None else _required_decimal(
        dwell_s, "Selected severity duration")
    tolerance = _required_decimal(tolerance_c, "Temperature tolerance")
    stabilization = _required_decimal(stabilize_s, "Stabilization", zero_ok=True)
    reach = _required_decimal(reach_timeout_s, "Reach watchdog")
    if stabilization == 0:
        raise ValueError("Explicit positive DUT stabilization is required")
    if reach < stabilization:
        raise ValueError("Reach watchdog must cover DUT stabilization")
    note = (
        f"{method.id} · {method.standard} {method.method}. "
        f"External DUT mode: {method.dut_state}. "
        "Research candidate — electrical bias, fixtures, sensors, chamber limits, "
        "thermal equilibrium, recovery and source revision require approval."
    )
    profile = ParsedProfile(
        (ProfileStep(1, True, target, None, None, tolerance, stabilization,
                     duration, reach, note, "ON"),),
        migration_warning=(UNAPPROVED_AUTOMOTIVE_TEMPLATE_PREFIX + method.id),
        name=("RESEARCH " + method.id),
        description=(
            "UNAPPROVED automotive research candidate. DO NOT RUN. "
            f"Source {method.source_url}. Method: {method.sequence}. "
            f"Missing: {method.missing}. DUT mode: {method.dut_state}. "
            "Chamber-run ON controls chamber only; DUT power is external."
        ),
    )
    return EditorDraft(validate_editor_profile(profile), dirty=True)
