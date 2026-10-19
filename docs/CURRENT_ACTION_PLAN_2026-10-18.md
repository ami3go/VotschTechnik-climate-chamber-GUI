# Chamber GUI — Current Status and Detailed Execution Action Plan

**Revision:** 1.0  
**Snapshot:** 2026-10-18, 16:04 Europe/Sofia (repository rechecked during preparation)  
**State:** Core software merged; physical profiles and production deployment **NO-GO**  
**Primary plan:** [REMAINING_DEVELOPMENT_TASKS.md](REMAINING_DEVELOPMENT_TASKS.md)  
**Canonical release blockers:** [READINESS_FINDINGS.md](READINESS_FINDINGS.md)  
**GUI repo:** https://github.com/ami3go/VotschTechnik-climate-chamber-GUI  
**External driver repo:** https://github.com/ami3go/VotschTechnik-climate-chamber-Python  
**Inspected GUI `main`:** `2f63d5896fc83e04f82cd709986b0a45caeda2b1`  
**Inspected driver `main`:** `9323e3701f3befedcc23b45170a851fd327f0bcc`

> **This is an execution plan, not physical equipment authorization.** Source/CI status is a time-bounded snapshot. Re-fetch branch heads, reviews, safety policies and GitHub checks before each action. Passing CI does not establish hardware certification or external site approval.

## 1. Verified progress since the previous action plan

