# G03-C — Persistent NiceGUI profile editing and immutable revisions

Implementation scope: one configured chamber, read-only device telemetry, **no profile execution
or hardware commands**. Code: `chamber_web/pages/profiles.py` +
`chamber_web/services/profile_editor.py` using the existing G03-A
`ParsedProfile/ProfileStep` and G03-B `ProfileStore`.

## Interaction contract

- Dashboard "Profiles" navigates to `/profiles` instead of the historical browser-local
  editable table. Persistent Profiles are independent of Dashboard refresh and clients.
- One **uncommitted server-side draft per open NiceGUI page instance**. Drafts are not persisted
  until Save. A page refresh/reconnect starts a fresh draft; saved profiles must be reloaded
  from the library. Unsaved edits are explicitly labeled and not promised to survive a restart.
- The Profile Library pages through 100 items; every open is scoped to the configured
  `chamber_id` obtained from the server dashboard service. There is no chamber picker.
  Profile IDs are generated in the store and are distinct across duplicates.
- AG Grid edits the canonical v2 fourteen-column schema, including enabled, target Celsius,
  optional ramp-up/down Celsius per minute, tolerance, stabilize seconds, dwell seconds,
  reach timeout seconds, chamber run, compressed air, dryer, numbered digital outputs,
  and notes. Named outputs use `ON` / `OFF` / `UNCHANGED`; other outputs use the
  bounded `number=ON;number=OFF` syntax. Outputs 1, 7 and 8 are reserved for the
  named columns. Steps may be inserted/duplicated/deleted/reordered,
  and are resequenced to 1..N. Null ramps are a schema-level capability-neutral value,
  **not** a request to inherit arbitrary previous hardware settings.
- Profile name, description and repeats are managed in the editor. Completion action is
  the canonical STOP. No browser-supplied adapter, controller ID, path, module or command.
- Save calls `create_profile` (new) or `save_revision(... expected_revision=...)`.
  A head mismatch results in a visible conflict; the competing revision remains intact and
  the stale browser's draft is retained. There is **no** automatic overwrite/merge.
- Historical revisions are strictly read-only. "Restore Historical as Draft" copies old
  content into the editor while capturing the **current** head revision; Save appends
  another revision with optimistic fencing instead of rewriting history.
- Duplicate Profile creates a separate profile identity. A repeated exact import
  (including legacy migration provenance) is rejected with the existing profile ID.
  Duplicate detection is guarded by a process-local lock consistent with the v1
  authoritative-process contract; excess database size above 5,000 scanned profiles
  fails closed rather than silently bypassing duplicate detection.

## Data validation and file interchange

All mutations and file contents are parsed/validated in Python before SQLite writes.
The client grid and HTML input constraints are merely presentation hints, not a trust boundary.

- Canonical G03-A v2 CSV requires exactly the fourteen headers and ordered rows. Existing
  ten-column v1 CSV/ZIP files remain importable and migrate to chamber run `ON` with all
  auxiliary outputs unchanged; the legacy six-column simulator CSV is a distinct input
  format. Legacy import requires an explicit operator
  reach timeout; physical gradient fields remain null, historical simulation ramps stay in
  `legacy_import.csv` inside archival ZIP with checksums and warning metadata.
- Files are capped at 1 MB CSV / 2 MB ZIP; expansion and entry count are constrained by
  the canonical ZIP parser; unexpected/traversal/duplicate/encrypted entries fail.
  A profile holds 1..200 ordered steps and at least one enabled step.
- In addition to strict canonical finite numbers, profile-editor entry/import policy
  applies **software-only sanity limits** of ±1,000 °C target, 0..1,000 positive
  tolerances/gradients, 0..2,592,000 seconds stabilize/dwell and
  (0,2,592,000] seconds reach timeout. Repeats are integers 1..100.
  These values are **not chamber hardware capabilities or safety certification**.
  The real runner must revalidate a frozen profile snapshot against signed current
  limits before dispatch.
- AG Grid sends a single edited cell; Python checks index and field allowlist before
  updating the server draft. A failed edit rolls the grid back to Python's canonical values.
  Raw note text is rendered as text, never as HTML/template/code.
- Only persisted saved revisions can be downloaded. ZIP is lossless; canonical CSV may
  omit legacy metadata; separate spreadsheet-safe CSV escapes formula-prefixed notes
  and is intentionally not a lossless round-trip format. Both are labeled.
