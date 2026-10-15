"""H02 signed physical-profile permit validation (NOT a hardware enable switch).

This module does not dispatch, start or stop hardware and is not wired into G06.
In particular H01 CHAMBER_HIL_* acknowledgement is NOT an H02 permit. Keep G06
simulation-only until site-specific safety/independent-supervision review.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, fields
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import re
from typing import Any, Mapping, Sequence

from chamber_web.domain.chamber import (
    ChamberIdentity, ChamberSafetyError, validate_chamber_id,
)


class AdmissionDenied(ChamberSafetyError):
    """Fail closed before any profile hardware command is dispatched."""


@dataclass(frozen=True)
class H02WatchdogLimits:
    schema_version: int
    controller_command_timeout_s: float
    readback_deadline_s: float
    max_telemetry_gap_s: float
    profile_step_deadline_s: float
    whole_profile_deadline_s: float
    recorder_heartbeat_s: float
    process_heartbeat_s: float
    supervisor_heartbeat_s: float
    cleanup_timeout_s: float
    stop_verification_timeout_s: float

    def __post_init__(self):
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise AdmissionDenied("Unrecognized watchdog schema")
        for field in fields(self):
            if field.name == "schema_version":
                continue
            value = getattr(self, field.name)
            if type(value) not in (int, float) or not math.isfinite(value) or (
                value <= 0 or value > 1_209_600
            ):
                raise AdmissionDenied("Invalid bounded watchdog limit: " + field.name)
        if self.max_telemetry_gap_s > 5 or self.readback_deadline_s > 5:
            raise AdmissionDenied("P00 readback/telemetry freshness limit exceeded")
        if self.profile_step_deadline_s > self.whole_profile_deadline_s:
            raise AdmissionDenied("Step deadline exceeds whole-run deadline")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "H02WatchdogLimits":
        names = {field.name for field in fields(cls)}
        if not isinstance(data, dict) or set(data) != names:
            raise AdmissionDenied("Watchdog configuration must match v1 schema")
        return cls(**data)


@dataclass(frozen=True)
class H02LiveChecks:
    """Trusted, fresh evidence from G04/G07/G08 and physically present staff.

    This is NOT a browser DTO. The integration root must derive these values
    through its authenticated services and site operator/witness workflow.
    """

    g04_exclusive_owner: bool
    g04_verified_stopped: bool
    no_stop_latch: bool
    g07_reconciled_writable: bool
    g08_authenticated_authorized: bool
    physical_stop_procedure_confirmed: bool
    operator_present: bool
    witness_present: bool
    supervisor_alive: bool

    def require_all(self) -> None:
        if any(type(getattr(self, field.name)) is not bool or
               not getattr(self, field.name) for field in fields(self)):
            raise AdmissionDenied("Physical admission requires all independent live checks")


def _sha(value: Any, name: str, size: int = 64) -> str:
    if not isinstance(value, str) or re.fullmatch('[0-9a-f]{' + str(size) + '}', value) is None:
        raise AdmissionDenied('Invalid SHA-256/commit identifier: ' + name)
    return value


def _nonempty(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise AdmissionDenied("Missing/invalid permit field: " + name)
    return value


def _utc(value: Any) -> datetime:
    if not isinstance(value, str):
        raise AdmissionDenied("UTC permit time required")
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AdmissionDenied("Invalid permit timestamp") from exc
    if timestamp.tzinfo is None or timestamp.utcoffset().total_seconds() != 0:
        raise AdmissionDenied("Permit timestamps must be explicit UTC")
    return timestamp


def verify_signed_permit(
    signed: Mapping[str, Any], *,
    trusted_site_public_key: bytes,
    now_utc: datetime | None = None,
) -> Mapping[str, Any]:
    """Verify an exact-scope Ed25519 detached signature over canonical JSON.

    The site public key MUST be provisioned through a trusted administrator
    path outside the browser, permit and repository. If cryptography or trusted
    key is absent, admission fails. Signature alone never enables G06.
    """
    if not isinstance(signed, dict) or set(signed) != {"permit", "signature_base64"}:
        raise AdmissionDenied("Expected signed H02 permit envelope")
    data = signed["permit"]
    if not isinstance(data, dict) or set(data) != {
        "schema_version", "scope", "site_method", "approval_reference",
        "chamber_id", "serial_number", "profile_id", "profile_revision_sha256",
        "gui_commit", "driver_commit", "operator", "witness",
        "specimen_restrictions", "temperature_min_c", "temperature_max_c",
        "valid_from_utc", "valid_until_utc", "watchdog",
    }:
        raise AdmissionDenied("H02 permit schema invalid or incomplete")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1 or (
        data["scope"] != "H02_SUPERVISED_PHYSICAL_PROFILE"
    ):
        raise AdmissionDenied("Wrong site permit scope/schema")
    if not isinstance(trusted_site_public_key, bytes) or len(trusted_site_public_key) != 32:
        raise AdmissionDenied("Trusted site Ed25519 public key not installed")
    try:
        signature = base64.b64decode(signed["signature_base64"], validate=True)
        if len(signature) != 64:
            raise ValueError("Ed25519 signature must be 64 bytes")
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=False, allow_nan=False).encode("utf-8")
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        Ed25519PublicKey.from_public_bytes(trusted_site_public_key).verify(
            signature, canonical,
        )
    except (ImportError, ValueError, TypeError, UnicodeError, OverflowError) as exc:
        raise AdmissionDenied("H02 permit signature unavailable/invalid") from exc
    except Exception as exc:
        raise AdmissionDenied("H02 permit signature rejected") from exc
    for name in ("site_method", "approval_reference", "serial_number",
                 "profile_id", "operator", "witness", "specimen_restrictions"):
        _nonempty(data[name], name)
    validate_chamber_id(data["chamber_id"])
    for name in ("profile_revision_sha256", "gui_commit", "driver_commit"):
        _sha(data[name], name, 40 if name.endswith("_commit") else 64)
    H02WatchdogLimits.from_dict(data["watchdog"])
    lower, upper = data["temperature_min_c"], data["temperature_max_c"]
    if (type(lower) not in (int, float) or type(upper) not in (int, float) or
        not math.isfinite(lower) or not math.isfinite(upper) or lower >= upper):
        raise AdmissionDenied("Invalid approved temperature envelope")
    start = _utc(data["valid_from_utc"])
    end = _utc(data["valid_until_utc"])
    current = now_utc or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset().total_seconds() != 0:
        raise AdmissionDenied("Current time must be UTC")
    if end <= start or not start <= current <= end or end - start > (
        timedelta(days=14)
    ):
        raise AdmissionDenied("H02 site permit expired, premature or overlong")
    return data


def preflight_physical_profile(
    signed: Mapping[str, Any], *,
    trusted_site_public_key: bytes,
    live: H02LiveChecks,
    identity: ChamberIdentity,
    profile_id: str,
    profile_sha256: str,
    gui_commit: str,
    driver_commit: str,
    operator: str,
    witness: str,
    targets_c: Sequence[float],
    has_outputs_or_gradient_mutations: bool,
    now_utc: datetime | None = None,
) -> str:
    """Read-only H02 preflight returns permit SHA; no G04 writes are possible.

    The caller MUST additionally verify device identity and convergence using
    fresh G04 reads, refuse UNKNOWN, and enforce runtime watchdog supervision.
    This deliberately cannot enable physical execution on its own.
    """
    data = verify_signed_permit(signed, trusted_site_public_key=trusted_site_public_key,
                                now_utc=now_utc)
    live.require_all()
    if identity.is_simulation or not identity.serial_number or (
        identity.chamber_id != data["chamber_id"] or
        identity.serial_number != data["serial_number"] or
        identity.backend_id != "votsch"
    ):
        raise AdmissionDenied("Physical chamber identity mismatch")
    if (profile_id != data["profile_id"] or
        _sha(profile_sha256, "profile") != data["profile_revision_sha256"] or
        _sha(gui_commit, "GUI", 40) != data["gui_commit"] or
        _sha(driver_commit, "driver", 40) != data["driver_commit"] or
        operator != data["operator"] or witness != data["witness"]):
        raise AdmissionDenied("Physical run identity/version/operator mismatch")
    if has_outputs_or_gradient_mutations:
        raise AdmissionDenied("Unapproved profile v2 outputs or gradient mutations")
    if not targets_c or len(targets_c) > 10000 or any(
        type(target) not in (int, float) or not math.isfinite(target) or
        not data["temperature_min_c"] <= target <= data["temperature_max_c"]
        for target in targets_c
    ):
        raise AdmissionDenied("Profile target outside approved envelope")
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
