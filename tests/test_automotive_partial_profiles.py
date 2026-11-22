"""Partial temperature-only coverage is a research metric, never HIL approval."""
from __future__ import annotations

from decimal import Decimal

import pytest

from chamber_web.adapters.fake import FakeBackend
from chamber_web.domain.chamber import ChamberCapabilities
from chamber_web.domain.profile import (
    export_profile_csv, export_profile_zip, import_profile_zip,
    is_unapproved_automotive_template, parse_profile_csv,
)
from chamber_web.services.automotive_partial_profiles import (
    PARTIAL_METHOD_IDS, assess_partial_coverage, partial_candidate_draft,
    thermal_targets,
)
from chamber_web.services.profile_editor import ProfileEditorService
from chamber_web.persistence.profiles import ProfileStore


def caps(low=-40, high=130):
    return ChamberCapabilities(low, high, True, True, True)


def test_all_partial_sources_have_explicitly_defined_sequences():
    assert PARTIAL_METHOD_IDS == {"ISO-STEP", "LV-K-02", "LV-K-03"}
    assert len(thermal_targets("LV-K-02")) == 29
    assert thermal_targets("LV-K-02")[0] == -55
    assert thermal_targets("LV-K-02")[-1] == 85
    assert thermal_targets("LV-K-03") == (-55,)


def test_default_simulated_range_passes_85_percent_with_missing_targets():
    report = assess_partial_coverage("LV-K-02", FakeBackend("fake").capabilities())
    assert (report.supported_points, report.possible_points) == (26, 29)
    assert report.percentage == Decimal("89.7")
    assert report.meets_threshold
    assert report.missing_targets_c == (Decimal("-55"), Decimal("-50"), Decimal("-45"))
    draft = partial_candidate_draft(
        "LV-K-02", caps(), dwell_s=300, tolerance_c=2,
        stabilize_s=60, reach_timeout_s=3600)
    assert len(draft.profile.steps) == 26
    assert draft.profile.steps[0].target_temperature_c == -40
    assert "Missing targets: -55, -50, -45" in draft.profile.description
    assert draft.profile.name.endswith("(partially)")
    assert is_unapproved_automotive_template(draft.profile)


def test_below_85_percent_k02_is_still_blocked():
    report = assess_partial_coverage("LV-K-02", caps(-30, 130))
    assert (report.supported_points, report.possible_points) == (24, 29)
    assert report.percentage == Decimal("82.8")
    assert not report.meets_threshold
    with pytest.raises(ValueError, match="85%"):
        partial_candidate_draft(
            "LV-K-02", caps(-30, 130), dwell_s=300, tolerance_c=2,
            stabilize_s=60, reach_timeout_s=3600)


def test_above_85_percent_k02_with_25_of_29_setpoints():
    report = assess_partial_coverage("LV-K-02", caps(-35, 130))
    assert (report.supported_points, report.possible_points) == (25, 29)
    assert report.percentage == Decimal("86.2")
    assert report.meets_threshold


def test_93_percent_k02_creates_archivable_unapproved_partial(tmp_path):
    report = assess_partial_coverage("LV-K-02", caps(-45, 130))
    assert (report.supported_points, report.possible_points) == (27, 29)
    assert report.percentage == Decimal("93.1") and report.meets_threshold
    draft = partial_candidate_draft(
        "LV-K-02", caps(-45, 130), dwell_s=300,
        tolerance_c=2, stabilize_s=60, reach_timeout_s=3600)
    assert draft.profile_id is None and draft.dirty
    assert draft.profile.name.endswith("(partially)")
    assert len(draft.profile.steps) == 27
    assert draft.profile.steps[0].target_temperature_c == -45
    assert "Missing targets: -55, -50" in draft.profile.description
    assert "NOT compliant" in draft.profile.description
    assert all(step.ramp_up_c_per_min is None for step in draft.profile.steps)
    assert is_unapproved_automotive_template(draft.profile)
    assert is_unapproved_automotive_template(import_profile_zip(
        export_profile_zip(draft.profile)))
    assert is_unapproved_automotive_template(parse_profile_csv(
        export_profile_csv(draft.profile)))
    store = ProfileStore(tmp_path / "profiles.db")
    editor = ProfileEditorService(store, "chamber-a")
    assert editor.profiles() == ()  # candidate creation doesn't touch SQLite
    saved = editor.save(draft)
    assert is_unapproved_automotive_template(editor.open(saved.profile_id).profile)


def test_iso_stepped_draft_requires_explicit_tmin_tmax_dwell():
    stage = thermal_targets("ISO-STEP", tmin_c=-40, tmax_c=85)
    assert len(stage) == 51
    assert stage[0] == 20 and stage[-1] == 20
    assert min(stage) == -40 and max(stage) == 85
    report = assess_partial_coverage("ISO-STEP", caps(), tmin_c=-40, tmax_c=85)
    assert report.percentage == 100 and report.meets_threshold
    draft = partial_candidate_draft(
        "ISO-STEP", caps(), tmin_c=-40, tmax_c=85,
        dwell_s=300, tolerance_c=1, stabilize_s=60,
        reach_timeout_s=2400)
    assert len(draft.profile.steps) == 51
    assert draft.profile.repeat_count == 1
    assert "(partially)" in draft.profile.name
    assert is_unapproved_automotive_template(draft.profile)
    with pytest.raises(ValueError, match="explicitly"):
        thermal_targets("ISO-STEP", tmin_c=-40)
    with pytest.raises(ValueError, match="5 °C"):
        thermal_targets("ISO-STEP", tmin_c=-41, tmax_c=85)


def test_lvk03_only_when_55_cold_exposure_within_reported_limits():
    assert not assess_partial_coverage("LV-K-03", caps(-40, 130)).meets_threshold
    assert assess_partial_coverage("LV-K-03", caps(-60, 100)).percentage == 100
    with pytest.raises(ValueError, match="172800"):
        partial_candidate_draft(
            "LV-K-03", caps(-60, 100), dwell_s=3600,
            tolerance_c=1, stabilize_s=60, reach_timeout_s=3600)
    draft = partial_candidate_draft(
        "LV-K-03", caps(-60, 100), dwell_s=172800,
        tolerance_c=1, stabilize_s=60, reach_timeout_s=3600)
    assert draft.profile.steps[0].target_temperature_c == -55
    assert is_unapproved_automotive_template(draft.profile)


@pytest.mark.parametrize("method", [
    "LV-K-05", "LV-K-08", "LV-L-02", "UN-R100-9B",
    "GB-PACK-SHOCK", "AEC-Q100-A4-G2", "IEC-DAMP-CYCLIC",
])
def test_nonrepresentable_facility_and_lifetime_methods_never_partial(method):
    with pytest.raises(ValueError, match="not eligible"):
        thermal_targets(method, tmin_c=-40, tmax_c=85)


def test_no_runnable_candidate_when_bounds_or_watchdog_unknown():
    with pytest.raises(ValueError, match="capabilities"):
        assess_partial_coverage("LV-K-02", None)
    with pytest.raises(ValueError, match="14-day"):
        partial_candidate_draft(
            "ISO-STEP", caps(-1000, 1000), tmin_c=-40, tmax_c=85,
            dwell_s=30000, tolerance_c=1, stabilize_s=60, reach_timeout_s=3600)
    with pytest.raises(ValueError, match="stabilization"):
        partial_candidate_draft(
            "LV-K-02", caps(-55, 85), dwell_s=300,
            tolerance_c=1, stabilize_s=3600, reach_timeout_s=100)
