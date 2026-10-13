"""G03-B durable per-chamber profile revision and migration tests."""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from io import BytesIO
from threading import Barrier
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from chamber_web.domain.chamber import ChamberSafetyError
from chamber_web.domain.profile import (
    MAX_BYTES, export_profile_csv, export_profile_zip, import_profile_zip, parse_profile_csv,
)
from chamber_web.persistence.profiles import (
    ProfileConflictError, ProfileNotFoundError, ProfileSchemaError, ProfileStore,
)

@contextmanager
def _sqlite(path: Path):
    # sqlite3.Connection.__exit__ commits/rolls back but does NOT close the
    # handle. Windows prevents TemporaryDirectory cleanup until it is closed.
    with closing(sqlite3.connect(path)) as db:
        with db:
            yield db


LEGACY = (
    b"target,ramp,tolerance,dwell,description,enabled\n"
    b"25,5,1,60,=2+2,True\n"
)


class ProfileStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.db_path = Path(self.temporary.name) / "data" / "profiles.sqlite3"
        self.store = ProfileStore(self.db_path)
        self.profile = parse_profile_csv(LEGACY, legacy_reach_timeout_s=Decimal("600"))

    def test_create_revision_restart_and_immutable_history(self):
        first = self.store.create_profile("alpha", self.profile)
        self.assertEqual(first.current_revision, 1)
        self.assertEqual(self.store.get_revision("alpha", first.profile_id).profile, self.profile)
        updated = replace(self.profile, name="Cycle v2", repeat_count=2)
        second = self.store.save_revision("alpha", first.profile_id, updated,
                                          expected_revision=1)
        self.assertEqual(second.current_revision, 2)
        reopened = ProfileStore(self.db_path)
        self.assertEqual(reopened.get_revision("alpha", first.profile_id).profile, updated)
        self.assertEqual(reopened.get_revision("alpha", first.profile_id,
                                                revision=1).profile, self.profile)
        self.assertEqual(len(reopened.list_profiles("alpha")), 1)

    def test_cross_chamber_isolation_even_with_known_id(self):
        saved = self.store.create_profile("alpha", self.profile)
        self.assertEqual(self.store.list_profiles("beta"), ())
        with self.assertRaises(ProfileNotFoundError):
            self.store.get_revision("beta", saved.profile_id)
        with self.assertRaises(ProfileNotFoundError):
            self.store.save_revision("beta", saved.profile_id, self.profile,
                                     expected_revision=1)
        with self.assertRaises(ProfileNotFoundError):
            self.store.export_revision_zip("beta", saved.profile_id)
        self.assertEqual(self.store.get_revision("alpha", saved.profile_id).revision, 1)

    def test_sequential_distinct_backend_fixtures_use_same_schema(self):
        # Different IDs represent separate one-device installations/fixtures,
        # not a fleet runtime and not physical control.
        first = self.store.create_profile("fake-room", self.profile)
        other = self.store.create_profile("alternate-room", replace(self.profile,
                                                        name="Different envelope"))
        self.assertNotEqual(first.profile_id, other.profile_id)
        self.assertEqual([p.name for p in self.store.list_profiles("fake-room")],
                         [self.profile.name])
        self.assertEqual([p.name for p in self.store.list_profiles("alternate-room")],
                         ["Different envelope"])

    def test_editor_conflict_prevents_lost_update(self):
        saved = self.store.create_profile("alpha", self.profile)
        writer1 = ProfileStore(self.db_path)
        writer2 = ProfileStore(self.db_path)
        writer1.save_revision("alpha", saved.profile_id,
                              replace(self.profile, name="Editor 1"), expected_revision=1)
        with self.assertRaises(ProfileConflictError):
            writer2.save_revision("alpha", saved.profile_id,
                                  replace(self.profile, name="Editor 2"), expected_revision=1)
        self.assertEqual(self.store.get_revision("alpha", saved.profile_id).profile.name,
                         "Editor 1")

    def test_transaction_rollback_on_failure_after_insert(self):
        saved = self.store.create_profile("alpha", self.profile)
        with _sqlite(self.db_path) as db:
            db.execute("CREATE TRIGGER reject_head BEFORE UPDATE ON profiles "
                       "BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.save_revision("alpha", saved.profile_id,
                                     replace(self.profile, name="Uncommitted"),
                                     expected_revision=1)
        with _sqlite(self.db_path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM profile_revisions").fetchone()[0], 1)
        self.assertEqual(self.store.get_revision("alpha", saved.profile_id).revision, 1)

    def test_invalid_import_is_atomic(self):
        with self.assertRaises(ValueError):
            self.store.import_profile("alpha", b"garbage", filename="broken.csv")
        with self.assertRaises(ValueError):
            self.store.import_profile("alpha", LEGACY, filename="old.csv")
        with self.assertRaises(ValueError):
            self.store.import_profile("alpha", b"not a zip", filename="broken.zip")
        self.assertEqual(self.store.list_profiles("alpha"), ())

    def test_legacy_import_retains_original_csv_and_ramp_provenance(self):
        saved = self.store.import_profile("alpha", LEGACY, filename="old.csv",
                                           legacy_reach_timeout_s=Decimal("600"))
        record = self.store.get_revision("alpha", saved.profile_id)
        self.assertEqual(record.source_format, "legacy_csv")
        self.assertEqual(record.profile.legacy_original, LEGACY)
        self.assertIsNone(record.profile.steps[0].ramp_up_c_per_min)
        self.assertIsNone(record.profile.steps[0].ramp_down_c_per_min)
        self.assertEqual(self.store.export_revision_zip("alpha", saved.profile_id),
                         export_profile_zip(record.profile))
        self.assertNotEqual(self.store.export_revision_csv("alpha", saved.profile_id),
                            LEGACY)  # standalone CSV loses legacy ramp provenance
        self.assertEqual(ProfileStore(self.db_path).get_revision(
            "alpha", saved.profile_id).profile.legacy_original, LEGACY)

    def test_zip_exports_have_fixed_metadata_and_identical_bytes(self):
        # Regression for issue #22: writestr(name, data) used local wall-clock
        # timestamps so identical profiles exported around a 2-second tick
        # produced different archive bytes on Windows 3.10/3.12.
        first = export_profile_zip(self.profile)
        self.assertEqual(first, export_profile_zip(self.profile))
        with ZipFile(BytesIO(first)) as archive:
            self.assertEqual(
                {item.date_time for item in archive.infolist()},
                {(1980, 1, 1, 0, 0, 0)},
            )
        legacy = self.store.import_profile(
            "alpha", LEGACY, filename="old.csv",
            legacy_reach_timeout_s=Decimal("600"),
        )
        legacy_profile = self.store.get_revision("alpha", legacy.profile_id).profile
        legacy_data = export_profile_zip(legacy_profile)
        self.assertEqual(legacy_data, export_profile_zip(legacy_profile))
        with ZipFile(BytesIO(legacy_data)) as archive:
            self.assertEqual(archive.read("legacy_import.csv"), LEGACY)
            self.assertEqual(
                {item.date_time for item in archive.infolist()},
                {(1980, 1, 1, 0, 0, 0)},
            )

    def test_zip_import_roundtrip(self):
        archive = export_profile_zip(self.profile)
        saved = self.store.import_profile("alpha", archive, filename="test.zip")
        self.assertEqual(self.store.get_revision("alpha", saved.profile_id).source_format, "zip")
        self.assertEqual(import_profile_zip(self.store.export_revision_zip("alpha", saved.profile_id)),
                         import_profile_zip(archive))

    def test_oversized_profile_fields_rejected_before_zip_compression(self):
        step = self.profile.steps[0]
        invalid = (
            replace(self.profile, steps=(replace(step, notes="N" * (MAX_BYTES + 1)),)),
            replace(self.profile, migration_warning="W" * (MAX_BYTES + 1)),
            replace(self.profile, legacy_original=b"L" * (MAX_BYTES + 1)),
        )
        for profile in invalid:
            with self.subTest(field=type(profile).__name__):
                # A rejected payload must never reach compression or a DB write.
                with patch("chamber_web.domain.profile.ZipFile",
                           side_effect=AssertionError("ZIP created before validation")):
                    with self.assertRaises(ValueError):
                        self.store.create_profile("alpha", profile)
        self.assertEqual(self.store.list_profiles("alpha"), ())

    def test_malformed_zip_manifest_is_validation_error(self):
        buffer = BytesIO()
        with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr("profile.csv", export_profile_csv(self.profile))
            archive.writestr("profile.json", "[]")
        with self.assertRaisesRegex(ValueError, "manifest"):
            self.store.import_profile("alpha", buffer.getvalue(), filename="bad.zip")
        self.assertEqual(self.store.list_profiles("alpha"), ())

    def test_concurrent_revision_writers_have_one_winner(self):
        header = self.store.create_profile("alpha", self.profile)
        barrier = Barrier(8)

        def save(index):
            barrier.wait()
            try:
                return self.store.save_revision(
                    "alpha", header.profile_id,
                    replace(self.profile, name=f"Writer {index}"),
                    expected_revision=1,
                )
            except ProfileConflictError:
                return None

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(save, range(8)))
        winners = [result for result in results if result is not None]
        self.assertEqual(len(winners), 1)
        self.assertEqual(winners[0].current_revision, 2)
        self.assertEqual(self.store.get_revision("alpha", header.profile_id).revision, 2)
        with _sqlite(self.db_path) as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM profile_revisions WHERE profile_id=?",
                (header.profile_id,),
            ).fetchone()[0], 2)

    def test_immutability_trigger_blocks_unexpected_sql_updates(self):
        saved = self.store.create_profile("alpha", self.profile)
        with _sqlite(self.db_path) as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("DELETE FROM profile_revisions WHERE profile_id=?",
                           (saved.profile_id,))
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE profile_revisions SET revision=100 WHERE profile_id=?",
                           (saved.profile_id,))

    def test_checksum_tampering_refuses_corrupt_revision(self):
        saved = self.store.create_profile("alpha", self.profile)
        with _sqlite(self.db_path) as db:
            db.execute("DROP TRIGGER revision_no_update")
            db.execute("UPDATE profile_revisions SET archive=? WHERE profile_id=?",
                       (b"tampered", saved.profile_id))
        with self.assertRaises(ProfileSchemaError):
            self.store.get_revision("alpha", saved.profile_id)
        with self.assertRaises(ProfileSchemaError):
            ProfileStore(self.db_path)

    def test_recognized_trigger_name_cannot_mask_noop_trigger(self):
        with _sqlite(self.db_path) as db:
            db.execute("DROP TRIGGER revision_no_update")
            db.execute(
                "CREATE TRIGGER revision_no_update BEFORE UPDATE ON "
                "profile_revisions BEGIN SELECT 1; END"
            )
        with self.assertRaises(ProfileSchemaError):
            ProfileStore(self.db_path)

    def test_missing_schema_index_fails_closed(self):
        with _sqlite(self.db_path) as db:
            db.execute("DROP INDEX profiles_by_chamber")
        with self.assertRaises(ProfileSchemaError):
            ProfileStore(self.db_path)

    def test_unrecognized_schema_and_version_fail_closed(self):
        with _sqlite(self.db_path) as db:
            db.execute("PRAGMA user_version=99")
        with self.assertRaises(ProfileSchemaError):
            ProfileStore(self.db_path)

    def test_unversioned_nonempty_db_is_not_overwritten(self):
        path = Path(self.temporary.name) / "unknown.sqlite3"
        with _sqlite(path) as db:
            db.execute("CREATE TABLE unrelated(data TEXT)")
        with self.assertRaises(ProfileSchemaError):
            ProfileStore(path)
        with _sqlite(path) as db:
            self.assertTrue(db.execute("SELECT name FROM sqlite_master "
                                       "WHERE name='unrelated'").fetchone())

    def test_reject_bad_ids_revisions_and_unbounded_listing(self):
        saved = self.store.create_profile("alpha", self.profile)
        for invalid in ("../alpha", "", " space", "é"):
            with self.assertRaises(ChamberSafetyError):
                self.store.list_profiles(invalid)
        with self.assertRaises(ValueError):
            self.store.get_revision("alpha", "not-a-uuid")
        with self.assertRaises(ValueError):
            self.store.save_revision("alpha", saved.profile_id, self.profile,
                                     expected_revision=True)
        with self.assertRaises(ValueError):
            self.store.list_profiles("alpha", limit=201)
        with self.assertRaises(ValueError):
            self.store.list_profiles("alpha", offset=-1)
        with self.assertRaises(ProfileNotFoundError):
            self.store.get_revision("alpha", saved.profile_id, revision=100)


if __name__ == "__main__":
    unittest.main()
