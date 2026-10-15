# Migration readiness findings — canonical closure ledger

Original review baseline: GUI `9bbbc6d`, driver `67978f9` (2026-10-12). Status rechecked against GUI `7a5d643` (PR #19 G04-A mock-only controller merge) and driver `9323e37`. **Original review SHAs are historical, not the current implementation.** `B`/`H`/`M` are the only valid IDs for the 2026-10-12 readiness review. Older unidentified `BLOCKER-01`–`HIGH-10` tags in previous plans have been retired rather than guessed into equivalence. See [P00 contracts](P00_DECISION_CONTRACTS.md).

| ID | Severity | Finding | Work item / closure evidence | Status |
|---|---|---|---|---|
| B1 | BLOCKER (hardware) | Unbounded/ambiguous TCP exchange | Driver PR #2 merged as `9323e37` with 3.9/3.12 CI; H01 framing certification | SOFTWARE FIX MERGED; HIL OPEN |
| B2 | BLOCKER (hardware) | STOP verification and uncertainty | Driver PR #2 `9323e37` plus mock-only G04-A [PR #19](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/19): STOP-generation fencing and fresh readback, [Windows mock CI](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38282962585). Hardware STOP/HIL and site authority remain outstanding | DRIVER/G04-A SOFTWARE MERGED AND TESTED; HIL/SITE OPEN |
| B3 | BLOCKER (hardware) | Unsigned model envelope and failure response | P00 signed site limits/policy and H01 | OPEN: SITE |
| B4 | BLOCKER (release) | Controller, run persistence, authentication and HIL incomplete | G04-A mock-only controller PR #19 and G06-A simulated runner PR #24 merged as `28377a4eb0c7f651063c87ad5789810b036380fe`; G08-min mock-only authorization PR #25 merged `61d8aefaadcdb6f5035b6683410bee0abf76e9d1`; G07, G05, G08-full, H01, W02 and R01 pending | OPEN — NO HARDWARE ACTIVATION |
| H1 | HIGH | Non-finite driver numeric inputs | Driver PR #2 `9323e37` and unit tests | SOFTWARE FIX MERGED |
| H2 | HIGH | Null gradient inherits prior hardware state | P00 explicit baseline semantics + G06 tests/HIL | ENGINEERING CONTRACT DRAFTED; HIL PENDING |
| H3 | HIGH | Zero-stability, gaps, deadline ambiguity | P00 virtual-clock semantics + G06-A PR #24 simulation-only tests; Windows Python 3.10/3.12 [run 38289290272](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38289290272) green | SOFTWARE VERIFIED IN SIMULATION; HIL/SITE OPEN |
| H4 | HIGH | Loopback hardware authentication gate too late | G08-min [PR #25](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/25) merged `61d8aefaadcdb6f5035b6683410bee0abf76e9d1`; [3.10/3.12 CI 38438666305](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38438666305) passed; dependent endpoints must integrate its guards before writes | AUTH CORE SOFTWARE VERIFIED; LIVE INTEGRATION/HIL OPEN |
| H5 | HIGH | Previous finding IDs undefined | This ledger and sequence linkage, P00 PR #6 | CLOSED (documentation) |
| H6 | HIGH | Legacy demo CSV migration ambiguous | GUI PR #8 `2ef81b6` adds strict parser and legacy-source-preserving ZIP; [GUI PR #12](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/12) adds transactional SQLite revisions with strict schema checks. G03-C authenticated editor PR #26 merged `fee88ab7929b414e02ac11d81881450e8c9ac365` | CORE + AUTHENTICATED EDITOR SOFTWARE VERIFIED; final-head Windows 3.10/3.12 NiceGUI [38441138681](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38441138681) green; HIL/G07 OPEN |
| H7 | HIGH | SQLite/filesystem crash gap | G07 journal/recovery/fault tests | ENGINEERING CONTRACT DRAFTED; CODE OPEN |
| H8 | HIGH | CI/dependency/driver pin insufficient | [GUI #10](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/10) `ef473e1` pins direct dependencies and driver revision; [Windows CI green](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38261039285). Hash-locked transitive freeze, typing and offline VM gates pending | PARTIAL — release gate OPEN |
| M1 | MEDIUM | One-device multi-vendor architecture unproven | GUI PRs #7/#9 G01, PR #14 single-device Dashboard and G04-A PR #19 fake/alternate/Vötsch-mock substitution with mock-only serialized backend controller | G01/G02-A/G04-A MOCK SOFTWARE MERGED; G02-B/HIL OPEN |
| M2 | MEDIUM | Windows freezing/offline unverified | [GUI PR #18](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/18) Windows prototype + [packaging CI](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38283556276); W02 disconnected clean Win10/11 VM required | W01-A EARLY FEASIBILITY SOFTWARE VERIFIED; W02 AIR-GAP CERTIFICATION OPEN |

**Definition of closure:** a merged PR and passing unit/static/integration checks alone close a code finding only to **software-verified** status. Safety-related findings require signed site documentation and physical HIL. Each future PR must update the row's status, exact merged commit/test run link, and owner/approver; never claim HIL from mocks. Hardware remains disabled in the current demo.

## Implemented PR audit trail

- GUI [PR #26](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/26): G03-C persistent NiceGUI editor plus G08 permission guards and integrated G06 simulated execution regression merged `fee88ab7929b414e02ac11d81881450e8c9ac365` (head `e82aba60e30a330c20944d98f9f28040ef1c93d0`), Windows 3.10/3.12 [NiceGUI 38441138681](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38441138681), [G06 38441138685](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38441138685), and W01 [38441138664](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38441138664) all passed. Addressed cancelled Windows test IDs and deterministic ZIP timestamp flake [#22](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/22). External human approval and HIL not performed.

- GUI [PR #25](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/25): G08-min offline identity, server-side roles, session/CSRF/Origin controls and audited G04 facade merged `61d8aefaadcdb6f5035b6683410bee0abf76e9d1`, final head `8a4164b6098187e57f026718410bf2be7ae96bac`, Windows NiceGUI/security [38438666305](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38438666305) and Windows offline freeze [38438666518](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38438666518) pass. AI-assisted review; G03-C/G06 endpoint wiring, full G08, site signoff and hardware HIL remain OPEN.

- GUI [PR #24](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/24): G06-A simulated, single-chamber deterministic execution engine merged `28377a4eb0c7f651063c87ad5789810b036380fe` from head `ef2e602b3d56b21ae1e7c9b5bfd2a86f817c690f`. Final-head Windows Python 3.10/3.12 G06 [38289290272](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38289290272), NiceGUI [38289290361](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38289290361) and W01 [38289290197](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38289290197) successful. AI-assisted code review closed earlier software HIGH findings; no independent human/safety certification. G08 authenticated binding, G07 durable recorder, H01 physical STOP and site safety approval remain OPEN; all physical writes disabled.

- Driver [PR #2](https://github.com/ami3go/VotschTechnik-climate-chamber-Python/pull/2): `9323e3701f3befedcc23b45170a851fd327f0bcc`, mocked transport/STOP tests green, no HIL.
- GUI [PR #6](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/6): P00 requirements/traceability contracts, `635c453`.
- GUI [PR #7](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/7): vendor-neutral G01 foundation, `c978ef9`.
- GUI [PR #9](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/9): vendor-specific branch isolation correction, `e8519ad`.
- GUI [PR #8](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/8): G03 profile migration core, `2ef81b6`.
- GUI [PR #10](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/10): pins CI-tested direct dependencies and hardened driver revision, `ef473e1`.
- GUI [PR #12](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/12): G03-B SQLite revisions, `252b0fb`, [Windows CI](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38276777330) green. G03-C editor still open; AI-assisted second-pass review, no human/site approval claimed.
- GUI [PR #15](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/15): independent audit follow-up bounded serialization, strict ZIP validation and concurrent revision regression; merged `8235c44`, [Windows CI 3.10/3.12](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38279522018) green; [AI-assisted final review](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/15#pullrequestreview-5493697291).

- GUI [PR #14](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/14): G02-A NiceGUI read-only server binding, merged [`8d22b8a`](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/commit/8d22b8a21648c2bf4b22a9dd7a6b07ca0be1d822) with [final-head Windows 3.10/3.12 CI](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38280329089) green and [AI-assisted review](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/14#pullrequestreview-5493759062). G02-B remains open; no driver/hardware operation, HIL or human/site approval.

- GUI [PR #19](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/19): G04-A serialized mock-only ChamberController, squash merge [`7a5d643`](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/commit/7a5d643ca8b53be9705d6b2f244d1766684d7011), [final-head 3.10/3.12 Windows CI](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38283603116), [AI-assisted requirements review](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/19#pullrequestreview-5494022692) and [fault/concurrency review](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/19#pullrequestreview-5494025452). No human/HIL/site approval claimed.

## G04-A mock-only safety review (PR #19)

- [G04-A PR #19](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/19) adds one exclusive controller, per-ID persisted STOP generations, mock-only I/O, priority STOP, readback and conservative UNKNOWN/FAULT. [Final-head Windows CI 38283603116](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38283603116) passed 3.10/3.12 on PR head `166b7cf`, and GitHub confirms squash merge [`7a5d643`](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/commit/7a5d643ca8b53be9705d6b2f244d1766684d7011) into `main`.
- Reviewed safety-sensitive HIGH failures: old operator's queued write after handover, un-fenced queued write during disconnect, stale STOPPED snapshot accepted at shutdown, and a START completing in-flight after disconnect intent. All have mock regression tests and corrective code on PR #19; see [controller review evidence](G04_A_CONTROLLER_CONTRACT.md).
- Remaining blockers are explicitly not closed: authenticated/authorized/audited mutations under G08-min; site-signed envelope and physical STOP/fault policy; bounded transport and physical HIL. Review is AI-assisted, **not human/site signoff**, and no physical device operation is enabled.

## Independent follow-up on merged PR #12

Reviewed original [G03-B PR #12](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/12): source head `a06874c`, merge `252b0fb`, [Windows Actions success 38276777330](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38276777330) (Python 3.10/3.12). A previous HIGH issue with weakened schema verification was corrected before #12 merged, and the [PR review](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/12#pullrequestreview-5493489781) records that narrow approval.

| Independent review ID | Severity | Verified issue / scope | Remediation and verification gate |
|---|---|---|---|
| G03B-R1 | **HIGH** | Direct `ParsedProfile` save could attempt large ZIP compression before input bounds were enforced; oversized notes, legacy source and migration metadata were not all preflighted | [Follow-up PR #15](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/15) merged as `8235c44` with bounded pre-serialization and regression tests; final-head Windows 3.10/3.12 CI passed in [run 38279522018](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38279522018), **CLOSED (software only)** |
| G03B-R2 | MEDIUM | A well-formed ZIP whose JSON manifest is an array could raise unexpected `AttributeError` instead of an input-validation error | PR #15 merged with object manifest and exact integer version checks and negative test; **CLOSED (software only)** |
| G03B-R3 | TEST COVERAGE | Sequential stale-editor tests did not simulate truly concurrent revisions to the same profile | PR #15 adds an eight-writer concurrent CAS/row-count test; **VERIFIED in Windows CI** |

These G03B-R findings are **supplemental** and do not rename or reinterpret the canonical B1–B4/H1–H8/M1–M2 readiness IDs. Closure evidence for #15 is source `d6df9c7c25ae0026d685de616f430b03b73a5330`, [passing Windows CI 38279522018](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38279522018) (3.10/3.12), [AI-assisted review #5493697291](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/15#pullrequestreview-5493697291) and [merged commit `8235c44`](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/commit/8235c448d5a7e9f66d7c5cfb8b0af8ccdb9712f8). The original #12 CI and the final #15 CI are distinct verified runs. This software-only follow-up does not grant operator authorization or HIL approval. In particular, G03-C editor, G04 controller, G07 crash journal and G08-min authentication remain separate release gates.

## W01-A Windows feasibility and second-pass review (PR #18)

[PR #18](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/18) implements a **simulator-only** Windows browser launcher + frozen NiceGUI archive. A HIGH package-presence-only Vötsch check is closed by performing a safe import **inside the Vötsch adapter** (no physical chamber instance); medium findings addressed a missing unprivileged shortcut creator, HTTP-proxy-bypassing/size-limited loopback readiness, and broad CI freeze triggers. The [AI-assisted review](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/18#pullrequestreview-5494009819) is not an external human/site or HIL approval.

Windows extracted simulator [run 38283556276](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38283556276) and Python 3.10/3.12 regression [run 38283556290](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38283556290) passed on an earlier code head. Review/CI for the final head is recorded in PR #18. A separate G03 ZIP timestamp flake is tracked as [issue #22](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/22). W02 offline VM, signed supply chain, browser egress, security, data migration and site HIL remain OPEN.

All release, HIL, Windows offline and operational security gates remain mandatory.

## Active status/next-PR source of truth

See [DEVELOPMENT_SEQUENCE.md](DEVELOPMENT_SEQUENCE.md) for per-delivery-unit progress, G02-A merged and remaining G08-min-A/G02-B/G03-C PR order (W01-A feasibility delivered; G04-A merged, W02 pending), acceptance and review/merge loops. **No site approval or HIL is recorded.** Hardware remains disabled. Status updates must distinguish phase-complete evidence from a merged foundation or demo.

## G08-min security checkpoint (implementation candidate)

Offline first-admin provisioning, SQLite session authority, server-side role guards,
Origin/CSRF gates and durable command audit are proposed on
`feat/g08-min-authentication`. See [G08_MIN_SECURITY.md](G08_MIN_SECURITY.md).
Until the security CI, review and package/browser evidence is confirmed, this
work is **not** an approved G08 gate. Even after software verification, G04
remains mock-only, the site STOP/limits/HIL approvals and complete G08 LAN
security remain NO-GO.

## 2026-10-13 post-merge residual risk register

- **BLOCKER (hardware/release)** B1–B4 are not physically certified. STOP remains an attempted/mock-only command; never infer stopped state on disconnect. No site-signed machine limits or physical/HIL approval.
- **HIGH / pending for operational readiness:** H2 signed gradient baseline / HIL; H4 G08-min authority only for integrated simulated interfaces, not standalone physical G05/G07/G06 command surfaces; H7 G07 durable recording/crash recovery; H8 W02 air-gapped Windows dependency and supply-chain verification. Full G08 LAN account recovery/audit tamper controls are absent.
- **SOFTWARE FIXED:** G03-C import/ZIP test identifiers previously overwhelmed Windows logs; [issue #22](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/22) canonical ZIP wall-clock timestamps removed with a regression. No physical chamber has been started or certified.


## H01 preparation baseline — 2026-10-13 (PR #32)

H01 simulation-only readiness package proposed in [PR #32](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/32), branch `feat/h01-hil-readiness`. Includes 20-case *future* site HIL procedure matrix, unsigned site equipment checklist, blank signed acceptance report, GO/NO-GO matrix and G04-injected FakeBackend tests. The driver remains pinned to `9323e3701f3befedcc23b45170a851fd327f0bcc`; no driver protocol was modified. This update is **NOT** evidence of executing, passing or certifying HIL. Windows and independent review gates are pending on the PR final head.

B1 transport physical framing/timeout; B2 actual STOP and local emergency procedure; B3 approved exact model/serial/firmware, manual, operating envelope/gradient and site signatures; B4 G05/G07/G08/W02/R01 integration and signed witnessed HIL remain **OPEN / PHYSICAL NO-GO**. H2, H4, H7 and H8 retain their previously documented physical/deployment gaps. Site data, operator signatures, readbacks, STOP timing, alarm semantics and power-loss permits have not been supplied. No physical enable path was added. See [H01 test plan](H01_HIL_VERIFICATION_PLAN.md), [inventory](H01_HARDWARE_ACCEPTANCE_CHECKLIST.md), [report](H01_TEST_REPORT_TEMPLATE.md), and [decision matrix](H01_SITE_APPROVAL_AND_GO_NOGO.md).


## G07-A current readiness — 2026-10-13

- [Draft PR #27](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/27) source `c586bd563b60830130d1d098c0bf21ef3ab47a23` has recorded passing [G07 recorder + 1M samples](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38440410962), [G06](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38440410835), [NiceGUI](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38440411011) and [W01](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38440410963) workflows. These checks precede synchronization with `main` `7a481d1125148fdcd610c0e9fea1dd7621ac938a`; exact integrated-branch verification remains required.
- **RELEASE HIGH (open):** Windows power-loss/rename durability, G06 independently observed setpoint readback, G08 authorization and audit for any future G07 History/Logs/download routes, offline corruption disposition and independent human architecture/security approval. Existing Python-only read services do not constitute authenticated web routes.
- **MEDIUM (open):** stride-based plotting can miss extrema; CSV/ZIP hard bounds reject large runs. Simulator-only integration does not close H7, B1–B4, site STOP approval, H01 or W02.
- **NO MERGE** until reviewed final integrated head passes all G07/G06/G08/NiceGUI/W01 Windows gates, branch is GitHub-mergeable, and required independent approval is obtained. UNKNOWN/INTERRUPTED must never be reported as verified STOPPED; recovery must never issue chamber I/O.


## G07-A integration sync — 2026-10-14

The existing G07-A branch was integrated with `main` including merged H01 #32 and environment setup #33. Original earlier-head CI evidence remains historical; final merge requires exact updated-head G07/G06/G08/NiceGUI/H01/Windows packaging checks and independent human architecture/durability/security acceptance. Physical hardware remains disabled; H01 site physical certification, G08-full, W02 and signed site safety approval remain NO-GO.

## G07-A remediation / outstanding release findings — 2026-10-15

| ID | Severity | Finding and closure | Status |
|---|---|---|---|
| G07-R9 | HIGH (software) | Missing SQLite DB with surviving run files or `-wal/-journal/-shm` sidecars previously recreated an empty history. Fail-closed preconnection guard and missing-DB, orphan-WAL regressions added on PR #27. | CODE FIX PUSHED; FINAL-HEAD WINDOWS CI REQUIRED |
| G07-R10 | HIGH (software lifecycle) | START_INTENT and STOP_INTENT recovery must avoid fabricated success or restart; STOP/cancel + UNKNOWN reconciliation + tamper denial integration test added. | CODE/TEST PUSHED; FINAL-HEAD CI REQUIRED |
| G07-R1/R2/R3/R4/R7/R8 | HIGH (release/acceptance) | Windows power-cut directory durability, G06 measured-setpoint/generation evidence, future G08-min authenticated History/Logs/export routes, independent archival integrity/backup, exclusive startup ownership and independent human review. | **OPEN; PR #27 DRAFT / DO NOT MERGE** |

The validated prior-source CI for `007e6053258680dd8df16175e66dfb00847c535d` was [G07 Windows/million samples](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38613839443) and [H01 Windows/Linux/Chromium](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38613839547); that evidence is not a result for the updated branch. Hardware activation, physical HIL, W02 Windows release and G08-full remain disabled/open. Do not interpret mock STOP as an emergency stop.
