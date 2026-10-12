"""Versioned, vendor-neutral profile CSV/ZIP core (G03-A, no hardware I/O)."""
from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from zipfile import ZIP_DEFLATED, ZipFile

CANONICAL = (
    "step", "enabled", "target_temperature_c", "ramp_up_c_per_min",
    "ramp_down_c_per_min", "tolerance_c", "stabilize_s", "dwell_s",
    "reach_timeout_s", "notes",
)
LEGACY = ("target", "ramp", "tolerance", "dwell", "description", "enabled")
MAX_BYTES = 1_000_000
MAX_STEPS = 200


def _number(value: str, field: str, *, positive=False, minimum=None) -> Decimal:
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"Invalid {field}") from exc
    if not result.is_finite() or (positive and result <= 0) or (
        minimum is not None and result < minimum
    ):
        raise ValueError(f"Invalid {field}: must be finite and within bounds")
    return result


def _enabled(value: str) -> bool:
    if value.strip().lower() in ("true", "yes", "1"):
        return True
    if value.strip().lower() in ("false", "no", "0"):
        return False
    raise ValueError("Invalid enabled flag")


@dataclass(frozen=True)
class ProfileStep:
    step: int
    enabled: bool
    target_temperature_c: Decimal
    ramp_up_c_per_min: Decimal | None
    ramp_down_c_per_min: Decimal | None
    tolerance_c: Decimal
    stabilize_s: Decimal
    dwell_s: Decimal
    reach_timeout_s: Decimal
    notes: str


@dataclass(frozen=True)
class ParsedProfile:
    steps: tuple[ProfileStep, ...]
    legacy_original: bytes | None = None
    migration_warning: str | None = None
    name: str = "Imported Profile"


def _rows(data: bytes):
    if not isinstance(data, bytes) or len(data) > MAX_BYTES:
        raise ValueError("Profile exceeds maximum permitted size")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Profile must use UTF-8") from exc
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if reader.fieldnames not in (list(CANONICAL), list(LEGACY)):
        raise ValueError("Unknown profile CSV schema or duplicate/mismatched headers")
    fields = tuple(reader.fieldnames)
    rows = []
    for row in reader:
        if len(rows) >= MAX_STEPS:
            raise ValueError("Too many profile steps")
        if None in row or any(cell is None for cell in row.values()):
            raise ValueError("Malformed CSV row")
        rows.append(row)
    if not rows:
        raise ValueError("Profile has no steps")
    return fields, rows


def parse_profile_csv(
    data: bytes, *, legacy_reach_timeout_s: Decimal | None = None
) -> ParsedProfile:
    """Detect canonical v1 or explicit demo legacy schema, never infer gradients."""
    fields, rows = _rows(data)
    if fields == LEGACY and legacy_reach_timeout_s is None:
        raise ValueError("Legacy CSV requires an operator-provided reach timeout")
    legacy_timeout = None
    if fields == LEGACY:
        legacy_timeout = _number(
            str(legacy_reach_timeout_s), "legacy_reach_timeout_s", positive=True
        )
    steps = []
    for index, row in enumerate(rows, 1):
        if fields == LEGACY:
            _number(row["ramp"], "legacy demo ramp", positive=True)
            source = {
                "step": str(index),
                "enabled": row["enabled"],
                "target_temperature_c": row["target"],
                "ramp_up_c_per_min": "",
                "ramp_down_c_per_min": "",
                "tolerance_c": row["tolerance"],
                "stabilize_s": "0",
                "dwell_s": row["dwell"],
                "reach_timeout_s": str(legacy_timeout),
                "notes": row["description"],
            }
        else:
            source = row
        try:
            ordinal = int(source["step"])
        except (ValueError, TypeError) as exc:
            raise ValueError("Invalid step index") from exc
        if ordinal != index:
            raise ValueError("Step indices must be 1..N in order")
        note = source["notes"]
        if len(note) > 4096:
            raise ValueError("Step notes too long")
        def ramp(field):
            return _number(source[field], field, positive=True) if source[field] else None
        step = ProfileStep(
            ordinal, _enabled(source["enabled"]),
            _number(source["target_temperature_c"], "target_temperature_c"),
            ramp("ramp_up_c_per_min"), ramp("ramp_down_c_per_min"),
            _number(source["tolerance_c"], "tolerance_c", positive=True),
            _number(source["stabilize_s"], "stabilize_s", minimum=0),
            _number(source["dwell_s"], "dwell_s", minimum=0),
            _number(source["reach_timeout_s"], "reach_timeout_s", positive=True),
            note,
        )
        steps.append(step)
    if not any(step.enabled for step in steps):
        raise ValueError("No enabled steps")
    if fields == LEGACY:
        return ParsedProfile(
            tuple(steps), data,
            "Legacy ramp is simulation-only; both physical gradients remain null. "
            "Use full ZIP to retain original legacy values."
        )
    return ParsedProfile(tuple(steps))


