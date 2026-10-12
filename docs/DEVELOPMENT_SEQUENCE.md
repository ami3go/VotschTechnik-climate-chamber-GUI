# NiceGUI migration — implementation and merge sequence

Status: PROPOSED / NOT STARTED. This is the execution plan for [WEB_GUI_MIGRATION_PLAN.md](WEB_GUI_MIGRATION_PLAN.md), revised after the 2026-10-12 independent technical review. Phase IDs are **not** GitHub PR numbers. Each delivery unit must have its own PR and review; driver work belongs exclusively to [VotschTechnik-climate-chamber-Python](https://github.com/ami3go/VotschTechnik-climate-chamber-Python).

## Non-negotiable boundaries

- NiceGUI web application; Python package in the GUI repository root (no src/ directory); preserve only the useful visual/layout aspects of the earlier single-file screenshot prototype. No prototype simulator/state machine in production control.
- Generic NiceGUI pages, application services, profile runner, CSV and controller depend only on the typed `ChamberBackend` abstraction and normalized DTOs. For Vötsch chambers, `VotschBackend` alone imports the existing external `VotschTechnikClimateChamber` driver. Future chamber brands require new adapters + their own maintained external driver; no low-level hardware protocol or manufacturer branching in generic GUI. Required contract: [CHAMBER_ABSTRACTION_CONTRACT.md](CHAMBER_ABSTRACTION_CONTRACT.md).
- v1 requires capability-driven controls, explicit backend registry and Vötsch/Fake/second-vendor-stub conformance **in separate one-device test instances**, and a generic `ChamberController(chamber_id)`/manager API. **Enforce at most one configured physical chamber and one live controller per application deployment.** Multi-chamber orchestration, simultaneous multi-device runs and chamber selector are deferred to [FUTURE_MULTI_CHAMBER_ARCHITECTURE.md](FUTURE_MULTI_CHAMBER_ARCHITECTURE.md).
- Server owns chamber state and profile execution independently of browser clients. Exactly one command owner per chamber and single authoritative server process; operator ownership does not obstruct an authorized STOP.
- NO physical-device release until BLOCKER-01 through BLOCKER-04, site safety approval and the chamber-in-the-loop (HIL) gate pass. Driver reliability fixes must land in the driver repository and the GUI must pin the tested driver revision.
- Local physical emergency stop/manufacturer protections remain necessary. Web STOP is an attempted control command, not a certified emergency stop. A disconnected chamber cannot be asserted stopped.
- Keep legacy Tkinter and historical releases usable until an explicitly approved cutover. Do not merge unreleased simulated/frozen builds as evidence of HIL certification.

## Workstreams and prerequisites

- **A — Specification and driver:** P00, D01. Hardware controller acceptance requires both.
- **B — Foundation/UI/data:** G01 introduces vendor-neutral contract/registry, stable `chamber_id`, one-device cardinality guard and minimal manager interface; G02/G03 use these with a single-chamber GUI. Second-vendor stub tests are sequential. D01 proceeds independently.
- **C — Early packaging:** W01 begins immediately after G01 (not at the end); keep both required PowerShell build scripts passing through development.
- **D — Control/run engine:** G04 can be developed against fake driver; G05 requires D01 + site-accepted safety policy before enabling physical control; G06–G08 follow tested interfaces.
- **E — Security/certification/cutover:** G08-min authentication/authorization/origin protections MUST gate **any** real-device mutation, including loopback HIL; full G08 is required before general-use/LAN control; H01 and W02 precede R01 and desktop retirement. Far-future MC01–MC05 are NOT v1 prerequisites.

## Ordered delivery units

| ID | Target repository | Task / deliverables | Depends on | Required completion evidence |
|---|---|---|---|---|
| P00 | GUI | Define safety/STOP/fault, profile timing/ownership/persistence/offline bootstrap, typed backend and **future-ready `chamber_id` model with strict one-physical-chamber v1 cardinality** | None | Approve [abstraction](CHAMBER_ABSTRACTION_CONTRACT.md) and [future fleet boundary](FUTURE_MULTI_CHAMBER_ARCHITECTURE.md); record unresolved site decisions and review blockers |
| D01 | Driver | Separate backward-compatible driver PR(s): finite connect timeout, socket cleanup, verified full send/framing, bounded read, type/finite/limit validation, start/stop/error semantics; mocked network tests | P00 safety/interface contract | Refused/blackhole/split-frame/failure tests; driver version/tag or immutable commit pinned in GUI before hardware integration |
| G01 | GUI | NiceGUI root package, typed ChamberBackend/DTOs/registry, Vötsch/Fake/second-vendor-stub conformance, stable `chamber_id`, **single-device ChamberManager interface**, versioned single-device configuration and fail-closed physical device count guard | P00 | Config with 2 physical chambers fails BEFORE connection; unknown/wrong ID rejected; three backends tested separately; static import boundary passes |
| G02 | GUI | Single-chamber NiceGUI shell/pages, generic status/STOP and capability-driven controls, approved branding; no selector, fleet cards or global multi-device commands | G01 | Same one-device Dashboard/Profiles/History/Logs/Settings tests pass sequentially for Fake, Vötsch-mock and second manufacturer stub; accessible single-device UI |
| G03 | GUI | Vendor-neutral profile schema, immutable revisions, AG Grid, SQLite + versioned `chamber_id` keys, namespaced run files, profile CSV/ZIP and compatibility validation | G01, P00 | No hard-coded chamber-1 or vendor command IDs; globally unique run IDs, persistent per-device metadata; sequential fixture A/B isolation and migration tests |
| W01 | GUI | Early Windows launcher and offline scripts with working freeze, complete installed adapter registry, dependencies, backend factory loading, manifest and clean-Windows smoke | G01 | Both scripts run; frozen Fake/second stub load without Python/internet; Vötsch external driver is explicitly packaged for actual release and never imported by generic UI |
| G04 | GUI | Generic `ChamberController(chamber_id)` behind **one-active-controller manager**, adapter I/O, process lock/transactional per-ID lease, STOP fencing, readback/polling and normalized errors; reject second physical device | G01, P00; D01 for live device | One-device mock faults and alternate-backend substitution; second physical config rejected pre-connect; stale/wrong ID never dispatches; no later setpoints after STOP |
| G08-min | GUI | Offline admin bootstrap, authenticated session, server-side roles on all hardware mutations, CSRF/origin protections and mutation audit for loopback/LAN; no production access yet | G01, G04 | Two-user and viewer-denial tests; unauthenticated local request cannot write hardware; audited authorized STOP independent of lease |\n| G05 | GUI | Manual target/presets/start/stop through controller/backend only, identity and certified capabilities, safe limits, handover and settings snapshot. Unsupported controls disabled; gradients HIL-gated | G04, G08-min, D01 + signed physical STOP policy for live commands | VT4011 parity; second stub with alternate range/no ramps disables unsupported actions without code changes; verified start/stop readback |
| G06 | GUI | Vendor-neutral ONE-device cancellable profile runner with monotonic deadlines/stabilization/dwell/abort, immutable execution snapshot with chamber/backend/capabilities | G03, G04, P00 timing/safety | Virtual-clock tests run separately for Fake and second-vendor stub; one active run maximum; no model-specific branches or multi-device scheduler |
| G07 | GUI | Vendor-neutral per-`chamber_id` sample/event CSV, atomic manifests, crash reconciliation, history, plots and downloads | G06, G03 | Immutable chamber/backend/driver metadata and namespaced storage, wrong-device association prohibited, partial-run recovery and 1M samples |
| G08 | GUI | Complete security/ops: encrypted transport for LAN, account recovery, rate limits, audit retention, update/backup policy, service supervision/logoff/shutdown behavior | G08-min, G04, P00 lifecycle/security contract; parallelizable before hardware release | Air-gapped bootstrap/password recovery, two-user conflict, viewer denial, session expiry, service restart and logout tests |
| H01 | Driver + GUI | **Single** approved VT4011 HIL through Vötsch adapter/driver, certified gradients, readbacks/STOP/faults, operator conflict; separate architecture conformance for alternative test adapter | D01, G05–G08, site signoff | Site-signed VT4011 report and different-vendor stub substitution; no simultaneous multi-device HIL required for v1 |
| W02 | GUI | Final Windows launcher/complete offline ZIP, registered adapter/vendor dependency freeze, data migration/rollback, Win10/11 x64 and clean disconnected VM | W01, G02–G08 | Installer/ZIP contains Vötsch and Fake backends, registry works offline, no runtime remote plugins/downloads; full app and data preserved |
| R01 | GUI | Release checklist: documentation, packaging, manuals, formal parity signoff, security/hardware/offline evidence, tagged release; retire old UI only after approval | H01 + W02 + all release gates | Signed GO decision, updated README, recoverable legacy release, no unreviewed main deletions |

P00 and D01 are the **critical path for physical operation**, but they must not block G01/G02/G03/W01 simulated/UI development. G08-min is mandatory **before any physical device mutation even on localhost**; full G08 precedes operational LAN release and may develop alongside G05–G07. W01 is an early feasibility gate, W02 is final offline certification.

## Required design-review artifacts at P00

1. **Safety response matrix** for normal completion, explicit operator STOP, command timeout/ambiguous acknowledgement, communication loss, out-of-safe-envelope measured temperature, loss of logging/disk space, app crash, Windows logout/shutdown, loss/return of power, hardware alarms. For each: requested action, bounded attempt strategy, what can/cannot be verified, fault latch, local intervention. Default STOP on operator abort; HOLD_SETPOINT disabled until specifically approved. NEVER claim return-to-ambient is inherently safe.
2. **Capability records and vendor-agnostic boundary:** typed ChamberBackend, stable `chamber_id`, identity/capability/status/error DTOs, normalized units, allowlisted adapters, certified model envelope and gradient support. Second-vendor stub runs in a separate one-device fixture; v1 rejects two physical chambers. Future multi-device expansion is separately specified in [FUTURE_MULTI_CHAMBER_ARCHITECTURE.md](FUTURE_MULTI_CHAMBER_ARCHITECTURE.md).
3. **Command contract** listing driver-only methods, timeout and retry policy, state transitions, ambiguous-command policy and cancellation/fencing. On STOP intent: atomically latch stop generation, refuse new control commands, invalidate queued old-generation work; an in-flight call is not preemptible unless the driver transport truly supports it; attempt STOP/readback with bounded deadlines, return UNKNOWN/FAULT when unverifiable.
4. **Ownership contract**: device-ID-scoped OS lock and SQLite transaction/lease/generation with **one active physical controller in v1**. Startup reconciles unfinished runs and never auto-resumes/replays; every hardware write verifies its requested `chamber_id` and fencing token. Attempting to connect a second physical chamber fails before device I/O. Future multi-controller isolation/concurrency is not v1 scope.
5. **Profile-time contract**: all intervals use monotonic clock; band inclusive; only GOOD fresh observations contribute; stability requires at least two valid observations spanning configured stable time and no stale/gap/out-of-band observations; a gap resets stability, dwell stops accumulating during gaps/excursions; PAUSE freezes transition/dwell but not safety and absolute watchdog. Set bounded reach/stabilize/dwell and absolute step/run deadlines, including across pause (unless separately signed exception). Observation cadence cannot prove between-sample temperature; label as observed stability.
6. **Data contract**: versioned profile CSV step-only vs canonical ZIP (profile.csv + profile.json), max import size/rows/ZIP expansion/precision, reversible machine CSV and separate spreadsheet-safe export; run CSV sample sequence + quality, per-run manifest, write-order/atomic finish, incomplete markers, ENOSPC policy, quota, snapshot read while active, server-side plot sampling.
7. **Windows lifecycle/security**: supervised server not owned by browser/launcher, explicit service vs portable logoff semantics, authenticated instance discovery and separate process/device health; first-run offline admin setup (loopback), roles, TLS for LAN, OS/browser baseline, signed/integrity-checkable offline updates and schema backup before upgrade.

Do not silently convert PENDING choices to defaults. If site-signoff information is unavailable, implement the simulator/UI contracts and keep physical control disabled.

## PR contract and merge order

- **One cohesive delivery unit per PR**; D01 may be multiple small driver PRs with the same gate, followed by a tagged or commit-pinned driver update in the GUI repository. PR ID labels in this document are not GitHub numbers.
- Each PR description includes scope, dependencies, source/driver versions, public contract compatibility, changed adapter capabilities, acceptance checklist, test scope, rollback and migration. No vendor-specific imports in NiceGUI/services/controller/runner/persistence; static dependency enforcement must pass in CI.
- Required checks: Ruff/lint, typing, Python unit tests, fake-driver and **all adapter conformance/alternate-backend tests**, architecture import-boundary enforcement and browser tests. W01/W02 additionally require Windows/offline VM; H01 requires physical site signoff.
- **Review before merge** by an independent requirements/code reviewer; fix BLOCKER/HIGH findings and rerun tests. Do not merge red CI, security regressions, incomplete STOP fencing, or unverified physical safety claims.
- Merge in dependency order. Never enable physical control using an unpinned/unhardened driver. Pin driver/library dependencies and record a manifest. HIL and air-gap gates are independent and both mandatory.
- After each merged PR verify next-phase prerequisites and update task status/evidence links here; final release only after R01 signoff.

## Mandatory cross-cutting acceptance tests

| Concern | Deterministic test | Minimum pass condition |
|---|---|---|
| Adapter dependency isolation | scan AST/import graph for pages/services/execution/persistence/controller and adapter-specific imports | No manufacturer driver/protocol import outside dedicated adapter; new second-manufacturer stub needs no changes to generic source |
| Capability-driven UI/profile | Fake and second vendor stub differ in max/min, gradients, state/error mappings, capabilities | Same generic UI/runner and schema; unsupported control not shown/run; normalized snapshot+ERROR/UNKNOWN; fail closed |
| Single-device configuration / future isolation seam | Attempt to configure 2 physical chamber instances and issue commands with wrong/stale ID; run separate one-device fixtures A/B using different adapters | 2-device config rejected before I/O, no wrong-ID dispatch, A/B histories isolated by chamber_id and namespace; **no simultaneous multi-device execution tested/claimed** |
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

The canonical reviewed issue IDs, owners, status and closure evidence are in [READINESS_FINDINGS.md](READINESS_FINDINGS.md). Previously used labels `BLOCKER-01`–`HIGH-10` lacked a committed definition and are **retired**, not silently assumed equivalent to this review.

- B1/H1: driver D01; transport and numeric tests; hardware certification H01.
- B2: driver D01, G04 STOP fencing and H01 site readback/STOP.
- B3: P00 site-signed model/firmware, safety and gradient envelope; H01.
- B4: G01–G08, H01, W01/W02 and R01.
- H2/H3: P00 gradient and virtual-clock contracts, G06 tests, H01 gradients.
- H4: G08-min **before** G05 physical controls and any live HIL.
- H5: this traceability register and PR evidence.
- H6/H7: G03, G07, CSV migration and crash recovery tests.
- H8: CI and pinned dependencies; enforce per-PR independent checks.
- M1/M2: G01 conformance and W01 Windows feasibility, respectively.

## Go / no-go rules

- **GO now:** P00 abstraction review, D01 driver reliability, G01 typed backend contract/registry and 3-adapter conformance, G02/G03 UI/data and W01 early freeze, simulated generic G04/G06 plus G08-min security scaffolding.
- **CONDITIONAL GO:** any Vötsch real chamber command requires D01 merged/pinned, G08-min passed, signed STOP policy, certified identity/envelope and controller ownership; additional vendor control requires its own reviewed maintained driver, new adapter and separate HIL signoff, never bypassing the generic `ChamberBackend` port.
- **NO-GO:** enabling hardware gradients until HIL proves units/ranges; physical-control release before BLOCKER-01..04 and H01; LAN mutation before G08; legacy retirement before both H01 and W02.

## Far-future multi-chamber roadmap (not part of initial implementation)

The architecture reserves stable per-device IDs, controller/manager boundaries, per-ID leases and namespaced data. **Do not implement live multiple-chamber connectivity, a selector, fleet views, concurrent device runs or global fleet STOP in v1.** Multi-device support requires separate reviewed phases MC01–MC05 documented in [FUTURE_MULTI_CHAMBER_ARCHITECTURE.md](FUTURE_MULTI_CHAMBER_ARCHITECTURE.md). Only the one-device cardinality guard, routed identity and schema compatibility are v1 acceptance gates.

## Future chamber onboarding (post-v1)

The acceptance criterion for a new manufacturer is: implement its maintained external driver and one isolated adapter conforming to [the contract](CHAMBER_ABSTRACTION_CONTRACT.md), add a reviewed registry/config entry and capability/safety certification, and pass common conformance/HIL tests. Adding a basic temperature-control vendor must **not** modify existing NiceGUI screens, generic controller/runner, SQLite/CSV formats or auth/ownership logic. Capabilities are discovered and checked, not assumed; unsupported features must be hidden/disabled and the driver must never be silently replaced with Fake.
