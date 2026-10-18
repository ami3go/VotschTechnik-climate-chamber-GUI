# G07-A PR #27 — merge-gate audit (2026-10-13)

Status: **MERGED 2026-10-15 AS `fa77998faff9343c1751e6c0bf5d5a78bb4712af` / SIMULATOR ONLY (software); the release gates below remain OPEN.** This review records verified evidence and outstanding gates. Do not interpret GitHub mergeability or green automated checks as approval for physical operation.

- PR: https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/27
- Reviewed head: `157f66e20ff1430d4a7a0a31e54830b7310de3ef`
- Current main at audit: `64c3d8c2d41bd40173428aaec4ca5125af60dd95`; branch diverged (2 main commits behind), requiring re-synchronization and fresh exact-head CI before merge (subsequently re-synchronized and merged 2026-10-15).
- GitHub reports mergeable but draft; submitted review is COMMENTED, no recorded independent human approval; no unresolved inline review threads.

## Exact-head successful GitHub Actions evidence (head 157f66e)

- G07 Windows Python 3.10/3.12 recorder, G06 integration, fault tests, 1,000,000 SQLite samples: https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38450800954
- G06 Windows Python 3.10/3.12: https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38450800975
- NiceGUI Windows Python 3.10/3.12: https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38450801074
- W01 Windows PyInstaller / simulated launch: https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38450800989

These checks passed at the stated head; they are NOT results for a future synchronized commit. The existing G07 workflow has no separate G08-specific authorization regression step, and W01 extracted simulator checks are not W02 air-gapped certification.

## Review of code and open issues

| ID | Severity | Evidence and disposition |
|---|---|---|
| G07-R1 | HIGH / release | `runs.py:_sync_parent` explicitly skips Windows directory metadata sync. Atomic file replacement and fsynced file data are implemented; power-cut / filesystem durability is unverified. Require fault testing on target Windows volume and documented recovery policy. |
| G07-R2 | HIGH / evidence fidelity | G06 v1 SAMPLE includes measured temperature but not independently observed setpoint/readback nor per-sample controller generation. `intended_setpoint_c` must stay labeled as intent; upstream compatible G06 event contract, mock readback and regression tests required before claiming measured setpoint evidence. |
| G07-R3 | HIGH / authorization integration | G07 exposes Python read/export services, not HTTP routes. Future History/Logs and downloads must require G08-min authorization, audit and limits at every server entrypoint. Direct access to data files is forbidden. |
| G07-R4 | HIGH / integrity | `RunStore._find` verifies only snapshot SHA. `verify_artifacts` validates the manifest and exported file digests against SQLite counters and state, but does not cryptographically anchor the SQLite events to immutable remote evidence. An actor capable of mutating both DB and local evidence can forge a consistent set; require authenticated external anchoring/backups for evidentiary trust. Detect/reject database corruption with a tested fail-closed startup and restoration procedure. |
| G07-R5 | MEDIUM | `plot_samples` samples with fixed stride; it can hide brief extrema. Replace with bounded min/max-preserving buckets (plus edge points) before claiming diagnostic plot completeness. |
| G07-R6 | MEDIUM | CSV/ZIP exports enforce 128 MiB maximum, so larger runs are refused. Add bounded authenticated streaming or explicitly retain a documented maximum, with deterministic size tests. |
| G07-R7 | HIGH / rollout | `reconcile_startup` must be called once under exclusive process ownership before accepting commands; tests for two simultaneous processes/service restarts, interrupted manifest finalization, and conservative STOP_INTENT => UNKNOWN remain mandatory for operational gate. |
| G07-R8 | HIGH / integration | Current branch is 2 commits behind main. Merge latest main without losing G03-C or G08-min, run complete final-head CI, and obtain an external human architecture/security/durability approval before marking ready. |

## What is verified versus unverified

The review shows an isolated standard-library recorder, SQLite synchronous=FULL write transactions, sequential event/sample indexing, SHA-256-checked exports, offline recovery categories and tests for injected errors. The exact-head G07/G06/NiceGUI/W01 runs passed. This is software evidence, not a power-loss certification or proof of safe hardware STOP.

Physical hardware I/O **remains disabled**. G04 stays the exclusive chamber I/O owner. The recorder neither imports manufacturer drivers nor owns a second execution engine, and startup recovery must never command or automatically resume equipment.

**Merge decision (2026-10-13): HOLD. Closure (2026-10-18):** PR #27 merged 2026-10-15 as `fa77998faff9343c1751e6c0bf5d5a78bb4712af` after the synchronized head passed all G07/G06/NiceGUI/W01 Windows checks. Independent human approval was NOT obtained; every release item in the tables below remains OPEN.

## 2026-10-15 candidate revision and corrective action (not independent approval)

Branch was reconfirmed as based on `main` `4be73edda855ea53cc5a1417ec8583fd37dfed98`; candidate source **before this documentation-only commit** is `efe22762a8d3add07f61e1405f629f17909f20f9`, including preserved merged H01 and setup functionality. Prior accepted exact-head `007e6053258680dd8df16175e66dfb00847c535d` passed [G07 Windows 3.10/3.12 + 1M](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38613839443), [G06](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38613839478), [NiceGUI](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38613839398), [H01 Windows/Linux/Chromium](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38613839547) and [W01 Windows frozen simulator](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38613839384). These are *historical* green checks, not the latest-head verdict.

**Resolved in candidate source:** G07-R9 HIGH (absence of run SQLite DB while per-run evidence or SQLite sidecar remains could previously create empty replacement). Added fail-closed pre-open detection and regression tests for missing DB and orphan WAL; added six-worker concurrent idempotent replay test and G06/G04 simulator cancel + STOP_INTENT crash/recovery + evidence tamper/ZIP test. G07 workflow now runs G04 STOP-fencing and G08-min security tests for each Windows Python version. No new recording architecture, web HTTP route, physical driver connection or physical control is introduced.

**Outstanding:** All release/HIGH items R1 (Windows power loss), R2 (independent setpoint readback + generation from G06), R3 (authorization for any future History/Logs/exports), R4 (trusted archival anchoring and backup recovery), R7 (exclusive process-startup integration/physical interruption), R8 (independent human review and final exact-source CI) remain open. Documented unit/software remediation **does not** close physical HIL, G08-full or W02. This audit is AI-assisted technical review only; its author cannot supply independent human approval. Keep PR draft, do not merge absent required gates. Actual final-head CI run IDs and conclusions must be recorded in the PR audit discussion after GitHub reports them.
