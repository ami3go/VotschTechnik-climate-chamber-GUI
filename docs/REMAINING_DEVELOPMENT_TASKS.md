# Climate Chamber GUI — Remaining Development and Production Readiness Plan

**Revision:** 1.0  
**Latest execution/status plan:** [Current Action Plan — 2026-10-18](CURRENT_ACTION_PLAN_2026-10-18.md)  
**Baseline date:** 2026-10-18  
**Overall state:** Core NiceGUI software integrated; physical profile execution and production release **NO-GO**  
**GUI repository:** https://github.com/ami3go/VotschTechnik-climate-chamber-GUI  
**External driver:** https://github.com/ami3go/VotschTechnik-climate-chamber-Python  
**Inspected GUI main:** d38506a27fb2bd39f81b8e6d1823638b8b1e81fa  
**Inspected driver main:** 9323e3701f3befedcc23b45170a851fd327f0bcc

> This is an engineering work plan, not site authorization or a production certification. The statuses below describe remaining acceptance gates as of the stated baseline; check fresh GitHub state before changing code. Historical audits remain historical rather than authorization to operate equipment.

## 1. Objective and system boundaries

Finish the remaining software integration, independent watchdog supervision, hardware/safety verification, operational security, offline Windows packaging and final release acceptance for **one** Vötsch environmental chamber. Implement incrementally using existing architecture rather than creating parallel controllers, schedulers, authentication authorities or vendor protocol stacks.

- **NiceGUI** is the only supported web UI, with the Python package in the repository root.
- **G03** owns immutable profile revisions; **G04** alone serializes/fences chamber I/O and STOP; **G06** alone schedules profiles; **G07** owns durable run evidence; **G08** authorizes and audits all mutations.
- Vötsch-specific I/O resides exclusively in the maintained external Python driver, called through VotschBackend; the generic GUI and service layers never compose raw S!MPAC commands.
- Default operation is simulation. Existing supervised manual HIL is opt-in but **not** blanket authorization for physical profiles, auxiliary outputs, gradients, or hazardous fault injection.
- All hardware actions require exact, independently signed site authorization for their scope, approved physical STOP procedures and a named on-site operator/witness as required.
- A software/web STOP is not an emergency stop. UNKNOWN is not STOPPED. No automatic physical command replay or resume after crash or uncertain state.
- CI or a software PR merge never constitutes site physical acceptance or an offline production release.

## 2. Current GitHub baseline

