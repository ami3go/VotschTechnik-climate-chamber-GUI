"""G03-C server-owned profile editing service. No NiceGUI or device I/O."""
from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from threading import RLock
from zipfile import BadZipFile

from chamber_web.domain.chamber import ChamberCapabilities, validate_chamber_id
from chamber_web.domain.profile import (
    MAX_BYTES, MAX_STEPS, ParsedProfile, ProfileStep, export_profile_zip,
    import_profile_zip, parse_profile_csv,
)
from chamber_web.persistence.profiles import ProfileHeader, ProfileStore

MAX_DURATION_S = Decimal("2592000")  # UI/import guard: 30 days per stage.
MAX_ABS_TEMPERATURE_C = Decimal("1000")  # Not a certified chamber envelope.
MAX_POSITIVE_C = Decimal("1000")
MAX_DUPLICATE_SCAN = 5000
_IMPORT_LOCK = RLock()
STEP_FIELDS = frozenset({
    "enabled", "target_temperature_c", "ramp_up_c_per_min",
    "ramp_down_c_per_min", "tolerance_c", "stabilize_s",
    "dwell_s", "reach_timeout_s", "notes",
})
DECIMAL_FIELDS = STEP_FIELDS - {"enabled", "notes"}
OPTIONAL_DECIMAL_FIELDS = {"ramp_up_c_per_min", "ramp_down_c_per_min"}


class DuplicateProfileError(ValueError):
    """An identical profile was already imported for this chamber."""

    def __init__(self, header: ProfileHeader):
        self.header = header
        super().__init__("An identical profile already exists: " + header.name)


@dataclass(frozen=True)
class EditorDraft:
    """Page-local, uncommitted copy; the SQLite store is authoritative."""

    profile: ParsedProfile
    profile_id: str | None = None
    expected_revision: int | None = None
    viewed_revision: int | None = None
    read_only: bool = False
    dirty: bool = False


def _decimal(value: object, field: str, *, minimum: Decimal | None = None,
             maximum: Decimal | None = None, strictly_positive: bool = False) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ValueError(field + " must be numeric")
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("Invalid " + field) from exc
    if not number.is_finite() or (minimum is not None and number < minimum) or (
        maximum is not None and number > maximum
    ) or (strictly_positive and number <= 0):
        raise ValueError(field + " outside finite permitted bounds")
    return number


def _step_field(field: str, value: object) -> object:
    if field not in STEP_FIELDS:
        raise ValueError("Unknown profile step field")
    if field == "enabled":
        if type(value) is not bool:
            raise ValueError("Enabled must be boolean")
        return value
    if field == "notes":
        if not isinstance(value, str) or len(value) > 4096:
            raise ValueError("Notes must contain at most 4096 characters")
        return value
    if field in OPTIONAL_DECIMAL_FIELDS and (value is None or value == ""):
        return None
    if field == "target_temperature_c":
        return _decimal(value, field, minimum=-MAX_ABS_TEMPERATURE_C,
                        maximum=MAX_ABS_TEMPERATURE_C)
    if field in ("stabilize_s", "dwell_s"):
        return _decimal(value, field, minimum=Decimal(0), maximum=MAX_DURATION_S)
    if field == "reach_timeout_s":
        return _decimal(value, field, strictly_positive=True, maximum=MAX_DURATION_S)
    return _decimal(value, field, strictly_positive=True, maximum=MAX_POSITIVE_C)


def validate_editor_profile(profile: ParsedProfile) -> ParsedProfile:
    """Run editor bounds AND round-trip through authoritative canonical validation.

    A profile is portable: capability mismatch is diagnostic, NOT a vendor-specific
    schema rewrite or an assertion that a real chamber can execute the profile.
    """
    if not isinstance(profile, ParsedProfile):
        raise ValueError("Invalid profile")
    if not 1 <= len(profile.steps) <= MAX_STEPS:
        raise ValueError("Profile requires 1..200 steps")
    for index, step in enumerate(profile.steps, 1):
        if type(step.enabled) is not bool or type(step.step) is not int or step.step != index:
            raise ValueError("Steps must be numbered consecutively with boolean enabled")
        for field in STEP_FIELDS:
            _step_field(field, getattr(step, field))
    if not any(step.enabled for step in profile.steps):
        raise ValueError("At least one step must be enabled")
    if type(profile.repeat_count) is not int or not 1 <= profile.repeat_count <= 100:
        raise ValueError("Repeat count must be between 1 and 100")
    if not isinstance(profile.name, str) or not 1 <= len(profile.name) <= 160:
        raise ValueError("Profile name must contain 1..160 characters")
    if not isinstance(profile.description, str) or len(profile.description) > 4096:
        raise ValueError("Description exceeds 4096 characters")
    if profile.completion_action != "STOP":
        raise ValueError("Only STOP is supported as completion action")
    try:
        checked = import_profile_zip(export_profile_zip(profile))
    except (BadZipFile, OverflowError, TypeError, KeyError) as exc:
        raise ValueError("Invalid canonical profile") from exc
    if checked != profile:
        raise ValueError("Canonical round-trip altered profile data")
    return profile