- Alternative backend compatibility feedback uses normalized
  `ChamberCapabilities`: out-of-range targets and unsupported gradient settings are
  visibly flagged, as are requested numbered outputs without a verified capability.
  Saving portable profile data does not assert that execution is safe;
  the G04/G06 controller/runner owns final authorization and compatibility.

## Persistence and Windows deployment

Database path is server-owned: on Windows `ClimateChamber/W01/profiles.sqlite3`
under LocalAppData (the W01 launcher state directory); on POSIX,
`~/.local/state/climate-chamber/profiles.sqlite3` (or `XDG_STATE_HOME`).
An administrator can override with process environment `CHAMBER_PROFILE_DB`;
the browser cannot choose a path. Back up via SQLite online backup API, not
copying a live database. The SQLite schema, foreign keys and immutable-revision
triggers are owned by G03-B; **no migrations or schema changes** introduced by G03-C.

NiceGUI + AG Grid assets are already part of pinned `nicegui==3.18.0`. No runtime
CDN, npm, arbitrary Python plugin or hardware communication is added. W01 remains
an early standalone packaging feasibility test only; W02 still needs disconnected
clean-VM verification and backup/restore documentation.

## Security and integration gate

PR #26 merged at `fee88ab7929b414e02ac11d81881450e8c9ac365` with G08-min authenticated role guards on the NiceGUI Profiles route and every server-side read/mutation callback. Viewer editor controls are disabled; backend permission checks (READ or PROFILE_EDIT) remain authoritative after refresh/reconnect/session revocation. The browser does not hold a G04 controller or run engine. This is mock-only software verification.

- Current main's web demo binds **127.0.0.1** and uses a **FakeBackend**.
  G03-C does not create an alternative authentication/session scheme or a control API.
  G08-min PR #25 now provides ADMIN/OPERATOR/VIEWER and server-side per-callback
  guards for edit/import/duplicate/save/export in PR #26, with
  CSRF/Origin/WebSocket protections. **Physical and non-loopback operation remain
  disabled** until full G08, signed site policy, HIL and W02. UI hiding is not authorization.
- G02-B may consolidate shared navigation/layout and remove the remaining Dashboard-only
  demo draft telemetry/preview. The Dashboard navigation entry and editor card now
  direct users to this persistent route; Dashboard, History, Logs and Settings are not
  otherwise implemented by G03-C.
- G06-A must snapshot a specific immutable `profile_id` + revision and revalidate
  capabilities/timing limits before profile execution. Nothing in this page can START,
  STOP, PAUSE, enqueue controller commands, or certify hardware readiness.
- The app supports **one configured physical chamber maximum**, even though
  profile records remain individually keyed by stable chamber ID.

## Verification

Windows workflow `.github/workflows/web-gui-demo.yml` runs the original safety/
model/dashboard/storage tests and adds `pytest tests/test_profile_editor.py
tests/test_web_profiles_ui.py` for Windows Python 3.10 and 3.12.
Regression coverage: SQLite restart, immutable history, two stale tabs, competing
writers, limits and malformed inputs, canonical and legacy ZIP/CSV, duplicates,
formula-safe download, cross-chamber isolation, sequential alternate backend
capability preview, and per-session browser refresh behavior.

Physical HIL, G08 authentication, G06 execution, G07 run history/recorder, G02-B
shared-shell integration and W02 fully offline Windows are explicitly OPEN.

## 2026-10-13 merged integration verification

G03-C [PR #26](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/26) merge `fee88ab7929b414e02ac11d81881450e8c9ac365`, final head `e82aba60e30a330c20944d98f9f28040ef1c93d0`. Exact-head Windows Python 3.10/3.12 [NiceGUI/security/profile CI 38441138681](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38441138681), [G06 CI 38441138685](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38441138685), [W01 offline-simulation build 38441138664](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38441138664) all passed. G08 guards enforce authorization at UI callback dispatch and re-check after file-read await; simulated cross-feature regression tests exercise G03 immutable revision, G06 profile execution and G08 revocation/STOP. G07 history and H01 actual chamber validation remain OPEN. Windows CI previously cancelled due 2 MB pytest node IDs; short IDs preserve fixture coverage. Deterministic ZIP entry metadata removes separate timestamp-driven Windows flake (issue #22).
