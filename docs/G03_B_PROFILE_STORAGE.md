# G03-B — SQLite profile storage contract (software-only)

This module is the database/backend part of G03, **not the NiceGUI profile editor**. It does not connect to a chamber, start a profile, modify the demo state, or authorize any physical command.

## API

`chamber_web.persistence.ProfileStore(db_path)` creates a new version 1 SQLite file when its path does not exist, or opens a matching, recognized application database. Unsupported version, application ID, missing tables, or missing immutability triggers **fail closed**. There is no automatic database downgrade or destructive migration.

- `create_profile(chamber_id, ParsedProfile)` saves revision 1.
- `import_profile(chamber_id, bytes, filename=".csv"/".zip", legacy_reach_timeout_s=...)` strictly validates the whole file before creating a profile. Legacy CSV requires an explicit reach timeout and retains its original bytes in the canonical ZIP.
- `save_revision(chamber_id, profile_id, ParsedProfile, expected_revision=N)` creates immutable revision N+1 and atomically advances the head. Outdated editors receive `ProfileConflictError` and never overwrite another editor's work.
- `get_revision(chamber_id, profile_id, revision=N)`, `list_profiles(chamber_id, limit=100, offset=0)`, and `export_revision_zip/csv` are chamber-scoped. The optional revision selects historical immutable content; omitted means latest.
- Profile IDs are server-generated UUIDs. Every read, write and export needs the stable configured `chamber_id`; a cross-chamber lookup is indistinguishable from not found. List requests are bounded to 200 profiles.

The persisted artifact is a canonical, versioned ZIP with SHA-256 verified on read, including the original legacy CSV and migration warning when present. A standalone canonical CSV loses legacy ramp provenance; use ZIP for archival interchange. Spreadsheet-safe CSV is a distinct opt-in export. Raw SQL writes to past revisions are blocked by triggers; append-only revision history does not imply a tamper-proof database against filesystem administrators.

## Storage and lifecycle

Use a trusted **server-owned** path, e.g. `data/profiles.sqlite3`, rather than a browser-supplied path. One SQLite transaction contains both the revision insert and the head update; SQLite `BEGIN IMMEDIATE` serializes competing writes, while optimistic revision checks reject stale browser edits. No device commands take place inside these transactions. SQLite `synchronous=FULL` is enabled; deployment still needs operational backups, directory permissions and the single-authoritative-process policy specified for G04/G07.

Copying an in-use SQLite database file is **not** a valid backup strategy. Use SQLite's online backup API on a quiescent/consistent snapshot and preserve migration rollback copies before introducing any future schema version.

The G03-C editor must integrate this service behind server-side authentication and role checks before making profiles mutable in a real network deployment. The G06 runner will later freeze the selected immutable revision into run evidence; G07 separately implements run-file journals and crash recovery. No site STOP policy, HIL approval, or real Vötsch operation is implied.

## Verification

Run `python -m unittest discover -s tests -p "test_profile_*.py" -v` and the full Windows CI. The G03-B suite covers restart, immutable old revisions, stale concurrent editors, cross-device isolation, conversion provenance, invalid import atomicity, induced transaction rollback, checksum tampering, unknown schema, and bounded listing.