def compatibility_warnings(profile: ParsedProfile,
                           capabilities: ChamberCapabilities | None) -> tuple[str, ...]:
    """Informational only; G06/G04 revalidate against live certified capabilities."""
    if capabilities is None:
        return ("Chamber capabilities unavailable: execution compatibility unverified.",)
    issues: list[str] = []
    for step in profile.steps:
        if not step.enabled:
            continue
        number = step.step
        if not capabilities.temperature_min_c <= step.target_temperature_c <= capabilities.temperature_max_c:
            issues.append(f"Step {number}: target outside reported chamber temperature range")
        for field, direction in (("ramp_up_c_per_min", "up"), ("ramp_down_c_per_min", "down")):
            value = getattr(step, field)
            if value is None:
                continue
            supported = getattr(capabilities, "supports_ramp_" + direction)
            limits = getattr(capabilities, "ramp_" + direction + "_range_c_per_min")
            if not supported or limits is None:
                issues.append(f"Step {number}: {direction} gradient is not supported/verified")
            elif not limits[0] <= value <= limits[1]:
                issues.append(f"Step {number}: {direction} gradient outside supported range")
    return tuple(issues)


class ProfileEditorService:
    """Chamber-scoped, stateless persistence facade shared by browser sessions."""

    def __init__(self, store: ProfileStore, chamber_id: str):
        validate_chamber_id(chamber_id)
        self.store = store
        self.chamber_id = chamber_id

    @staticmethod
    def new_draft() -> EditorDraft:
        initial = ProfileStep(1, True, Decimal("25"), None, None,
                              Decimal("2"), Decimal("0"), Decimal("300"),
                              Decimal("3600"), "Ambient soak")
        return EditorDraft(ParsedProfile((initial,), name="New Temperature Profile"))

    def profiles(self, *, limit: int = 100, offset: int = 0) -> tuple[ProfileHeader, ...]:
        return self.store.list_profiles(self.chamber_id, limit=limit, offset=offset)

    def open(self, profile_id: str, revision: int | None = None) -> EditorDraft:
        record = self.store.get_revision(self.chamber_id, profile_id, revision=revision)
        past = record.revision != record.header.current_revision
        return EditorDraft(record.profile, record.header.profile_id,
                           record.header.current_revision, record.revision, past)

    def use_historical_as_draft(self, draft: EditorDraft) -> EditorDraft:
        if not draft.read_only or draft.profile_id is None:
            raise ValueError("Choose an immutable historical revision first")
        # Latest head is checked at the point of restoration, then fenced again on Save.
        head = self.store.get_revision(self.chamber_id, draft.profile_id)
        return replace(draft, expected_revision=head.revision,
                       read_only=False, dirty=True)

    @staticmethod
    def _editable(draft: EditorDraft) -> None:
        if draft.read_only:
            raise ValueError("Historical revisions are read-only; use Restore as draft")

    def set_metadata(self, draft: EditorDraft, field: str, value: object) -> EditorDraft:
        self._editable(draft)
        if field == "name":
            if not isinstance(value, str) or not 1 <= len(value) <= 160:
                raise ValueError("Profile name must contain 1..160 characters")
        elif field == "description":
            if not isinstance(value, str) or len(value) > 4096:
                raise ValueError("Profile description exceeds 4096 characters")
        elif field == "repeat_count":
            if isinstance(value, bool):
                raise ValueError("Invalid repeat count")
            try:
                number = _decimal(value, "repeat_count", minimum=Decimal("1"),
                                  maximum=Decimal("100"))
                if number != number.to_integral_value():
                    raise ValueError("Repeat count must be a whole number")
                value = int(number)
            except (ValueError, TypeError) as exc:
                raise ValueError("Invalid repeat count") from exc
            if not 1 <= value <= 100:
                raise ValueError("Repeat count must be 1..100")
        else:
            raise ValueError("Unknown metadata field")
        return replace(draft, profile=replace(draft.profile, **{field: value}), dirty=True)

    def edit_step(self, draft: EditorDraft, index: int, field: str,
                  value: object) -> EditorDraft:
        self._editable(draft)
        if type(index) is not int or not 0 <= index < len(draft.profile.steps):
            raise ValueError("Unknown step")
        converted = _step_field(field, value)
        steps = list(draft.profile.steps)
        steps[index] = replace(steps[index], **{field: converted})
        return replace(draft, profile=replace(draft.profile, steps=tuple(steps)), dirty=True)

    def change_step(self, draft: EditorDraft, operation: str,
                    index: int | None = None) -> EditorDraft:
        self._editable(draft)
        steps = list(draft.profile.steps)
        if operation == "add":
            if len(steps) >= MAX_STEPS:
                raise ValueError("Maximum of 200 steps")
            source = steps[-1]
            steps.append(replace(source, notes="New step"))
        else:
            if type(index) is not int or not 0 <= index < len(steps):
                raise ValueError("Select a valid step")
            if operation == "duplicate":
                if len(steps) >= MAX_STEPS:
                    raise ValueError("Maximum of 200 steps")
                steps.insert(index + 1, replace(steps[index]))
            elif operation == "delete":
                if len(steps) <= 1:
                    raise ValueError("A profile needs at least one step")
                steps.pop(index)
            elif operation == "up" and index > 0:
                steps[index - 1], steps[index] = steps[index], steps[index - 1]
            elif operation == "down" and index < len(steps) - 1:
                steps[index + 1], steps[index] = steps[index], steps[index + 1]
            else:
                raise ValueError("Step cannot be moved in that direction")
        numbered = tuple(replace(step, step=pos) for pos, step in enumerate(steps, 1))
        return replace(draft, profile=replace(draft.profile, steps=numbered), dirty=True)

    def validate(self, draft: EditorDraft) -> ParsedProfile:
        return validate_editor_profile(draft.profile)

    def save(self, draft: EditorDraft) -> EditorDraft:
        self._editable(draft)
        profile = self.validate(draft)
        if draft.profile_id is None:
            header = self.store.create_profile(self.chamber_id, profile)
        else:
            if draft.expected_revision is None:
                raise ValueError("Missing expected profile revision")
            header = self.store.save_revision(
                self.chamber_id, draft.profile_id, profile,
                expected_revision=draft.expected_revision)
        return EditorDraft(profile, header.profile_id, header.current_revision,
                           header.current_revision)

    def duplicate(self, draft: EditorDraft) -> EditorDraft:
        profile = replace(draft.profile, name=(draft.profile.name[:153] + " (Copy)")[:160])
        self.validate(profile)
        header = self.store.create_profile(self.chamber_id, profile)
        return EditorDraft(profile, header.profile_id, header.current_revision,
                           header.current_revision)

    def import_file(self, data: bytes, *, filename: str,
                    legacy_reach_timeout_s: object | None = None) -> EditorDraft:
        if not isinstance(data, bytes) or len(data) > 2 * MAX_BYTES:
            raise ValueError("Import exceeds maximum of 2 MB")
        if not isinstance(filename, str) or len(filename) > 255:
            raise ValueError("Invalid import filename")
        extension = Path(filename).suffix.lower()
        if extension == ".csv":
            timeout = None if legacy_reach_timeout_s is None else _decimal(
                legacy_reach_timeout_s, "legacy reach timeout", strictly_positive=True,
                maximum=MAX_DURATION_S)
            profile = parse_profile_csv(data, legacy_reach_timeout_s=timeout)
        elif extension == ".zip":
            try:
                profile = import_profile_zip(data)
            except BadZipFile as exc:
                raise ValueError("Invalid ZIP") from exc
        else:
            raise ValueError("Only CSV or ZIP profiles can be imported")
        self.validate(EditorDraft(profile))
        # Idempotent repeated imports: compare validated profile values, never ZIP
        # bytes (ZIP timestamps change for otherwise identical archives).
        offset = 0
        while offset < MAX_DUPLICATE_SCAN:
            page = self.profiles(limit=200, offset=offset)
            for header in page:
                existing = self.store.get_revision(self.chamber_id, header.profile_id)
                if existing.profile == profile:
                    raise DuplicateProfileError(header)
            if len(page) < 200:
                break
            offset += len(page)
        else:
            raise ValueError("Too many profiles for duplicate detection; import denied")
        header = self.store.import_profile(
            self.chamber_id, data, filename=filename,
            legacy_reach_timeout_s=(
                _decimal(legacy_reach_timeout_s, "legacy reach timeout", strictly_positive=True,
                         maximum=MAX_DURATION_S)
                if extension == ".csv" and legacy_reach_timeout_s is not None else None
            ))
        return self.open(header.profile_id)

    def export(self, draft: EditorDraft, *, format: str) -> tuple[bytes, str, str]:
        """Only persisted revisions are downloadable; never export unsaved edits."""
        if draft.profile_id is None or draft.viewed_revision is None:
            raise ValueError("Save the draft before exporting")
        if draft.dirty:
            raise ValueError("Unsaved changes: save or discard them before exporting")
        if format == "zip":
            return (self.store.export_revision_zip(
                self.chamber_id, draft.profile_id, revision=draft.viewed_revision
            ), "profile_rev" + str(draft.viewed_revision) + ".zip", "application/zip")
        if format in ("csv", "spreadsheet_csv"):
            return (self.store.export_revision_csv(
                self.chamber_id, draft.profile_id, revision=draft.viewed_revision,
                spreadsheet_safe=format == "spreadsheet_csv"
            ), "profile_rev" + str(draft.viewed_revision) +
                ("_spreadsheet.csv" if format == "spreadsheet_csv" else ".csv"),
                "text/csv")
        raise ValueError("Unsupported export format")