| Area | Implemented foundation | Still open |
|---|---|---|
| G01–G04 | Vendor-neutral backend, profiles, persisted editor, G04 controller | Physical deployment acceptance |
| G05/G06 | Manual control, simulated runner and browser profile execution | Physical G06 profile run |
| G07 | RunRecorder, SQLite journal, recovery and exports | Operational evidence/History authorization and physical G07 composition |
| G08 | Security profiles, credentials, local reset and audit | Independent LAN/Windows/security acceptance |
| H01 | Simulated browser/HIL tests; supervised manual HIL and soak test code/evidence | Signed site acceptance and outstanding physical matrix |
| H02 #39 | Signed *preflight validator* and development-command watchdog | Live G06/G07 integration, independent physical supervisor, authorized physical test |
| H03 | Profile v2 output/run-state directives tested in simulation (#38) | Typed driver capability approval, physical outputs/gradients and shutdown policy |
| W02 #30 | Signed inventory/verifier candidate and Windows frozen simulator | Hash-locked air-gap release, install/upgrade/rollback, clean-VM QA |
| R01 | Not approved | Final release evidence, signatures and GO decision |

The GUI had no open pull requests or issues at the baseline. The driver had an old unrelated open PR #1; do not confuse it with new feature work. Always refresh status at implementation time.

## 3. Master task table and proposed order

| ID | Priority | Scope | Prerequisites | Result / gate |
|---|---|---|---|---|
| DOC-01 | P1 | Reconcile tracker, README and readiness ledger | None | Single current authoritative work queue |
| T01 | P0 quality | Full test isolation and combined browser/fault regression | Current main | Stable CI on exact head |
| H02-B | P0 critical | Physical-profile G06/G04/G07/G08 runtime composition | H02 #39; approved architecture | Fail-closed software implementation, no unauthorized physical I/O |
| H02-C | P0 safety | Independent physical watchdog and STOP supervision | H02-B contracts | Watchdog fault matrix and independent review |
| H03-A | P1 | Typed external-driver outputs and gradient capability APIs | Driver API review | Driver+GUI tested integration |
| H03-B | P0 safety | Baseline/shutdown/restoration policies and G06/G07 integration | H03-A + site policy | Safe simulated dispositions; physical writes gated |
| G07-B | P1 | Authenticated History/Logs and evidence fidelity | G07/G08 | Audit-protected verified export workflows |
| W02-B | P1 release | Signed reproducible offline dependency/artifact pipeline | W02 #30 | Trusted independently verified bundle |
| W02-C | P1 release | Windows supervision, backup, migration and rollback | W02-B | Clean-VM lifecycle/recovery evidence |
| G08-OPS | P1 release | LAN, identity, audit and operational security certification | G08 + W02 | Independent security acceptance |
| H01-A | P0 release | Signed site HIL and scope-specific hardware acceptance | H02/H03 safety gates | Witnessed evidence + site signatures |
| R01 | P0 final | Production cutover and release | All applicable gates | Signed GO/NO-GO release |

Tasks are independently branchable when file ownership and contracts do not conflict. Do not combine H02 and H03 physical activation in a single unrestricted feature switch. W02-B, T01 and DOC-01 can proceed independently from H02-B; H03-A may proceed on the driver API while H02-C is developed.

---

## 4. DOC-01 — Current readiness ledger and documentation synchronization

**Priority:** P1; **branch:** docs/current-readiness-and-remaining-work; **hardware:** none.

1. Fetch current GUI and driver main, merged PRs and CI. Preserve exact inspected SHAs and links.
2. Update documentation whose headings still call merged PRs #27–#30 drafts or describe H01 physical I/O as categorically absent.
3. Reconcile docs/DEVELOPMENT_SEQUENCE.md, docs/READINESS_FINDINGS.md, docs/G08_REMAINING_WORK.md, docs/W02_OFFLINE_RELEASE.md, docs/H02_PROFILE_VERIFICATION_PLAN.md and README_WEB.md; retain dated historical evidence in separate sections.
4. Publish separate states for **implemented**, **tested in simulation**, **tested on physical hardware**, **independently approved**, and **certified for release**.
5. Maintain an ID-based BLOCKER/HIGH findings ledger with risk, owner, dependencies, verification evidence, signoff and closure status.

**Acceptance:** Accurate current PR states; no false physical certification; all major remaining milestones and release blockers cross-linked from README. No runtime changes.

## 5. T01 — Stable combined test suite and fault-injection coverage

**Priority:** P0 quality; **branch:** test/combined-nicegui-hil-regressions; **hardware:** prohibited in CI.

1. Reproduce and fix NiceGUI route-registration/import-order isolation, port contention, process teardown, event-loop and app-reload issues. Preserve the #50 user-simulation timing fix without relying solely on sleeps.
2. Use per-test temporary HOME/user-data directories, SQLite stores, lease locks and browser state; prove independent and combined test order.
3. Extend G03 profile revision, G04 STOP/generation, G05 operator leases, G06 one/multistep/pause/resume, G07 recording/restart, G08 three security profiles and credential reset, and H01 browser paths.
4. Add security regressions for factory password/PIN restrictions before LAN startup, server-local factory reset, stale sessions, CSRF, Origin, unauthorized exports and concurrent browsers.
5. Add H02 permit rejection, H02 simulated watchdog expiry and H03 denied physical output/gradient cases.
6. Exercise actual Chromium, Python 3.10/3.12, Windows/Linux, and frozen Windows simulator; use deterministic virtual time where possible.

**Acceptance:** No order-dependent 404s, fixed-port leaks, or flaky browser redirects; bounded test execution; archived failure artifacts; zero real hardware I/O in CI. Record counts and exact-head workflow URLs.

## 6. H02-B — Physical-profile runtime integration

**Priority:** P0 critical; **branch:** feat/h02-b-physical-profile-runtime; **depends on:** H02 #39, G04/G05/G06/G07/G08; **physical tests:** no execution without new signed H02 permit.

Current H02 contains an Ed25519 signed preflight validator and a subprocess test watchdog, **not** production hardware profile execution. G06 currently rejects non-simulated devices.

### Implementation
1. Inspect chamber_web/services/profile_execution.py, chamber_web/execution/profile_runner.py, chamber_web/services/chamber_controller.py, chamber_web/persistence/runs.py, chamber_web/hil/profile_admission.py and the existing composition root.
2. Wire the existing single ProfileRunner/RunRecorder/AuthorizedChamber through the application composition root. Never instantiate a second controller or duplicate a vendor driver interface.
3. Initialize and exclusively reconcile G07 durable recording before accepting a run. On unavailable storage, fail before mutation.
4. Bind H02 signed permit fields to *server-derived* G04 identity, immutable G03 profile checksum, actual pinned GUI/driver revisions, G08 actor, witnessed site scope, watchdog approval, safe initial readback and live owner/generation; never trust browser-supplied admission booleans.
5. Implement an explicit narrowly-scoped supervised physical run path. Keep default simulated behavior and prohibit unapproved output/gradient directives.
6. Verify ramp-aware setpoint convergence (the VT4011's observed setpoint may be mid-ramp), fresh GOOD telemetry, monotonically bounded reach/stabilization/dwell/repeats, cancellation and STOP fencing. PAUSE must not reset absolute deadlines.
7. Persist immutable PREPARED, START_INTENT, SETPOINT_INTENT, each state/sample/observed-setpoint and controller generation, STOP_INTENT and terminal outcome. Commit mutation intents *before* dispatch; separate intended vs independently observed values.
8. On write uncertainty, recorder failure, identity mismatch, expired authorization, G04 generation change or blocked operation, stop further dispatch, request the approved bounded STOP path, and retain UNKNOWN until independently verified.
9. Expose authorized supervised run status via existing NiceGUI Profile card, without a general hardware activation toggle; show simulation/physical state unambiguously.

### Tests
- One/multi-step and repetition; time-bound reach/stabilization/dwell; simulated ramp readback.
- START and STOP intent durability; crash after START_INTENT or STOP_INTENT; no automatic replay.
- Manual-vs-profile ownership, role revocation, simultaneous browsers, invalid/expired/wrong-device signed permits.
- ENOSPC, SQLite corruption, event-sink failure and lost/fault telemetry; G07 verified evidence exports.
- Browser refresh/reconnect, bounded Chromium tests, Windows/Linux runner integration and frozen simulator.

**Acceptance:** Full simulation-only integration green; exact identity and permit preflight fail closed; durable intents before commands; no physical tests without H02-specific signed site authorization; independent review of any physical enablement.

## 7. H02-C — Independent physical watchdog

**Priority:** P0 safety blocker; **branch:** feat/h02-c-independent-watchdog; **depends on:** H02-B service contracts.

The existing scripts/h02_watchdog_command.py supervises development/test processes. It is **not** a physical safety watchdog.

### Implementation
1. Design a separately supervised monitor with authenticated, bounded app/monitor heartbeat. It must not become an independent uncoordinated chamber controller.
2. Monitor approved run deadline, G04 generation and exclusive ownership, correct chamber identity, G07 journal liveness, device alarms, fresh telemetry and site temperature envelope.
3. Define fail-closed actions for heartbeat loss, app freeze, blocked G04, recorder failure, stale readback, unexpected identity/state and STOP verification timeout.
4. On expiry: synchronously inhibit further profile dispatch, persist abort intent when possible, request *one* approved prioritized G04 STOP when callable, bound fresh STOP verification and retain UNKNOWN on uncertainty. Preserve operator alert/evidence/restart latch.
5. Document limitation: software cannot guarantee chamber STOP after power/OS/network/driver failure; physical local emergency procedures remain mandatory.
6. Use signed site-approved finite timeouts, not universal physical safety constants.

**Tests:** Simulated heartbeat loss both directions, blocked I/O, missed STOP, unknown readback, recorder failure, simultaneous cancellation, process kill/restart, stale permit and complete cleanup with no extra writes.

**Acceptance:** Independent security/safety review; all fault matrices deterministic; no silent continuation or false STOPPED state. Physical activation blocked until independently approved.

## 8. H03-A — Typed external driver output and gradient support

**Priority:** P1; **branches:** feat/h03-driver-output-api (driver) and feat/h03-output-capabilities (GUI).

1. Inspect external VotschTechnikClimateChamber/ClimateChamber.py typed dryer, compressed_air, gradient_up/down properties and raw digital-output query behavior; verify actual OEM/firmware capabilities before claiming physical support.
2. Add safe typed numbered-output APIs to **external driver** where necessary, with strictly bounded IDs, boolean states, no unsupported writes, deterministic readback and mocked transport/fault tests.
3. Keep Vötsch protocol completely inside external driver. GUI's VotschBackend delegates instead of composing new vendor command strings.
4. Extend generic capability advertisement for installed/verified output numbers and gradient direction, units, limits and fresh readback; never infer all 64 outputs are physically installed.
5. Preserve v1/v2 profile CSV/ZIP compatibility and reserved mappings (chamber run = 1, compressed air = 7, dryer = 8) unless authoritative model documentation proves otherwise.
6. Review driver and GUI PRs separately, pin the verified driver commit and rerun Windows/Linux conformance, mock/failure and regression tests.

**Acceptance:** Typed driver abstraction, vendor-neutral GUI service, accurate capability discovery, explicit UnsupportedCapability, no enabled physical output by default.

## 9. H03-B — Output baseline, shutdown policy and gradient restoration

**Priority:** P0 safety gate; **branch:** feat/h03-safe-output-restoration; **depends on:** H03-A + signed site policy.

1. Establish an approved output mapping/safe-state policy specific to model, firmware, installed wiring and specimen. **OFF is not presumed safe** for compressed air, dryer or numbered outputs.
2. Read and durably snapshot the initial verified running state, output values, gradient settings, measured temperature, setpoint, G04 generation, actor and chamber identity before any mutation.
3. For each approved mutation: validate site permit and G08, persist OUTPUT_INTENT/GRADIENT_INTENT, call only G04, verify authoritative state/gradient readback and commit observed result to G07.
4. Separate physical setpoint-readback ramp from programmable gradient_up/down mutation. Obtain independently approved units/ranges before enabling setters.
5. Define explicit normal completion, cancellation, STOP, FAULT, UNKNOWN, reboot and disconnect dispositions: preserve, restore verified baseline, or apply a site-approved safe state. Enforce G04 STOP priority; no post-STOP writes outside a separately approved safe restoration procedure.
6. Handle interrupted output sequence/readback mismatch, denied restoration, G07 storage failure and crash without fabricated success or automatic command replay.
7. Update preflight and NiceGUI to reject unapproved output/gradient requests *before* any physical dispatch, and clearly show intended vs observed state.

**Tests:** Simulated output 7/8 and numbered capabilities, range/type and reservation checks, baseline missing, STOP during mutation, partial sequence, malformed readback, gradient up/down unit/range, lost baseline, missing approval, restore failure and watchdog expiry.

**Acceptance:** Complete simulation and browser evidence; explicit signed physical output shutdown policy required for any future H03 physical test; UNKNOWN remains locked pending operator reconciliation.

## 10. G07-B — Authenticated run history, exports and evidence fidelity

**Priority:** P1; **branch:** feat/g07-b-secure-run-history; **depends on:** G07 and G08.

1. Audit current History/Logs/Results page behavior and wire any missing server-authorized RunStore service routes.
2. Provide bounded run filtering, immutable revision identity, raw measured temperature, intended target and **independently observed** setpoint when available, chronological step/state/STOP/fault event timeline.
3. Enforce G08 role, session, Origin/CSRF where relevant, per-run/chamber authorization, audit logging, validation and size limits on every read/download route. Direct unguarded evidence-file serving forbidden.
4. Replace naive stride plots with bounded min/max/edge-preserving buckets so brief extrema survive downsampling; verify data/plot fidelity.
5. Verify SHA-256 manifests, reject tampered evidence, recover UNKNOWN honestly; document optional externally anchored integrity/archive and Windows power-loss limitations.
6. Keep export bounded, or implement securely authenticated bounded streaming with cancellation and negative size tests.

**Acceptance:** Chromium workflows for listing/plotting/downloading, authorization and corruption tests; no false completed status.

## 11. W02-B — Reproducible signed offline Windows build

**Priority:** P1 release; **branch:** feat/w02-b-offline-supply-chain; **depends on:** W01/W02 foundation.

1. Produce approved full transitive dependency lock + hashes and disconnected wheelhouse. Reject missing, modified, non-approved or unexpected components.
2. Generate a reviewed frozen-runtime CycloneDX/SPDX SBOM, license inventory and attestable build provenance (current build-environment inventory is provisional).
3. Use approved signing infrastructure/escrow, separately provisioned trust root, verified Ed25519 release manifest, key rotation/revocation procedure and independently protected minimum-version floor.
4. Independently trust frozen target-side verifier/PowerShell 5.1 wrapper; check ZIP traversal, NTFS reparse/casefold aliases, unlisted/missing files, invalid keys/signatures and replay/downgrade attacks.
5. Verify Windows 10/11 x64 isolated clean VMs with Python/Git/Node absent, deny network egress, collect browser HAR, firewall/DNS logs and offline-launch evidence.
6. Do not market unsigned CI artifacts or connected Windows runners as production-signed offline certification.

**Acceptance:** Independent supply-chain review; offline reproducible build inputs; fail-closed verified install candidate; clean-VM evidence or explicit NOT RUN blocker.

## 12. W02-C — Windows lifecycle, migration, backup and rollback

**Priority:** P1 release; **branch:** feat/w02-c-windows-lifecycle; **depends on:** W02-B.

1. Implement/verify process supervision and single-instance ownership, shutdown, browser disconnect, operator logoff, OS restart, crash-uncertainty and Windows service/portable modes.
2. Restrict NTFS ACLs and application/service identity access to G03, G07, G08 data, keys, logs and release trust roots.
3. Pre-upgrade SQLite snapshots for immutable profiles, G07 run journal/evidence and G08 identity/audit; validate schema, quick_check, manifests, retention and restore permissions.
4. Provide transactional staged binary version switch, migration checkpoints and verified rollback matching original data versions.
5. Test interrupted upgrade, corrupted backup, downgraded schema, loss of network, shutdown during active simulated run and stale-session revocation.
6. Never restart/replay hardware profile commands automatically after interrupted upgrade or reboot.

**Acceptance:** Clean Windows 10/11 offline lifecycle and recovery matrix, documented operator runbooks and independent review.

## 13. G08-OPS — Operational security acceptance

**Priority:** P1 release; **depends on:** G08 and W02.

- Validate exact HTTPS/WSS trust, Host/Origin, DNS rebinding, client CIDR allow-lists, firewall and browser/WebSocket session revocation on real deployed LAN configurations.
- Verify General, Isolated LAN PIN/no-expiry and Large Network policies, audit and authentication even for lease-independent STOP; no unguarded browser/server endpoints.
- Test local-console credential recovery and factory administrator reset, persistent changes, hashing, audit, session revocation and no web recovery route.
- Enforce changing both factory password and PIN prior to network deployment.
- Review NTFS/private-key access, protected external audit anchoring, backup rollback, signing key escrow/rotation, capacity/retention and recovery after corruption.
- Obtain independent qualified security assessment and record accepted residual risks.

**Acceptance:** No unaccepted HIGH/BLOCKER deployment security issue; clear approved policy for loopback, isolated LAN and larger network.

## 14. H01-A — Formal hardware/site acceptance

**Priority:** P0 release; **physical permission:** separately signed procedure for EACH scope.

1. Identify chamber/model/serial/firmware, manual revision, installed hardware/output mappings, calibrated reference, local STOP and emergency procedures, permitted specimen and temperature/gradient envelopes.
2. Record exact deployed GUI/driver revisions, operator/witness, physical instrument readings, signed site test plan, permitted duration and watchdog/STOP conditions.
3. Review prior H01 supervised manual HIL and soak evidence as engineering data, not blanket signoff.
4. Separately authorize H02 physical profile tests, H03 auxiliary/gradient mutations and any intrusive process/network/power fault injection. Do not infer authorization from existing CHAMBER_HIL_* variables or signed software preflight.
5. When authorized, run short witnessed approved tests with independently verified precondition, readback, STOP and restored baseline, G07 manifest hashes and deviations.
6. Record PASS, FAIL or NOT RUN honestly; do not claim production GO without signatures from responsible site authority.

**Acceptance:** Signed acceptance matrix with raw evidence and independent approval; all unexecuted scopes remain NO-GO.

## 15. R01 — Production release and cutover

**Priority:** Final gate; **depends on:** applicable software, security, W02 and signed H01/H02/H03 approvals.

- Freeze exact main SHAs, pinned driver, dependency hashes and signed artifacts.
- Approve released configuration and operating envelope; produce release notes, administrator/operator manuals, emergency/STOP procedure, backups/restore and upgrade/rollback guide.
- Complete final Windows offline, multi-browser, security, hardware and G07 evidence acceptance.
- Record all BLOCKER/HIGH findings closed or explicitly approved by appropriate authority (no unresolved unaccepted safety block).
- Obtain site and release-owner signatures and issue a formal GO/NO-GO decision.
- Tag/release only accepted software; retain validated existing installation and tested rollback path until production cutover is approved.

**Acceptance:** Exact source/artifact traceability, independent signoff, no false physical certification, documented operational readiness.

---

## 16. Mandatory watchdog and long-task discipline

**Reuse** scripts/h02_watchdog_command.py for long-running development/CI subprocesses. Do not create a duplicate process watchdog. For each operation over approximately one minute:

1. Declare objective, exit criteria, **finite** overall timeout, idle/heartbeat timeout and bounded cleanup.
2. Track child PID/group; capture timestamped stdout/stderr, heartbeats, and summary/exit code.
3. On stalled output/lost heartbeat, terminate the *owned* process tree; preserve partial evidence; TIMEOUT/NO_OUTPUT is never PASS.
4. Separate test groups when a single suite risks unbounded runtime; use bounded polling for GitHub CI; never leave unattended physical operations running in another task.
5. Example development-only command (timeouts are **not** approved physical safety limits):

        python scripts/h02_watchdog_command.py --timeout-s 180 --idle-timeout-s 75 --cleanup-s 5 --log-dir test-evidence/h02 -- python -m pytest -q tests/test_h02_profile_admission.py

6. Independently reviewed *physical* watchdog limits come from a signed site test procedure. A development subprocess watchdog is not an equipment emergency stop.

## 17. PR implementation and review rules

For each task:

1. Re-fetch exact GUI/driver main and open PRs; inspect existing code and avoid duplication.
2. Use one focused branch/PR per milestone (and a separate driver PR when changing the external driver).
3. Keep code/package in repository root without a src/ layout, and preserve manufacturer protocol isolation.
4. Implement in bounded stages, use watchdogs, run Linux/Windows Python 3.10/3.12 and real Chromium where applicable.
5. Perform an independent technical/code review; an AI-assisted self-review is **not** a human/site authorization.
6. Fix every BLOCKER/HIGH **software** finding or document the non-software release gate. Never suppress failing CI or force-merge.
7. Push branch, create PR, verify exact final-head checks, request required approvals, merge only if policy permits.
8. Verify merged main CI, record merge SHA, evidence and updated readiness ledger.
9. Physical activation remains a separate signed decision regardless of software PR merge.

## 18. Required acceptance/evidence report

| Field | Evidence |
|---|---|
| Task ID, scope and objective | Exact specification and excluded physical scope |
| Base GUI / driver SHAs | Inspected and pinned versions |
| PR links and final tested SHAs | Actual GitHub references |
| Changed code/interfaces | Architecture impact and external driver delegation |
| Tests and platforms | Counts, PASS/FAIL/SKIPPED, Windows/Linux and browser |
| CI run URLs | Exact final-head GitHub Actions results |
| Watchdog logs | Timeouts, heartbeat losses and cleanup proof |
| Review and findings | Independent reviewer/status; accepted residual risks |
| Physical HIL | Explicit authorization and PASS/FAIL/NOT RUN |
| Run evidence and STOP | Original intent, readback, manifest, uncertainty and physical witness |
| Merge / release | Merge SHA and distinct operational GO/NO-GO |

### Release decision

**Software core functional. Physical G06 profile execution: NO-GO. Physical profile v2 auxiliary/gradient writes: NO-GO. Certified offline Windows distribution: NO-GO. Production release: NO-GO** until their distinct engineering, independent review and signed site acceptance gates have passed.