| Workstream | Verified GitHub evidence | Current decision |
|---|---|---|
| Master plan | [PR #52](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/52) merged 2026-10-18 | **COMPLETE** |
| DOC-01 tracker and readiness reconciliation | [PR #53](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/53) merged 2026-10-18 | **COMPLETE** (update ledger on each later merge) |
| T01 NiceGUI order-independent test isolation/security regressions | [PR #54](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/54) merged 2026-10-18 | **COMPLETE** baseline; continue regressions |
| H02-B part 1 — G07 journal composition, measured setpoint and generation, ramp-aware runner | [PR #55](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/55) merged 2026-10-18 | **COMPLETE** |
| H02-B part 2 — supervised signed-permit path | [PR #56](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/56), head `bbf6c9b5ac2fbd473ed54805123384f51ecae9e6` | **OPEN**; no recorded independent approval; CI in progress at snapshot |
| H02-C separate *physical* watchdog | No merged dedicated implementation identified | **BLOCKER** |
| H03 typed driver/output and gradient support | Driver main unchanged at inspected SHA; simulation profile v2 from #38 | **NOT STARTED** for physical acceptance |
| G07-B evidence/history security and fidelity | Recorder merged and browser/history foundation present | **FOLLOW-UP**; operational review open |
| W02 offline Windows certified release | W02 foundation [PR #30](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/30) merged | **RELEASE NO-GO** |
| G08 independent operational security approval | G08-full #29 merged; site review not evidenced | **OPEN** |
| H01 site-authorized physical certification | Supervised 2026-10-15 manual HIL evidence; 2026-10-19 `tests/hardware` re-run on main `5680adb` **8/8 PASS** (not site-signed) | **OPEN / site signatures absent** |
| R01 production cutover | None | **NO-GO** |

At snapshot, GUI main's three check runs were successful: Windows Python 3.10 and 3.12 model/import and Windows x64 PyInstaller simulated launch ([Windows web CI](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/39125033574), [frozen simulator](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/39125033575)). These are **not** physical-profile acceptance checks. The GUI had one open PR (#56) and no open issues. The external driver had no new milestone PR (old unrelated PR #1 remained open).

### Exact PR #56 checkpoint

- **Branch:** `feat/h02-b-supervised-permit-path`.
- **Current contents:** server-only H02 permit and trust key loading; launch-time fail-closed configuration; scope/operator/witness/driver/GUI revision binding; permit revalidation; restricted G06 physical run path, capability preflight and single G04 START; browser state reporting; mock-only regression tests.
- **Safety boundary:** no general physical profile authorization; the independent H02-C supervisor does **not** exist, so live supervisor validation must refuse physical starts. Real H02 hardware tests **NOT RUN**.
- **Local test evidence reported by PR:** Python 3.10 and 3.12: 453 passed, 9 skipped, 161 subtests on each tested version.
- **GitHub exact-head observation during review:** 16 checks, initially 11 PASS / 5 RUNNING / 0 FAIL; more jobs may complete after snapshot. Confirm exact current results before merging.
- **Review state:** No recorded PR reviews at snapshot. Independent code/safety review is not supplied by CI success.
- **Mergeability:** no reported conflict; GitHub `unstable` while checks were pending.

## 2. Execution queue

| Order | Work package | Suggested PR / branch | Dependencies | Exit / blocked state |
|---|---|---|---|---|
| 01 | Complete existing H02-B part 2 | Existing [PR #56](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/56) | #55, #39 | Exact-head checks, code review, no unauthorized physical start |
| 02 | Independent H02-C watchdog | `feat/h02-c-independent-watchdog` | Stable #56 interface | Bounded independent monitor and STOP/UNKNOWN faults validated; independent review |
| 03 | H02-D cross-component acceptance in simulation | `test/h02-d-full-execution-acceptance` | H02-B and H02-C | Full G04/G06/G07/G08 and NiceGUI/Chromium scenario matrix |
| 04 | H03-A typed manufacturer driver/API | Driver: `feat/h03-typed-output-apis`; GUI adapter follow-up | Driver API inventory | Mocked driver plus GUI conformance; no new physical writes |
| 05 | H03-B outputs, gradients and safe restoration | `feat/h03-b-output-restoration` | H03-A, site policy | Simulated STOP races/restoration and signed site policy required for physical operation |
| 06 | G07-B authenticated evidence & History | `feat/g07-b-evidence-and-history` | Existing G07/G08 | Verified authorized exports and no missed extrema |
| 07 | W02-B reproducible signed air-gap build | `feat/w02-b-offline-supply-chain` | W02 foundation | Trusted verifier, pinned wheelhouse/SBOM, offline evidence |
| 08 | W02-C Windows lifecycle/data recovery | `feat/w02-c-windows-lifecycle` | W02-B, G03/G07/G08 data contracts | Offline Windows install/restart/upgrade/rollback acceptance |
| 09 | G08-OPS independent operational security | Review package; focused remediation PR if needed | G08, W02 deployment | Reviewed LAN/credential/backup/audit security and site policy |
| 10 | H01-A physical site acceptance | Signed site procedure/evidence, no default implementation PR | H02/H03 approved software, P00 | Separately authorized signed hardware tests; independent STOP evidence |
| 11 | R01 production release/cutover | Tagged signed release + approval record | All applicable release and site gates | Signed GO decision |

H03-A, G07-B, W02-B, and G08 review preparation are good parallel workstreams. Do **not** make H02-C and H03-B compete over G04 command dispatch without agreeing the ownership/STOP contracts first. Do not treat a task's priority as permission to bypass safety approval.

## 3. Package 01 — Finish H02-B PR #56

**Immediate actions**
1. Re-fetch latest `main`, PR head, review comments, all required checks and GitHub mergeability. Confirm no newer implementation supersedes the PR.
2. Review the full diff in `chamber_web/hil/supervised_profile.py`, `chamber_web/main.py`, `chamber_web/services/profile_execution.py`, `chamber_web/execution/profile_runner.py`, affected pages and tests.
3. Check signed Ed25519 permit canonicalization, trusted public-key provenance, precise scope, strict H02 launch-time configuration, expiry/replay defenses, pinned 40-hex GUI/driver commits, chamber serial/model/identity, immutable G03 profile SHA, G08 actor and witness.
4. Verify server-derived live checks rather than browser flags; enforce preflight before runner creation and revalidation before every mutation.
5. Confirm *every* path with H02-C missing refuses physical START; no H01-only opt-in, browser-only toggle or simulation impersonation can bypass the gate.
6. Verify G04 single owner, STOP priority and generation fencing, G07 intent-before-write, uncertainty propagation, recorder errors and monitored ramped setpoint behavior; ensure profile v2 auxiliary outputs and gradients reject.
7. Finish all exact-head Python 3.10/3.12 Windows/Linux H02/G06/H01/NiceGUI/Chromium and W01 frozen simulator workflows; inspect any failures, fix root causes and rerun on changed source.
8. Obtain required independent technical review (AI self-review is not qualified human approval). Merge via normal branch protection only when mandatory approvals and checks pass.
9. Recheck post-merge `main`; update H02 and consolidated readiness ledgers.

**Exit:** Software merge accepted, hardware remains **NO-GO** until H02-C and signed site gates. If review/CI remains unavailable, leave PR open and state precise blocker.

## 4. Package 02 — H02-C independent physical watchdog

**Design**
- Reuse the existing *development command* watchdog `scripts/h02_watchdog_command.py` for commands; do not pretend it supervises real chamber safety.
- Provide a separately supervised process with mutually checked heartbeat and authenticated IPC, while G04 remains the sole device command authority. Supervisor may only request the approved STOP path, not become an independent second controller.
- Bind run/permit/identity, G04 generation, ownership, G07 recorder health, live telemetry freshness and approved temperature/step/whole-run bounds to supervision state.
- Use monotonic deadlines, bounded STOP verification and fail-closed restart latch.
- On timeout/failure: prohibit new G06 dispatch, preserve abort/STOP intent where writable, request one approved priority G04 STOP where possible, obtain fresh STOPPED confirmation or retain UNKNOWN, alert on-site operator, persist diagnostic evidence. Never blindly replay or retry ambiguous physical commands.
- Define supervisor loss, application loss and blocked G04 behavior independently. A failed host/OS/network may prevent software STOP entirely; physical emergency procedures remain mandatory.

**Tests:** heartbeat missing in both directions; stuck or cancelled worker; STOP queued while setpoint write waits; stale telemetry; wrong identity; generation/lease changes; G07 ENOSPC/corruption; unverified STOP; process termination/restart; audit/evidence preservation.

**Exit:** independent code/safety review + deterministic mock fault matrix; hardware starts still gated until signed site validation.

## 5. Package 03 — H02-D simulated integration + NiceGUI evidence

Build on `tests/test_h02_supervised_profile.py`, `tests/test_profile_runtime.py`, H01 HIL/Chromium tests and the T01 isolation baseline.

- Simulate complete single-step, multistep, repeat, ramped readback, stabilization/dwell, pause/resume, cancel, and STOP; verify monotonic deadlines.
- Record immutable G03 profile identity and ordered G07 PREPARED/START_INTENT/SETPOINT_INTENT/STOP_INTENT, fresh measured and observed setpoint, controller generation, terminal verdict and SHA-256 run artifacts.
- Verify manual control vs active profile ownership; server session revocation; conflicting operators; browser refresh/disconnect; unauthorized websocket/API requests; expiry of H02 permit mid-run.
- Inject disk full, corrupted SQLite, lost recorder heartbeat, process crash after mutation intent, restart into UNKNOWN, STOP failure, stale/wrong-chamber telemetry; **no automatic physical command replay**.
- Run on Windows/Linux Python 3.10/3.12, combined pytest and actual Chromium; no live device in CI.

**Exit:** exact-head software matrix PASS; physical acceptance marked NOT RUN absent permit.

## 6. Package 04 — H03-A typed output and gradient driver support

1. Review external `VotschTechnikClimateChamber/ClimateChamber.py` dryer, compressed air, gradient up/down and numbered outputs; confirm actual supported OEM units/ranges/options.
2. Introduce typed and validated numbered-output API **in the external driver** when needed. Add mocked transport, error and readback tests; preserve package-at-repository-root layout.
3. Change GUI `chamber_web/adapters/votsch.py` to rely on the driver rather than raw manufacturer query strings.
4. Advertise only installed/verified physical output capabilities. Do not assume outputs 1–64 exist; preserve profile reserved mappings (run 1, compressed air 7, dryer 8) only where verified.
5. Keep setpoint *ramp readback* separate from programmable gradient mutation. Unsupported gradient units/limits must raise `UnsupportedCapability` and remain disabled.
6. Pin the reviewed driver SHA in GUI, verify alternate backend contract, Python 3.10/3.12, Windows/Linux and existing H01 simulation regression.

**Exit:** separate reviewed driver and GUI PRs; hardware outputs remain off limits without site procedure.

## 7. Package 05 — H03-B shutdown/restoration and durable evidence

- Capture authoritative pre-mutation baseline: identity/firmware, run state, observed setpoint, temperature, upward/downward gradient, each touched output, timestamps and G04 generation.
- For approved commands: G08 authorization; site permit; durable G07 OUTPUT_INTENT/GRADIENT_INTENT; G04 serialized write; fresh output/gradient readback; durable observed result; no subsequent write after STOP fencing.
- Define versioned, equipment-specific policy for completion, cancellation, STOP, WATCHDOG, FAULT, UNKNOWN, communication loss and crash. **OFF is not necessarily safe** for dryer/compressed air/output wiring; chamber STOP does not automatically restore auxiliary outputs.
- Restore only with separately approved state/sequence and only when compatible with G04 fencing. Keep UNKNOWN if readback or restoration cannot be verified.
- Test output 7/8, arbitrary numbered output absence, partial sequences, misreported values, bad gradients, baseline loss, STOP during transition, restore failures, G07 recorder errors and browser status. All physical writes must remain disabled until signed H03 authorization.

**Exit:** simulated verification and independent safety policy review; physical H03 acceptance as a later specifically approved stage.

## 8. Package 06 — G07-B authenticated history and run evidence

- Audit NiceGUI History/Logs and RunStore service routes; enforce G08 authorization and audit on every per-chamber/per-run data access/export, including direct download endpoints.
- Show chronological profile states, STOP/UNKNOWN, measured temperature versus intended target and independently observed setpoint, run revisions/checksums and verified manifests.
- Replace naive plotting stride with bounded min/max and edge-preserving buckets if current code can hide short excursions. Keep authenticated, size-bounded exports or reviewed streaming limits.
- Negative tests: modified SQLite/manifests/CSV, unauthorized viewers, revoked sessions, large files, corrupt restart, stale run identity. Document Windows power-cut and off-device audit anchoring as separate certification gates.

**Exit:** real Chromium secure browsing/export PASS, no false COMPLETED/STOPPED verdicts.

## 9. Package 07 — W02-B signed offline Windows supply chain

- Build hash-locked complete transitive dependency wheelhouse; prove offline install/build without internet.
- Produce reviewed *runtime* SBOM (CycloneDX/SPDX), license inventory and source/provenance statement, not merely build-host pip inventory.
- Validate W02 Ed25519 canonical release manifest using a protected **out-of-band** publisher trust root and independently attested standalone verifier. Key rotation/revocation, anti-rollback minimum version, reparse/NTFS alias checks and invalid-key/tamper rejection.
- Test frozen verifier + PowerShell 5.1 on clean disconnected Win10/11 x64 with no Python/Git/Node; inspect local-browser/CDN/DNS/firewall egress evidence.
- Never embed a trust key in the artifact being verified or present a connected GitHub runner as offline certification.

**Exit:** signed, independently verified release candidate plus clean-VM evidence; explicit NO-GO if missing key management/site QA.

## 10. Package 08 — W02-C Windows lifecycle and data migration

- Support supervised server/portable lifecycle, Windows logoff, reboot, sleep/power-loss behavior and strict single-instance ownership.
- Restrict NTFS ACLs for G03 profile SQLite, G07 runs/evidence, G08 security/audit/keys, private release trust data.
- Implement verified pre-upgrade snapshots, schema compatibility checks, migration and rollback of **all** G03/G07/G08 data owners, checked atomic binary stage/swap and post-restart reconciliation.
- Simulate interrupted update, corrupt backup, unexpected database version, active run, stale sessions, foreign port, low disk, restart and failed restore.
- Never auto-resume a physical profile on restart and never roll back code against incompatible database schema silently.

**Exit:** independently reviewed clean Win10/11 offline lifecycle test matrix and operator recovery runbook.

## 11. Package 09 — G08-OPS deployment and independent security review

- Validate General / Isolated LAN PIN/no-expiry / Large Network role/session policy under real browsers and appropriate site network restrictions.
- Review HTTPS/WSS certificates, Host/Origin/DNS rebinding/CSRF, WebSocket logout/revocation, Windows firewall and client-allowlist enforcement.
- Verify factory password + PIN changed before LAN binding; test local-console `reset_credentials.py` / frozen `--reset-credentials`, recovery audit and server-host-only controls with session revocation.
- Independently assess backup/restore, off-device audit anchoring, NTFS private keys, signing key escrow, replay/rollback and credential-safe logging.
- Obtain qualified human assessment, document HIGH/BLOCKER remediations, residual risk and deployment approval.

**Exit:** signed site network/security policy; any unaccepted severe finding blocks production.

## 12. Package 10 — H01-A signed physical acceptance and R01 production release

**H01-A prerequisite:** signed scope-specific site permit with chamber model/serial/firmware, wiring/options, temperature and gradient envelopes, physical STOP and emergency procedures, operator and witness, approved procedure, limits and independent post-test inspection.

- Prior H01 manual tests/soak may be cited as *historical supervised data*, not as blanket H02/H03 approval.
- Test H02 physical profiles only after H02-B/C/D software gates and a new H02 signed test procedure. H03 outputs and gradients require distinct approval. Intrusive process/network/power tests need additional signed hazard reviews.
- Preserve independent STOP readback, G07 raw evidence, manifest checksums, physical final baseline and witness signoff.
- Record PASS/FAIL/NOT RUN honestly and retain UNKNOWN for unverified STOP or state restoration.

**R01:** Freeze exact GUI/driver SHA, dependency lock, signed artifact, release signing authority, training manuals, administrative recovery, installation/rollback steps and release decisions. Independent qualified site/security/release owners must sign GO. Production remains **NO-GO** until then.

---

## 13. Execution streams, coordination and handoffs

**Stream A — Critical safety path (sequential):**
1. Finish #56 exact-head CI + review + merge.
2. H02-C supervisor/STOP mock faults.
3. H02-D full simulated browser/integration acceptance.
4. Distinct site-authorized physical H02 HIL review and execution only if signed.

**Stream B — Hardware capability path (parallel until merging shared G04/G06):**
1. H03-A external typed driver API.
2. GUI vendor-neutral capability adapter.
3. H03-B site-specific safe disposition and simulation tests.
4. Distinct signed physical H03 test permission.

**Stream C — Production packaging path (parallel):**
1. W02-B hash-locked supply chain + trusted verifier.
2. W02-C Windows lifecycle/data migration.
3. Offline clean Win10/11 QA + G08-OPS independent security review.

**Stream D — Quality/evidence (parallel):**
1. G07-B history/evidence integrity.
2. T01 combined NiceGUI/Chromium regression as ongoing CI.
3. DOC-01 ledger updates after each accepted merge.

**Shared-file coordination:** G04 ChamberManager/controller, G06 ProfileRunner and G07 event contracts have single primary owners. Do not merge H02/H03 parallel feature branches without reviewing STOP and generation semantics together. Driver API work lives in the separate Python driver repository; GUI consumes only a pinned reviewed revision.

## 14. Required execution watchdog (all task prompts)

The existing `scripts/h02_watchdog_command.py` is the preferred **development/test subprocess watchdog**. For long-running test, browser, PyInstaller, Git or CI-poll stages:

1. Use a finite per-command timeout, finite idle/heartbeat timeout and bounded cleanup deadline.
2. Capture PID/process group, timestamps, separate stdout/stderr logs and JSONL/summary evidence.
3. Detect hang and terminate owned process tree; TIMEOUT, lost heartbeat, cancelled or incomplete runs are **never PASS**.
4. Split large test suites by independently bounded logical groups; retry only after root-cause review; do not suppress CI failures or force-merge.
5. Use bounded GitHub polling and provide status/checkpoint reports rather than silently hanging.

**Development-only example** (not a certified hardware timeout):

~~~bash
python scripts/h02_watchdog_command.py \
  --timeout-s 180 \
  --idle-timeout-s 75 \
  --cleanup-s 5 \
  --log-dir test-evidence/h02 \
  -- python -m pytest -q tests/test_h02_profile_admission.py
~~~

**Physical watchdog:** H02-C is a separately specified independent supervisor and must never be substituted by this command runner. Physical watchdog limits/response are supplied by signed site safety procedures; software cannot guarantee emergency STOP after host power, OS, transport or instrument failure.

## 15. Per-PR required evidence and acceptance

Every implementation PR must provide:

| Field | Required content |
|---|---|
| Task/scope | Work-package ID, affected architecture, expressly excluded live hardware scope |
| Revisions | Exact inspected base GUI/driver SHAs, final tested head SHA and dependency pin |
| Tests | Counts by suite/platform and PASS/FAIL/SKIP, fault injections and real Chromium when relevant |
| CI | Exact GitHub Actions URLs; mandatory checks on final head; post-merge main recheck |
| Review | Independent code/security/safety findings, reviewer and unaccepted BLOCKER/HIGH list |
| Watchdog | Finite deadlines, timeout/liveness outcome, cleanup and preserved diagnostic evidence |
| G04/G06/G07 | Operator lease, STOP generation, immutable event intent, measured readback, restart/UNKNOWN fidelity |
| Physical HIL | Explicit signed authorization reference + test method + witness, or **NOT RUN** |
| Release | Distinguish software merge, operational/security certification, physical acceptance and R01 GO |
| Merge | PR URL, merge commit SHA, final ledger/README updates |

**Merge policy:** Fetch final source and approvals, run exact-head required checks, correct blockers, merge only under normal branch protection and review policy. AI-assisted review is not an independent human safety approval. Document blocked work instead of inventing proof.

## 16. Immediate next actions / decision record

1. **Highest priority:** Finish verification and independent review of **existing PR #56**; do not create duplicate H02-B work.
2. **Next critical implementation:** H02-C physically supervised watchdog. Without it, signed H02 permit preflight cannot authorize physical profile execution.
3. **Then:** H02-D end-to-end simulated acceptance before any new hardware test.
4. **Parallel now:** H03-A external driver typed outputs and gradients; G07-B authenticated evidence; W02-B complete air-gap supply chain.
5. **Release parallel:** W02-C Windows lifecycle and G08-OPS qualified independent security assessment.
6. **Final:** Site-signed H01/H02/H03 evidence then R01 release approval.

**Decisions at snapshot:** Software core functional; H02-B part 1 merged; H02-B part 2 open; independent physical watchdog missing; physical G06 profiles **NO-GO**; physical auxiliary outputs/gradients **NO-GO**; certified W02 offline Windows release **NO-GO**; R01 production release **NO-GO**.
