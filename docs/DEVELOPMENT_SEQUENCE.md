# NiceGUI migration — implementation and merge sequence

Status: PROPOSED / NOT STARTED. This is the execution plan for [WEB_GUI_MIGRATION_PLAN.md](WEB_GUI_MIGRATION_PLAN.md), revised after the 2026-10-12 independent technical review. Phase IDs are **not** GitHub PR numbers. Each delivery unit must have its own PR and review; driver work belongs exclusively to [VotschTechnik-climate-chamber-Python](https://github.com/ami3go/VotschTechnik-climate-chamber-Python).

## Non-negotiable boundaries

- NiceGUI web application; Python package in the GUI repository root (no src/ directory); preserve only the useful visual/layout aspects of the earlier single-file screenshot prototype. No prototype simulator/state machine in production control.
- Generic NiceGUI pages, application services, profile runner, CSV and controller depend only on the typed `ChamberBackend` abstraction and normalized DTOs. For Vötsch chambers, `VotschBackend` alone imports the existing external `VotschTechnikClimateChamber` driver. Future chamber brands require new adapters + their own maintained external driver; no low-level hardware protocol or manufacturer branching in generic GUI. Required contract: [CHAMBER_ABSTRACTION_CONTRACT.md](CHAMBER_ABSTRACTION_CONTRACT.md).
- v1 requires capability-driven controls, an explicit allowlisted backend registry, conformance tests for Vötsch/Fake and a deliberately different second-manufacturer stub, and one independent controller per chamber_id. A second real vendor driver is NOT required for initial release.
- Server owns chamber state and profile execution independently of browser clients. Exactly one command owner per chamber and single authoritative server process; operator ownership does not obstruct an authorized STOP.
- NO physical-device release until BLOCKER-01 through BLOCKER-04, site safety approval and the chamber-in-the-loop (HIL) gate pass. Driver reliability fixes must land in the driver repository and the GUI must pin the tested driver revision.
- Local physical emergency stop/manufacturer protections remain necessary. Web STOP is an attempted control command, not a certified emergency stop. A disconnected chamber cannot be asserted stopped.
- Keep legacy Tkinter and historical releases usable until an explicitly approved cutover. Do not merge unreleased simulated/frozen builds as evidence of HIL certification.

## Workstreams and prerequisites

- **A — Specification and driver:** P00, D01. Hardware controller acceptance requires both.
- **B — Foundation/UI/data:** G01 first establishes vendor-neutral domain contract/adapter registry and conformance fixtures; G02/G03 must use this only, while D01 proceeds. Simulation must be explicitly labeled.
- **C — Early packaging:** W01 begins immediately after G01 (not at the end); keep both required PowerShell build scripts passing through development.
- **D — Control/run engine:** G04 can be developed against fake driver; G05 requires D01 + site-accepted safety policy before enabling physical control; G06–G08 follow tested interfaces.
- **E — Security/certification/cutover:** G09 is required before LAN control; H01 and W02 precede R01 and desktop retirement.

## Ordered delivery units

| ID | Target repository | Task / deliverables | Depends on | Required completion evidence |
|---|---|---|---|---|
| P00 | GUI | Amend safety/capability/STOP/fault, profile timing, state/fencing, persistence/CSV, OS/lifecycle, offline bootstrap **and stable vendor-neutral `ChamberBackend` contract + adapter rules**; agree generic DTOs and readback requirements | None | Normative [abstraction contract](CHAMBER_ABSTRACTION_CONTRACT.md) approved; four blockers tracked; site decisions PENDING until signed |
| D01 | Driver | Separate backward-compatible driver PR(s): finite connect timeout, socket cleanup, verified full send/framing, bounded read, type/finite/limit validation, start/stop/error semantics; mocked network tests | P00 safety/interface contract | Refused/blackhole/split-frame/failure tests; driver version/tag or immutable commit pinned in GUI before hardware integration |
| G01 | GUI | Foundation: root-level NiceGUI package, typed `ChamberBackend` Protocol and immutable identity/capability/status DTOs, normalized errors/units, explicit allowlisted backend registry, Fake and minimal Vötsch adapter, fake second-manufacturer stub, CI architectural import boundaries, settings/test clock | P00, abstraction contract | Static import boundary rejects vendor driver use outside `adapters/votsch.py`; Fake/second stub pass contract suite; local UI starts without device/network; no raw vendor protocols in generic modules |
| G02 | GUI | NiceGUI shell and responsive pages, generic status/STOP component, capability-driven controls and approved assets; no manufacturer-specific control logic | G01 | Same Dashboard/Profiles/History/Logs/Settings tests pass for Fake, Vötsch-mock and second manufacturer stub with differing capabilities, without editing generic page code |
| G03 | GUI | Vendor-neutral versioned profile schema, immutable revisions, AG Grid workflow, SQLite migration, CSV steps/full-profile ZIP/JSON, capability compatibility validation at save/launch | G01, P00 data/adapter contract | Full schema/CSV roundtrip and revision tests; profiles store no vendor command IDs; unsupported features fail closed for different backend capabilities |
| W01 | GUI | Early Windows launcher and offline scripts with working freeze, complete installed adapter registry, dependencies, backend factory loading, manifest and clean-Windows smoke | G01 | Both scripts run; frozen Fake/second stub load without Python/internet; Vötsch external driver is explicitly packaged for actual release and never imported by generic UI |
| G04 | GUI | Generic per-chamber `ChamberController`, chamber_id manager, sole backend adapter I/O boundary, process lock/transactional lease, STOP fencing, polling, readback and normalized error mapping; Vötsch adapter translates public driver API only | G01, P00; D01 for real hardware | One shared mock conformance/fault suite across backends; second stub substitutes without changes to controller/pages/runner; two configured devices never cross-control; no queued writes after STOP |
| G05 | GUI | Manual target/presets/start/stop through controller/backend only, identity and certified capabilities, safe limits, handover and settings snapshot. Unsupported controls disabled; gradients HIL-gated | G04, D01 + signed physical STOP policy for live commands | VT4011 parity; second stub with alternate range/no ramps disables unsupported actions without code changes; verified start/stop readback |
| G06 | GUI | Vendor-neutral, backend-mediated cancellable profile runner and finite reach/stability/dwell/pause/abort/repeat semantics, immutable execution snapshots with backend ID/capability fingerprint | G03, G04, P00 timing/safety | Virtual-clock timing/fault tests against Fake + second-vendor stub; identical generic runner, strict capability preflight, zero model-specific branching |
| G07 | GUI | Backend-independent append-only sample/event CSV, atomic manifest and crash recovery, history, downsampled charts and downloads | G06, G03 | Include backend_id, chamber_id, adapter/driver version, capabilities snapshot; no vendor protocols in data; recover partial runs and 1M samples |
| G08 | GUI | Security/ops: offline initial-admin bootstrap, roles/leases, TLS/LAN restrictions, action audit, update/backup policy, service supervision/logoff/shutdown behavior | G01, G04, P00 lifecycle/security contract; parallelizable before hardware release | Air-gapped bootstrap/password recovery, two-user conflict, viewer denial, session expiry, service restart and logout tests |
| H01 | Driver + GUI | Physical VT4011 HIL certification using only `VotschBackend` and external driver, gradient units/readbacks, transport faults, STOP/readback, operator conflict, measurement quality plus architecture conformance | D01, G05–G08, site capability/safety signoff | Signed model-specific matrix; second manufacturer stub proves no generic core/UI changes; simulated tests are not substitute for VT4011 certification |
| W02 | GUI | Final Windows launcher/complete offline ZIP, registered adapter/vendor dependency freeze, data migration/rollback, Win10/11 x64 and clean disconnected VM | W01, G02–G08 | Installer/ZIP contains Vötsch and Fake backends, registry works offline, no runtime remote plugins/downloads; full app and data preserved |
| R01 | GUI | Release checklist: documentation, packaging, manuals, formal parity signoff, security/hardware/offline evidence, tagged release; retire old UI only after approval | H01 + W02 + all release gates | Signed GO decision, updated README, recoverable legacy release, no unreviewed main deletions |

P00 and D01 are the **critical path for physical operation**, but they must not block G01/G02/G03/W01 simulated/UI development. G08 security must land before exposing mutation endpoints outside loopback; it may be developed in parallel with G05–G07. W01 is an early feasibility gate, W02 is final offline certification.

## Required design-review artifacts at P00

1. **Safety response matrix** for normal completion, explicit operator STOP, command timeout/ambiguous acknowledgement, communication loss, out-of-safe-envelope measured temperature, loss of logging/disk space, app crash, Windows logout/shutdown, loss/return of power, hardware alarms. For each: requested action, bounded attempt strategy, what can/cannot be verified, fault latch, local intervention. Default STOP on operator abort; HOLD_SETPOINT disabled until specifically approved. NEVER claim return-to-ambient is inherently safe.
2. **Capability records and vendor-agnostic boundary:** typed `ChamberBackend` Protocol, stable identity/capability/status/error DTOs, normalized units, explicit registered adapters. Capabilities keyed by identity/model/controller and verified configuration (envelope, start/stop/readback, gradient support/units/ranges, polling). Until HIL, gradients disabled. Add a second manufacturer STUB adapter with deliberately different limits/features and no production generic code branches; exact [abstraction contract](CHAMBER_ABSTRACTION_CONTRACT.md).
3. **Command contract** listing driver-only methods, timeout and retry policy, state transitions, ambiguous-command policy and cancellation/fencing. On STOP intent: atomically latch stop generation, refuse new control commands, invalidate queued old-generation work; an in-flight call is not preemptible unless the driver transport truly supports it; attempt STOP/readback with bounded deadlines, return UNKNOWN/FAULT when unverifiable.
4. **Ownership contract**: one OS-level server/chamber lock + SQLite transactional lease/generation; startup always inspects incomplete runs, clears no hardware fault automatically, never replays stale commands or auto-resumes a run; every setpoint checks generation immediately before transmission. Manual/profile takeover is never silent; require audited abort/completion before new owner.
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
| Per-chamber isolation | two IDs with independent adapters/leases/STOP/CSV, attempt live backend swap | Cross-device writes impossible; swap during RUNNING/UNKNOWN rejected; run records exact backend/capability fingerprint |
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

- **GO now:** P00 abstraction review, D01 driver reliability, G01 typed backend contract/registry and 3-adapter conformance, G02/G03 UI/data and W01 early freeze, simulated generic G04/G06.
- **CONDITIONAL GO:** any Vötsch real chamber command requires D01 merged/pinned, signed STOP policy, certified identity/envelope and controller ownership; additional vendor control requires its own reviewed maintained driver, new adapter and separate HIL signoff, never bypassing the generic `ChamberBackend` port.
- **NO-GO:** enabling hardware gradients until HIL proves units/ranges; physical-control release before BLOCKER-01..04 and H01; LAN mutation before G08; legacy retirement before both H01 and W02.

## Future chamber onboarding (post-v1)

The acceptance criterion for a new manufacturer is: implement its maintained external driver and one isolated adapter conforming to [the contract](CHAMBER_ABSTRACTION_CONTRACT.md), add a reviewed registry/config entry and capability/safety certification, and pass common conformance/HIL tests. Adding a basic temperature-control vendor must **not** modify existing NiceGUI screens, generic controller/runner, SQLite/CSV formats or auth/ownership logic. Capabilities are discovered and checked, not assumed; unsupported features must be hidden/disabled and the driver must never be silently replaced with Fake.
