"""G03-B durable per-chamber profile revision and migration tests."""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from chamber_web.domain.chamber import ChamberSafetyError
from chamber_web.domain.profile import export_profile_zip, import_profile_zip, parse_profile_csv
from chamber_web.persistence.profiles import (
    ProfileConflictError, ProfileNotFoundError, ProfileSchemaError, ProfileStore,
)

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
        with sqlite3.connect(self.db_path) as db:
            db.execute("CREATE TRIGGER reject_head BEFORE UPDATE ON profiles "
                       "BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.save_revision("alpha", saved.profile_id,
                                     replace(self.profile, name="Uncommitted"),
                                     expected_revision=1)
        with sqlite3.connect(self.db_path) as db:
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

    def test_zip_import_roundtrip(self):
        archive = export_profile_zip(self.profile)
        saved = self.store.import_profile("alpha", archive, filename="test.zip")
        self.assertEqual(self.store.get_revision("alpha", saved.profile_id).source_format, "zip")
        self.assertEqual(import_profile_zip(self.store.export_revision_zip("alpha", saved.profile_id)),
                         import_profile_zip(archive))

    def test_immutability_trigger_blocks_unexpected_sql_updates(self):
        saved = self.store.create_profile("alpha", self.profile)
        with sqlite3.connect(self.db_path) as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("DELETE FROM profile_revisions WHERE profile_id=?",
                           (saved.profile_id,))
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE profile_revisions SET revision=100 WHERE profile_id=?",
                           (saved.profile_id,))

    def test_checksum_tampering_refuses_corrupt_revision(self):
        saved = self.store.create_profile("alpha", self.profile)
        with sqlite3.connect(self.db_path) as db:
            db.execute("DROP TRIGGER revision_no_update")
            db.execute("UPDATE profile_revisions SET archive=? WHERE profile_id=?",
                       (b"tampered", saved.profile_id))
        with self.assertRaises(ProfileSchemaError):
            self.store.get_revision("alpha", saved.profile_id)
        with self.assertRaises(ProfileSchemaError):
            ProfileStore(self.db_path)

    def test_unrecognized_schema_and_version_fail_closed(self):
        with sqlite3.connect(self.db_path) as db:
            db.execute("PRAGMA user_version=99")
        with self.assertRaises(ProfileSchemaError):
            ProfileStore(self.db_path)

    def test_unversioned_nonempty_db_is_not_overwritten(self):
        path = Path(self.temporary.name) / "unknown.sqlite3"
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE unrelated(data TEXT)")
        with self.assertRaises(ProfileSchemaError):
            ProfileStore(path)
        with sqlite3.connect(path) as db:
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