def export_profile_csv(profile: ParsedProfile, *, spreadsheet_safe=False) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CANONICAL)
    if not 1 <= len(profile.steps) <= MAX_STEPS:
        raise ValueError("Invalid profile length")
    for expected, step in enumerate(profile.steps, 1):
        if step.step != expected:
            raise ValueError("Invalid step sequence")
        notes = step.notes
        if spreadsheet_safe and notes.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
            notes = "'" + notes
        writer.writerow((
            step.step, str(step.enabled),
            str(step.target_temperature_c),
            "" if step.ramp_up_c_per_min is None else str(step.ramp_up_c_per_min),
            "" if step.ramp_down_c_per_min is None else str(step.ramp_down_c_per_min),
            str(step.tolerance_c), str(step.stabilize_s), str(step.dwell_s),
            str(step.reach_timeout_s), notes,
        ))
    return buffer.getvalue().encode("utf-8")


def _checksum(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def export_profile_zip(profile: ParsedProfile) -> bytes:
    """Lossless canonical profile with retained legacy original, if present."""
    csv_data = export_profile_csv(profile)
    metadata = {
        "schema_version": 1,
        "name": profile.name,
        "profile_csv_sha256": _checksum(csv_data),
        "legacy_csv_sha256": (
            _checksum(profile.legacy_original)
            if profile.legacy_original is not None else None
        ),
        "migration_warning": profile.migration_warning,
    }
    out = io.BytesIO()
    with ZipFile(out, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("profile.csv", csv_data)
        archive.writestr("profile.json", json.dumps(metadata, ensure_ascii=False))
        if profile.legacy_original is not None:
            archive.writestr("legacy_import.csv", profile.legacy_original)
    return out.getvalue()


def import_profile_zip(content: bytes) -> ParsedProfile:
    if not isinstance(content, bytes) or len(content) > MAX_BYTES * 2:
        raise ValueError("ZIP exceeds input limit")
    with ZipFile(io.BytesIO(content)) as archive:
        info = archive.infolist()
        names = [item.filename for item in info]
        if len(names) != len(set(names)) or not (2 <= len(names) <= 3):
            raise ValueError("ZIP contains duplicate or unexpected entries")
        if set(names) not in (
            {"profile.csv", "profile.json"},
            {"profile.csv", "profile.json", "legacy_import.csv"},
        ):
            raise ValueError("ZIP entries not allowlisted")
        if any(item.file_size > MAX_BYTES or item.flag_bits & 1 for item in info):
            raise ValueError("ZIP entry size/encryption invalid")
        if sum(item.file_size for item in info) > MAX_BYTES * 2:
            raise ValueError("ZIP expansion limit exceeded")
        manifest = json.loads(archive.read("profile.json"))
        if manifest.get("schema_version") != 1:
            raise ValueError("Unsupported profile version")
        data = archive.read("profile.csv")
        if _checksum(data) != manifest.get("profile_csv_sha256"):
            raise ValueError("CSV checksum mismatch")
        parsed = parse_profile_csv(data)
        legacy = archive.read("legacy_import.csv") if "legacy_import.csv" in names else None
        if (legacy is None) != (manifest.get("legacy_csv_sha256") is None):
            raise ValueError("Legacy metadata inconsistent")
        if legacy is not None and _checksum(legacy) != manifest["legacy_csv_sha256"]:
            raise ValueError("Legacy checksum mismatch")
        if legacy is not None:
            parse_profile_csv(legacy, legacy_reach_timeout_s=Decimal("1"))
        name = manifest.get("name")
        if not isinstance(name, str) or not 1 <= len(name) <= 160:
            raise ValueError("Invalid profile name")
        warning = manifest.get("migration_warning")
        if warning is not None and not isinstance(warning, str):
            raise ValueError("Invalid migration warning")
        return ParsedProfile(parsed.steps, legacy, warning, name)
