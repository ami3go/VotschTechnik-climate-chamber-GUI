"""Automotive temperature catalogue and unapproved template tests (no hardware)."""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from chamber_web.domain.profile import (
    export_profile_csv, export_profile_zip, import_profile_zip,
    is_unapproved_automotive_template, parse_profile_csv,
)
from chamber_web.services.automotive_profile_templates import (
    candidate_draft, find_method, method_templates, standard_templates,
)
from chamber_web.services.profile_editor import ProfileEditorService
from chamber_web.persistence.profiles import ProfileStore


def test_research_catalogue_complete_and_consistent():
    methods = method_templates()
    standards = standard_templates()
    assert len(methods) == 60
    assert len(standards) == 86
    identifiers = {method.id for method in methods}
    assert len(identifiers) == len(methods)
    assert len({standard.id for standard in standards}) == len(standards)
    assert all(set(standard.method_ids) <= identifiers for standard in standards)
    assert all(method.source_url.startswith("https://") for method in methods)
    assert all(std.source_url.startswith("https://") for std in standards)
    assert sum(method.can_make_draft for method in methods) == 6
    assert len([m for m in methods if m.id.startswith("LV-")]) == 16
    assert find_method("ISO-HOT-STORAGE").temperatures == "+85"


@pytest.mark.parametrize("method,target,dwell", [
    ("ISO-COLD-STORAGE", Decimal("-40"), Decimal("86400")),
    ("ISO-HOT-STORAGE", Decimal("85"), Decimal("172800")),
    ("ISO-COLD-OP", Decimal("-30"), Decimal("86400")),
    ("ISO-HOT-OP", Decimal("105"), Decimal("345600")),
    ("IEC-COLD-METHOD", Decimal("-20"), Decimal("3600")),
    ("IEC-DRY-HEAT-METHOD", Decimal("65"), Decimal("7200")),
])
def test_explicit_candidates_are_valid_but_not_executable(method, target, dwell):
    needs_target = method not in ("ISO-COLD-STORAGE", "ISO-HOT-STORAGE")
    is_iec = method.startswith("IEC")
    candidate = candidate_draft(
        method, target_c=target if needs_target else None,
        dwell_s=dwell if is_iec else None, tolerance_c=1,
        stabilize_s=300, reach_timeout_s=7200)
    profile = candidate.profile
    assert candidate.profile_id is None and candidate.dirty
    assert profile.steps[0].target_temperature_c == target
    assert profile.steps[0].dwell_s == dwell
    assert profile.steps[0].ramp_up_c_per_min is None
    assert profile.steps[0].ramp_down_c_per_min is None
    assert profile.steps[0].compressed_air == "UNCHANGED"
    assert profile.steps[0].dryer == "UNCHANGED"
    assert is_unapproved_automotive_template(profile)
    assert is_unapproved_automotive_template(import_profile_zip(export_profile_zip(profile)))
    # CSV is a lossy metadata format: notes must independently carry the blocker.
    assert is_unapproved_automotive_template(parse_profile_csv(export_profile_csv(profile)))


def test_candidate_is_draft_only_no_database_write(tmp_path):
    store = ProfileStore(tmp_path / "profiles.db")
    editor = ProfileEditorService(store, "chamber-A")
    draft = candidate_draft("ISO-COLD-STORAGE", tolerance_c=1,
                            stabilize_s=120, reach_timeout_s=3600)
    assert editor.profiles() == ()
    saved = editor.save(draft)
    assert saved.viewed_revision == 1
    assert is_unapproved_automotive_template(editor.open(saved.profile_id).profile)
    # Ordinary metadata edits and duplicates preserve provenance.
    updated = editor.save(editor.set_metadata(saved, "name", "Review copy"))
    assert is_unapproved_automotive_template(updated.profile)
    copied = editor.duplicate(updated)
    assert is_unapproved_automotive_template(copied.profile)


@pytest.mark.parametrize("method", [
    "LV-K-05", "LV-L-03", "AEC-Q100-A4-G0", "AEC-Q100-A6-G0",
    "AEC-Q100-A2-THB", "UN-R100-9B", "GB-PACK-SHOCK",
])
def test_unsupported_methods_cannot_be_silently_simplified(method):
    with pytest.raises(ValueError, match="needs controlled"):
        candidate_draft(method, target_c=65, dwell_s=7200, tolerance_c=1,
                        stabilize_s=120, reach_timeout_s=3600)


@pytest.mark.parametrize("kwargs", [
    {},
    {"tolerance_c": 0},
    {"tolerance_c": "NaN"},
    {"tolerance_c": 1, "stabilize_s": 0, "reach_timeout_s": 3600},
    {"tolerance_c": 1, "stabilize_s": 300, "reach_timeout_s": 60},
    {"tolerance_c": 1, "stabilize_s": 300, "reach_timeout_s": 3600,
     "target_c": 75},
    {"tolerance_c": 1, "stabilize_s": 300, "reach_timeout_s": 3600,
     "dwell_s": 10},
])
def test_no_silent_defaults_for_safety_critical_severity(kwargs):
    with pytest.raises(ValueError):
        candidate_draft("ISO-COLD-STORAGE", **kwargs)


def test_parameterized_method_needs_explicit_severity():
    with pytest.raises(ValueError, match="temperature"):
        candidate_draft("ISO-HOT-OP", tolerance_c=1, stabilize_s=100,
                        reach_timeout_s=600)
    with pytest.raises(ValueError, match="duration"):
        candidate_draft("IEC-COLD-METHOD", target_c=-30, tolerance_c=1,
                        stabilize_s=100, reach_timeout_s=600)


def test_old_profiles_not_blocked_by_research_marker():
    candidate = candidate_draft("ISO-COLD-STORAGE", tolerance_c=1,
                                stabilize_s=100, reach_timeout_s=600).profile
    clean = replace(candidate, migration_warning=None,
                    steps=(replace(candidate.steps[0], notes="Verified user profile"),))
    assert not is_unapproved_automotive_template(clean)
