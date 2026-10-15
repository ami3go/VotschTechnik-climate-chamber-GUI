"""G03-C durable profile editor service regression tests (no physical I/O)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from chamber_web.domain.chamber import ChamberCapabilities
from chamber_web.domain.profile import MAX_BYTES, export_profile_zip
from chamber_web.persistence.profiles import (
    ProfileConflictError, ProfileNotFoundError, ProfileStore,
)
from chamber_web.services.profile_editor import (
    DuplicateProfileError, ProfileEditorService, compatibility_warnings,
    validate_editor_profile,
)

LEGACY = (b"target,ramp,tolerance,dwell,description,enabled\n"
          b"25,5,1,60,=1+2,True\n")


@pytest.fixture
def editor(tmp_path: Path) -> ProfileEditorService:
    return ProfileEditorService(ProfileStore(tmp_path / "profiles.db"), "chamber-A")


def test_create_save_restart_and_unmodified_old_revisions(editor, tmp_path):
    draft = editor.new_draft()
    draft = editor.set_metadata(draft, "name", "Thermal soak")
    first = editor.save(draft)
    assert first.viewed_revision == 1
    edited = editor.edit_step(first, 0, "target_temperature_c", "-40")
    second = editor.save(edited)
    assert second.profile_id == first.profile_id
    assert second.viewed_revision == 2
    restarted = ProfileEditorService(ProfileStore(tmp_path / "profiles.db"), "chamber-A")
    assert restarted.open(first.profile_id).profile.steps[0].target_temperature_c == -40
    old = restarted.open(first.profile_id, revision=1)
    assert old.read_only
    assert old.profile.steps[0].target_temperature_c == 25
    with pytest.raises(ValueError, match="read-only"):
        restarted.edit_step(old, 0, "notes", "overwrite")
    restored = restarted.use_historical_as_draft(old)
    assert restarted.save(restored).viewed_revision == 3
    assert restarted.open(first.profile_id, revision=2).profile == second.profile


def test_stale_two_browser_editors_never_overwrite(editor):
    saved = editor.save(editor.new_draft())
    first_tab = editor.open(saved.profile_id)
    second_tab = editor.open(saved.profile_id)
    editor.save(editor.set_metadata(first_tab, "name", "First editor"))
    stale = editor.set_metadata(second_tab, "name", "Second editor")
    with pytest.raises(ProfileConflictError):
        editor.save(stale)
    assert editor.open(saved.profile_id).profile.name == "First editor"
    assert stale.profile.name == "Second editor"  # draft remains available


def test_competing_saves_single_winner(editor):
    initial = editor.save(editor.new_draft())
    barrier = Barrier(4, timeout=10)

    def edit(idx):
        local = editor.edit_step(editor.open(initial.profile_id), 0, "notes", str(idx))
        barrier.wait()
        try:
            return editor.save(local).viewed_revision
        except ProfileConflictError:
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(edit, range(4)))
    assert results.count(2) == 1
    assert results.count(None) == 3


@pytest.mark.parametrize("field,value", [
    ("target_temperature_c", "NaN"),
    ("target_temperature_c", "Infinity"),
    ("target_temperature_c", "1001"),
    ("dwell_s", "-1"),
    ("dwell_s", "2592001"),
    ("reach_timeout_s", "0"),
    ("stabilize_s", "-0.1"),
    ("tolerance_c", "0"),
    ("ramp_up_c_per_min", "1001"),
    ("enabled", "true"),
    ("chamber_run", "sometimes"),
    ("compressed_air", True),
    ("dryer", "enabled"),
    ("digital_outputs", "1=ON"),
    ("digital_outputs", "2=ON;2=OFF"),
    ("notes", "X" * 4097),
    ("__class__", "foo"),
])
def test_invalid_step_edits_are_atomic(editor, field, value):
    original = editor.new_draft()
    with pytest.raises(ValueError):
        editor.edit_step(original, 0, field, value)
    assert original.profile.steps[0].target_temperature_c == 25


def test_step_order_resequence_and_validation(editor):
    draft = editor.new_draft()
    added = editor.change_step(draft, "add")
    added = editor.edit_step(added, 1, "target_temperature_c", -40)
    added = editor.change_step(added, "up", 1)
    assert [(s.step, s.target_temperature_c) for s in added.profile.steps] == [
        (1, -40), (2, 25)]
    added = editor.change_step(added, "duplicate", 0)
    assert [s.step for s in added.profile.steps] == [1, 2, 3]
    added = editor.change_step(added, "delete", 1)
    assert [s.step for s in added.profile.steps] == [1, 2]
    assert editor.save(added).viewed_revision == 1


def test_output_edits_are_canonical_and_persisted(editor):
    draft = editor.new_draft()
    draft = editor.edit_step(draft, 0, "chamber_run", "off")
    draft = editor.edit_step(draft, 0, "compressed_air", "on")
    draft = editor.edit_step(draft, 0, "dryer", "unchanged")
    draft = editor.edit_step(draft, 0, "digital_outputs", "6=OFF;2=ON")
    saved = editor.save(draft)
    step = editor.open(saved.profile_id).profile.steps[0]
    assert step.chamber_run == "OFF"
    assert step.compressed_air == "ON"
    assert step.dryer == "UNCHANGED"
    assert step.digital_outputs == ((2, True), (6, False))

    unsupported = ChamberCapabilities(-40, 130, True, True, True)
    warnings = compatibility_warnings(saved.profile, unsupported)
    assert "digital outputs [2, 6, 7]" in str(warnings)


def test_disabled_every_step_invalid_and_huge_numeric_rejected(editor):
    draft = editor.edit_step(editor.new_draft(), 0, "enabled", False)
    with pytest.raises(ValueError, match="enabled"):
        editor.save(draft)
    with pytest.raises(ValueError):
        editor.edit_step(draft, 0, "dwell_s", "1e999999999")


def test_legacy_import_zip_provenance_and_spreadsheet_escape(editor):
    imported = editor.import_file(LEGACY, filename="demo.csv", legacy_reach_timeout_s=600)
    assert imported.viewed_revision == 1
    assert imported.profile.legacy_original == LEGACY
    assert imported.profile.steps[0].ramp_up_c_per_min is None
    machine, _, _ = editor.export(imported, format="csv")
    excel, _, _ = editor.export(imported, format="spreadsheet_csv")
    zip_data, _, _ = editor.export(imported, format="zip")
    assert b"=1+2" in machine
    assert b"'=1+2" in excel
    assert b"legacy_import.csv" in zip_data
    assert export_profile_zip(imported.profile) != b""
    with pytest.raises(ValueError, match="Unsaved"):
        editor.export(editor.edit_step(imported, 0, "notes", "new"), format="zip")
    imported_zip = ProfileEditorService(
        ProfileStore(editor.store.path), "chamber-B"
    ).import_file(zip_data, filename="archive.zip")
    assert imported_zip.profile.legacy_original == LEGACY


def test_duplicate_import_skips_new_profile_identity(editor):
    original = editor.import_file(LEGACY, filename="first.csv", legacy_reach_timeout_s=300)
    with pytest.raises(DuplicateProfileError) as exc:
        editor.import_file(LEGACY, filename="copy.csv", legacy_reach_timeout_s=300)
    assert exc.value.header.profile_id == original.profile_id
    assert len(editor.profiles()) == 1


@pytest.mark.parametrize("payload,name,timeout", [
    (b"garbage", "x.csv", None),
    (b"PKx", "x.zip", None),
    (LEGACY, "x.csv", None),
    (LEGACY, "x.txt", 300),
    (b"X" * (2 * MAX_BYTES + 1), "x.zip", None),
    (b"step,enabled,target_temperature_c\n1,true,25\n", "bad.csv", None),
], ids=[
    "malformed-csv", "malformed-zip", "legacy-timeout-required",
    "unrecognized-extension", "oversized-zip", "invalid-canonical-header",
])
def test_invalid_imports_do_not_write(editor, payload, name, timeout, request):
    # Regression: pytest must never expand megabyte-scale binary cases in
    # test node IDs; Windows Actions logging became unresponsive on 2 MB lines.
    assert len(request.node.nodeid) < 256
    with pytest.raises(ValueError):
        editor.import_file(payload, filename=name, legacy_reach_timeout_s=timeout)
    assert editor.profiles() == ()


def test_isolation_and_backend_substitution(tmp_path):
    path = tmp_path / "one.db"
    alpha = ProfileEditorService(ProfileStore(path), "alpha")
    beta = ProfileEditorService(ProfileStore(path), "beta")
    a = alpha.save(alpha.new_draft())
    assert beta.profiles() == ()
    with pytest.raises(ProfileNotFoundError):
        beta.open(a.profile_id)
    with pytest.raises(ProfileNotFoundError):
        beta.export(a, format="zip")
    assert alpha.open(a.profile_id) == a
    profile = a.profile
    second_vendor = ChamberCapabilities(
        temperature_min_c=-15, temperature_max_c=60,
        supports_start_stop=False, supports_running_readback=False,
        supports_setpoint_readback=False, supports_ramp_up=False,
        supports_ramp_down=False,
    )
    assert compatibility_warnings(profile, second_vendor) == ()
    gradients = alpha.edit_step(a, 0, "ramp_up_c_per_min", "4")
    assert "not supported" in str(compatibility_warnings(gradients.profile, second_vendor))
    temp = alpha.edit_step(a, 0, "target_temperature_c", "-40")
    assert "outside reported" in str(compatibility_warnings(temp.profile, second_vendor))
    assert validate_editor_profile(gradients.profile) == gradients.profile
    # Device incompatibility is warnings for portable storage; no execution exists.


def test_refresh_starts_fresh_draft_but_store_persists(editor, tmp_path):
    saved = editor.save(editor.new_draft())
    new_browser = ProfileEditorService(ProfileStore(tmp_path / "profiles.db"), "chamber-A")
    assert new_browser.new_draft().profile_id is None
    assert new_browser.open(saved.profile_id).profile_id == saved.profile_id


def test_repeat_count_requires_integer(editor):
    draft = editor.new_draft()
    assert editor.set_metadata(draft, "repeat_count", 2.0).profile.repeat_count == 2
    with pytest.raises(ValueError):
        editor.set_metadata(draft, "repeat_count", 2.5)
    with pytest.raises(ValueError):
        editor.set_metadata(draft, "repeat_count", True)


def test_unchanged_metadata_does_not_dirty_reloaded_profile(editor):
    stored = editor.save(editor.new_draft())
    assert not stored.dirty
    hydrated = editor.set_metadata(stored, "name", stored.profile.name)
    assert hydrated == stored
    assert not hydrated.dirty
