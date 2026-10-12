# NiceGUI migration — implementation and merge sequence

Status: PROPOSED / NOT STARTED. This is the execution plan for [WEB_GUI_MIGRATION_PLAN.md](WEB_GUI_MIGRATION_PLAN.md), revised after the 2026-10-12 independent technical review. Phase IDs are **not** GitHub PR numbers. Each delivery unit must have its own PR and review; driver work belongs exclusively to [VotschTechnik-climate-chamber-Python](https://github.com/ami3go/VotschTechnik-climate-chamber-Python).

## Non-negotiable boundaries

- NiceGUI web application; Python package in the GUI repository root (no src/ directory); preserve only the useful visual/layout aspects of the earlier single-file screenshot prototype. No prototype simulator/state machine in production control.
- The external installable VotschTechnikClimateChamber driver is the **only** hardware/protocol layer. GUI code must not contain TCP commands, socket use to the chamber, duplicated device protocol or command numbers.
- Server owns chamber state and profile execution independently of browser clients. Exactly one command owner per chamber and single authoritative server process; operator ownership does not obstruct an authorized STOP.
- NO physical-device release until BLOCKER-01 through BLOCKER-04, site safety approval and the chamber-in-the-loop (HIL) gate pass. Driver reliability fixes must land in the driver repository and the GUI must pin the tested driver revision.
- Local physical emergency stop/manufacturer protections remain necessary. Web STOP is an attempted control command, not a certified emergency stop. A disconnected chamber cannot be asserted stopped.
- Keep legacy Tkinter and historical releases usable until an explicitly approved cutover. Do not merge unreleased simulated/frozen builds as evidence of HIL certification.

## Workstreams and prerequisites

- **A — Specification and driver:** P00, D01. Hardware controller acceptance requires both.
- **B — Foundation/UI/data:** G01, G02, G03 can proceed while D01 is developed. They can use an explicitly labeled fake driver only.
- **C — Early packaging:** W01 begins immediately after G01 (not at the end); keep both required PowerShell build scripts passing through development.
- **D — Control/run engine:** G04 can be developed against fake driver; G05 requires D01 + site-accepted safety policy before enabling physical control; G06–G08 follow tested interfaces.
- **E — Security/certification/cutover:** G09 is required before LAN control; H01 and W02 precede R01 and desktop retirement.

## Ordered delivery units

| ID | Target repository | Task / deliverables | Depends on | Required completion evidence |
|---|---|---|---|---|
| P00 | GUI | Amend specification: device capability + units, site STOP/fault matrix, profile timing, state/fencing, persistence/CSV, OS/session lifecycle, offline bootstrap; acceptance contracts and signoff placeholders | None | No contradictory requirements; four blockers tracked; signed site decisions flagged PENDING until obtained |
| D01 | Driver | Separate backward-compatible driver PR(s): finite connect timeout, socket cleanup, verified full send/framing, bounded read, type/finite/limit validation, start/stop/error semantics; mocked network tests | P00 safety/interface contract | Refused/blackhole/split-frame/failure tests; driver version/tag or immutable commit pinned in GUI before hardware integration |
| G01 | GUI | NiceGUI project foundation: installable root package, config, versioned migrations scaffold, typed service contracts, fake driver, explicit SIMULATION mode, deterministic test clock, CI, launch entry point | P00 initial architecture | Clean install/test; local-only server starts; no hidden hardware access; CI lint/type/unit |
| G02 | GUI | Web shell and visual components from screenshot: Dashboard, Profiles, Run History, Logs, Settings; responsive status/STOP layout; licensed assets strategy | G01 | Browser E2E screenshots at approved desktop/tablet widths; accessibility/keyboard check; disconnected values never simulated as real |
| G03 | GUI | Versioned profile data models, immutable revisions, AG Grid edit/reorder/clone/undo workflow, SQLite schema/migration, standalone step CSV + canonical full-profile ZIP/JSON roundtrip | G01, P00 data contract | Schema boundary/finite validation, version conflict, 100% field roundtrip, formula safety, archive limits and migration tests |
| W01 | GUI | **Early packaging feasibility**: scripts/build_windows_launcher.ps1 and scripts/build_windows_offline.ps1 skeleton with working freeze, embedded assets/driver, manifest and clean-Windows smoke | G01 | Both scripts exist; launcher detects port collision; frozen fake-device app launches with no target Python or downloads |
| G04 | GUI | Sole driver adapter + process owner/lease, command queue and fencing, monotonic status/polling, reconnection and readbacks, separate health/ready/device states | G01, P00; D01 for live hardware | Mocked concurrency races, STOP fencing (zero later setpoints), blackhole/stale-readback, lock/restart and error-state tests |
| G05 | GUI | Manual setpoint, presets, start/stop, device identity and capability handshake, model-safe limits, manual/profile handover + settings freeze; optional gradients default-disabled | G04 + D01 + approved physical STOP policy for live device | Feature parity with old GUI; verified setpoint/start/stop readback and permission checks; unsupported capabilities hidden/disabled |
| G06 | GUI | Profile-runner state machine (launch/reach/stabilize/dwell/pause/resume/abort/repeat), immutable run snapshots and timers | G03, G04, P00 timing/safety contract | Deterministic virtual-clock tests: gaps, excursions, long pauses, timeouts, repeat, reconnect, no commands after abort |
| G07 | GUI | Incremental sample+event CSV, atomic run manifest/reconciliation, run history, bounded/decimated charts and secure downloads | G06 and G03 | Kill process at write/transition boundaries; ENOSPC; partial CSV recovery; 100k/1M samples; simultaneous clients |
| G08 | GUI | Security/ops: offline initial-admin bootstrap, roles/leases, TLS/LAN restrictions, action audit, update/backup policy, service supervision/logoff/shutdown behavior | G01, G04, P00 lifecycle/security contract; parallelizable before hardware release | Air-gapped bootstrap/password recovery, two-user conflict, viewer denial, session expiry, service restart and logout tests |
| H01 | Driver + GUI | VT4011/LabEvent HIL certification, gradient command units/readback and measured slope, transport faults, STOP policy, operator conflict, measurement quality | D01, G05–G08, verified site capability and safety signoff | Written per-model HIL matrix signed; every failure leaves truthful RUNNING/UNKNOWN/FAULT state; no auto-resume |
| W02 | GUI | Complete Windows launcher/offline ZIP, frozen dependency/assets verification, migration/rollback, Win10/11 x64 baseline and clean disconnected VM | W01, G02–G08 | Both scripts pass clean Windows CI; isolated VM requires no Python/dev tools/internet; ZIP checksums and profile/data preservation verified |
| R01 | GUI | Release checklist: documentation, packaging, manuals, formal parity signoff, security/hardware/offline evidence, tagged release; retire old UI only after approval | H01 + W02 + all release gates | Signed GO decision, updated README, recoverable legacy release, no unreviewed main deletions |

P00 and D01 are the **critical path for physical operation**, but they must not block G01/G02/G03/W01 simulated/UI development. G08 security must land before exposing mutation endpoints outside loopback; it may be developed in parallel with G05–G07. W01 is an early feasibility gate, W02 is final offline certification.

## Required design-review artifacts at P00

1. **Safety response matrix** for normal completion, explicit operator STOP, command timeout/ambiguous acknowledgement, communication loss, out-of-safe-envelope measured temperature, loss of logging/disk space, app crash, Windows logout/shutdown, loss/return of power, hardware alarms. For each: requested action, bounded attempt strategy, what can/cannot be verified, fault latch, local intervention. Default STOP on operator abort; HOLD_SETPOINT disabled until specifically approved. NEVER claim return-to-ambient is inherently safe.
2. **Capability records** keyed by physical identity/model/controller and verified configuration: temperature envelope, gradient support/units/ranges and readback, polling constraints. Until HIL verification, gradient inputs are disabled or null/hardware-default; don't label raw driver values °C/min without evidence.
3. **Command contract** listing driver-only methods, timeout and retry policy, state transitions, ambiguous-command policy and cancellation/fencing. On STOP intent: atomically latch stop generation, refuse new control commands, invalidate queued old-generation work; an in-flight call is not preemptible unless the driver transport truly supports it; attempt STOP/readback with bounded deadlines, return UNKNOWN/FAULT when unverifiable.
4. **Ownership contract**: one OS-level server/chamber lock + SQLite transactional lease/generation; startup always inspects incomplete runs, clears no hardware fault automatically, never replays stale commands or auto-resumes a run; every setpoint checks generation immediately before transmission. Manual/profile takeover is never silent; require audited abort/completion before new owner.
5. **Profile-time contract**: all intervals use monotonic clock; band inclusive; only GOOD fresh observations contribute; stability requires at least two valid observations spanning configured stable time and no stale/gap/out-of-band observations; a gap resets stability, dwell stops accumulating during gaps/excursions; PAUSE freezes transition/dwell but not safety and absolute watchdog. Set bounded reach/stabilize/dwell and absolute step/run deadlines, including across pause (unless separately signed exception). Observation cadence cannot prove between-sample temperature; label as observed stability.
6. **Data contract**: versioned profile CSV step-only vs canonical ZIP (profile.csv + profile.json), max import size/rows/ZIP expansion/precision, reversible machine CSV and separate spreadsheet-safe export; run CSV sample sequence + quality, per-run manifest, write-order/atomic finish, incomplete markers, ENOSPC policy, quota, snapshot read while active, server-side plot sampling.
7. **Windows lifecycle/security**: supervised server not owned by browser/launcher, explicit service vs portable logoff semantics, authenticated instance discovery and separate process/device health; first-run offline admin setup (loopback), roles, TLS for LAN, OS/browser baseline, signed/integrity-checkable offline updates and schema backup before upgrade.

Do not silently convert PENDING choices to defaults. If site-signoff information is unavailable, implement the simulator/UI contracts and keep physical control disabled.

## PR contract and merge order

- **One cohesive delivery unit per PR**; D01 may be multiple small driver PRs with the same gate, followed by a tagged or commit-pinned driver update in the GUI repository. PR ID labels in this document are not GitHub numbers.
- Each PR description includes scope, dependencies, source/driver versions, acceptance checklist, unit/integration/E2E/HIL scope, risk and rollback path. New functionality gets documented public interfaces; no hidden socket/protocol implementation in the GUI.
- Required checks: Ruff/lint, type checks, Python unit tests, fake-driver integration tests and changed-area browser tests. W01/W02 additionally require Windows builds and no-network clean VM; H01 requires separate physical-device sign-off.
- **Review before merge** by an independent requirements/code reviewer; fix BLOCKER/HIGH findings and rerun tests. Do not merge red CI, security regressions, incomplete STOP fencing, or unverified physical safety claims.
- Merge in dependency order. Never enable physical control using an unpinned/unhardened driver. Pin driver/library dependencies and record a manifest. HIL and air-gap gates are independent and both mandatory.
- After each merged PR verify next-phase prerequisites and update task status/evidence links here; final release only after R01 signoff.

## Mandatory cross-cutting acceptance tests

| Concern | Deterministic test | Minimum pass condition |
|---|---|---|
| Driver transport | unreachable IP, refused, delayed connect, short send, split/oversized/malformed frame, malformed status, disconnect mid-command | Finite configured deadlines; no leaked socket; never infer success from incomplete response |
| Queue/STOP | simultaneous owner commands, poll active, STOP while busy, queued stale setpoint, reconnect with old generation | No control request admitted after STOP intent; no old-generation setpoint sent afterward; UNKNOWN/FAULT when stop unverifiable |
| Hardware identity | wrong model/firmware, mismatched safety envelope, unsupported gradient, NaN/Inf | No device write; clear actionable error; signed limits remain bounded |
| Runner time | exact tolerance boundary, one GOOD sample, missed/stale samples, dwell excursion, pause, clock adjustment, repeat overflow, stalled step | Virtual-clock state/elapsed assertions; finite watchdogs and no fabricated completed dwell |
| Crash + data | kill before/after create/start/append/finalize, full disk, folder denied, partial CSV, bad ZIP | Reconcile as INTERRUPTED/FAULT with verifiable sample sequence; no fabricated data and no unsafe auto-restart |
| Multi-client/auth | two tabs race for lease, unknown old owner, viewer write attempt, offline first-run, expired session | At most one command owner; audited denial; authorized STOP independent of lease |
| Scale + UX | 100k/1M stored samples, slow browser, two viewers, refresh; approved viewport screenshots | Bounded points (<=2000 per chart response), bounded memory/backlog, acquisition independent of clients, usable buttons |
| Launcher + offline | 2 launcher instances, foreign process on port, browser close, logoff, VM with blocked egress and no development runtimes | No second controller; documented process behavior; all pages/assets work with zero internet dependency |
| Migration | N -> N+1 -> rollback with profiles, runs and unfinished CSV | Backup preserved, version checks reject unsafe downgrade, no data loss or silent schema corruption |
| Physical certification | VT4011 commanded/readback temperature, slopes both directions, stop/network fault/power policy | Site-signed HIL report; demonstrated actions and truthful UNKNOWN/FAULT behavior |

## Coverage-to-review traceability

- BLOCKER-01 and HIGH-08: D01, G04, H01.
- BLOCKER-02, HIGH-02, MEDIUM-02: P00, G04, G05, G06, H01.
- BLOCKER-03 and HIGH-07: P00, G05, G06, G08, H01.
- BLOCKER-04 and MEDIUM-01: P00, G03, G05, H01.
- HIGH-01, HIGH-06, HIGH-09, MEDIUM-04: P00, W01, G08, W02.
- HIGH-03: P00, G06.
- HIGH-04 and MEDIUM-06: P00, G03, G07.
- HIGH-05: P00, G07.
- HIGH-10, MEDIUM-03, LOW-02: G01, G02, G07.
- MEDIUM-05: each phase and release checklist.
- MEDIUM-07, LOW-03: G02, W01, W02, R01.
- LOW-01: phase naming in this sequence.

## Go / no-go rules

- **GO now:** P00 review edits, D01 driver test/fix work, G01/G02/G03, W01, fake-device G04/G06 development.
- **CONDITIONAL GO:** any real chamber command requires D01 merged/pinned, site STOP policy, verified identity/envelope, single-owner controller and authorized access.
- **NO-GO:** enabling hardware gradients until HIL proves units/ranges; physical-control release before BLOCKER-01..04 and H01; LAN mutation before G08; legacy retirement before both H01 and W02.
