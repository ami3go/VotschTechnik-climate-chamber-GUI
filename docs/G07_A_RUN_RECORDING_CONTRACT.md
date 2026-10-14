# G07-A — Run journal, evidence export, and crash reconciliation (v1)

Status: **implementation candidate, software-only; G06-A #24 merged as 28377a4e; do not merge until final-head Windows G06/G07 integration checks and BLOCKER/HIGH reviews pass**. This contract documents G07-A behavior and explicit remaining gates; it does not certify physical operation, STOP latency, operator authentication or safety.

## API and ownership

`chamber_web.persistence.runs.RunStore(root)` owns a dedicated SQLite database at `root/data/runs.sqlite3`. `RunRecorder(store)` implements the **G06-A v1 synchronous EventSink** (`prepare(snapshot)`, `emit(event)`). The server composition root, not a NiceGUI page, injects `RunRecorder` via `ProfileRunner(..., sink=recorder)`. No automatic runner, backend connection or device mutation is created. The recorder imports only standard Python and `validate_chamber_id` from the vendor-neutral domain. It does not import a manufacturer adapter, socket, NiceGUI or G06's scheduler.

Only **one authoritative application process** may own a deployment. Startup `store.reconcile_startup()` must run under exclusive process/service ownership **before** accepting profiles or enabling chamber mutations. G08-min (merged [PR #25](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/25), still separate from G07) must guard History/Logs reads and exports, enforce operator access and audit permission decisions at the service/router boundary. Caller-provided run/chamber IDs are *never* authorization.

## Transaction/lifecycle semantics

| Stage | Durable evidence | Interruption policy |
|---|---|---|
| `PREPARED` | Snapshot JSON + SHA-256 in SQLite committed synchronously before G04 mutation. The first `PREPARED` event is separately indexed. | If no command-intent exists, recovery records `INTERRUPTED` with an explicit RECOVERY event. |
| `START_INTENT` | Synchronous SQLite `BEGIN IMMEDIATE` + FULL synchronous COMMIT of v1 event before the first setpoint/start call. | After restart, classify unfinalized run as `UNKNOWN`; **no** automatic STOP, restart, state inference or sample insertion. |
| `RUNNING` | Ordered, individually journaled G06 STATE, SAMPLE, STEP_COMPLETED and SETPOINT_INTENT observations; unique sample/event indices. | Same `UNKNOWN` classification, never imply stopped. |
| `STOP_INTENT` | STOP intent event committed before G04 STOP attempt. | Remains `UNKNOWN` on interrupted process until a separately authorized verification/reconciliation path. |
| `FINALIZING` | G06 TERMINAL event is committed, including its original terminal state, before CSV/manifest work. | Recover CSV/manifest **offline** from the already durable TERMINAL event; do not send chamber commands. |
| `COMPLETED / ABORTED / FAULT / UNKNOWN / INTERRUPTED` | Atomic CSV exports followed by SHA-256 manifest and finalized SQLite status. CANCELLED in G06 maps to ABORTED in storage. | Terminal status immutable to the public API; tampered files raise `RunIntegrityError`. |

The presence of STOP_INTENT **does not** establish STOP success. G06's terminal event represents its own verified readback policy, not independent hardware certification. When a crash occurs after a started run but before a persisted TERMINAL event, startup cannot infer any safe device condition: `UNKNOWN` remains the only conservative disposition.

`prepare` and `emit` must propagate SQLite errors without converting failed persistence into success. G06-A must fail closed and schedule STOP for failed observation/intent recording. Individual `emit` operations use one SQLite transaction with `PRAGMA synchronous=FULL`. `emit_batch` is a bounded (<=1000 events) journal import/stress-test path only; production G06 intent delivery calls `emit` synchronously, never buffers control intents.

## Evidence artifacts and integrity

Files live under `root/data/chambers/<chamber_id>/runs/<run_uuid>/`. `run_uuid` is a canonical UUID4; `chamber_id` is validated by the G01 domain contract. Paths are constructed solely from validated identifiers. No supplied filename/path is accepted for generated artifacts.

- `snapshot.json`: frozen canonical execution snapshot, including profile revision provenance, backend identity/capabilities/parameters and initial controller generation. Its SHA-256 must match the immutable SQLite run snapshot digest.
- `events.csv`: immutable indexed events, elapsed monotonic seconds, quality, state, active step and fault diagnostics.
- `samples.csv`: measured temperature, **intended setpoint** from the most recent SETPOINT_INTENT, UTC/source UTC, elapsed time, quality, sequence and step index. **The G06 v1 event does not carry independently read-back setpoint**, so this field must not be mislabeled as readback.
- `manifest.json`: version, run/chamber IDs, frozen snapshot digest, controller generation, terminal state, counts and SHA-256 digests of snapshot and both CSV artifacts.
- Run identity and snapshot are retained in the SQLite database. G03 immutable profile revisions remain in their own independent G03 store.

Export uses temporary files in the same directory, flushed + `fsync`, then `os.replace` and directory `fsync` on POSIX. On Windows, the directory `fsync` is unavailable through this portable implementation; file contents are flushed, and atomic replace is used, but unexpected **power loss between rename and durable directory metadata** remains an explicit Windows risk pending volume-specific tests. Manifest is installed **last**; SQLite terminal state is committed only after completed manifest. A missing/corrupted export never silently overwrites conflicting existing evidence. SQLite and files are not falsely described as a single distributed/atomic transaction; `FINALIZING` is the recovery bridge.

The recorder does not promise recoverability if the SQLite database itself is physically corrupted or the filesystem disregards flush/barrier requirements. It never claims that an ENOSPC or power-loss event had no effects on the hardware.

## Read-only History/Logs/export APIs

- `list_runs(chamber_id, limit<=200, offset>=0, since_utc, until_utc)` lists run summaries.
- `get_run(chamber_id, run_id)` gives immutable metadata and snapshot JSON, scoped by chamber.
- `list_events(chamber_id, run_id, limit<=500, after_sequence, since_utc, until_utc)` returns a bounded event page.
- `plot_samples(chamber_id, run_id, limit<=5000, first_sample, last_sample)` returns at most the requested number of downsampled points. It is **sampling**, not a min/max-preserving extrema aggregator; a high-density graph may conceal short excursions.
- `verify_artifacts`, `read_csv(name='events.csv'|'samples.csv', max_bytes<=128 MiB)` and `read_zip(max_bytes<=128 MiB)` validate digests and enforce strict, bounded download sizes. Exports exceeding these limits are refused, not silently truncated. Untrusted diagnostic CSV text is spreadsheet-formula neutralized. The reader is synchronous; NiceGUI integration must offload it outside the event loop, and G08-min must apply authorization, rate limiting and download auditing.

Large run support means disk-based evidence and bounded plot/history queries; it does **not** mean unbounded in-memory 1M-point graph or unlimited ZIP downloads. The 1M test asserts actual SQLite ingestion and final CSV/manifest digest after materialization.

## Verification and release blockers

Windows Python 3.10/3.12: `python -m unittest discover -s tests -p "test_run_recording.py" -v`; static ruff `E4,E7,E9,F`; separate Windows Python 3.12 test with `G07_STRESS=1` for 1,000,000 samples. Tests inject transaction errors, ENOSPC, fsync failures, conflicting event replay, cross-chamber IDs, unexpected schema, corrupted exports/manifests and interrupted startup phases. CI results, final review and merging must be reported **only after they actually exist**.

### Review and outstanding risks

1. **INTEGRATION GATE — merged G06-A dependency:** PR #24 merged as `28377a4e`. G07-A is rebased on that commit, with a real G06 ProfileRunner-to-RunRecorder integration suite covering separate Fake/alternate adapter instances and an injected START_INTENT write failure. Remains a blocker until both Windows versions pass on the final reviewed commit.
2. **HIGH — verified setpoint in G06 v1 EventSink:** SAMPLE emits measured temperature but no *readback* setpoint or per-event controller-generation. G07 captures the immutable generation and intended setpoint; to satisfy independently observed setpoint per sample, extend the upstream G06 contract/add a compatible field and test it before interpreting command intent as observation.
3. **HIGH — single-host durability:** Windows rename/directory metadata durability under power loss remains unverified. Workstation disk and clean-VM fault tests required for release; SQLite assumes durable local storage.
4. **HIGH — access control:** Merged G08-min cannot be bypassed by exposing history, logs or evidence files directly to unauthenticated clients. These are server-service APIs only; no HTTP endpoint is defined by this PR.
5. **MEDIUM — size/plot quality:** 128 MiB bounded downloads reject very large runs, and stride downsampling does not preserve peaks. Implement authenticated streaming and an extrema-preserving plot API before claiming complete large-run UI parity.
6. **MEDIUM — archival trust:** SHA-256 hashes are corruption checks, not third-party attestations or cryptographic signatures. Formal evidence retention, backup, tamper-evident external anchoring and database-corruption restoration remain site policy work.

This is an engineering/software evidence layer. H01 site safety approval, physical STOP validation, G08 full security, G08-min integration with future G07 HTTP pages and W02 certification remain **NO-GO**.


### SQLite startup corruption regression (2026-10-14)

`RunStore` now executes SQLite `PRAGMA quick_check(1)` on startup before accepting its schema and refuses damaged database pages with `RunIntegrityError`. A regression test corrupts the database header and verifies startup rejects it without silent recreation. This is only a structural check, not a substitute for full integrity scanning, independent evidence anchoring, backup/restore drills, or Windows power-cut tests. H01 extended simulated test workflow now also triggers on G07 recorder changes. Independent review and site safety acceptance remain outstanding.
