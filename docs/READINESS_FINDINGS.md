# Migration readiness findings — canonical closure ledger

**Current stage (2026-10-19):** [Stage 2 — pre-production hardening and controlled pilot preparation](STAGE_2_PILOT_READINESS_PLAN.md). H01 engineering verification has recorded physical 8/8 PASS on 2026-10-19 ([PR #60](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/60)); raw evidence is local and site acceptance signatures are not recorded. H02-B/C software is merged (#55/#56/#58), but physical H02 profile acceptance, independent safety/security review, W02 offline release and R01 remain OPEN. The dated ledger below is a preserved historical 2026-10-18 snapshot and must not be mistaken for the current source revision.

Original review baseline: GUI `9bbbc6d`, driver `67978f9` (2026-10-12). Status rechecked 2026-10-18 against GUI `9e6c892` (main after PRs #24–#52 merged, including G05 #28, G07-A #27, G08-full #29, W02 foundation #30, H01 #34/#36/#37, H02 #39, factory admin #49/#51 and CI de-flake #50) and driver `9323e3701f3befedcc23b45170a851fd327f0bcc`. **Original review SHAs are historical, not the current implementation.** `B`/`H`/`M` are the only valid IDs for the 2026-10-12 readiness review. Older unidentified `BLOCKER-01`–`HIGH-10` tags in previous plans have been retired rather than guessed into equivalence. Dated sections remain historical records; current consolidated status is in the [2026-10-18 ledger](#consolidated-blockerhigh-ledger--2026-10-18). See [P00 contracts](P00_DECISION_CONTRACTS.md). Main advanced 2026-10-18 to `36e25a1` with PRs #53–#58 (DOC-01 #53, T01 #54, H02-B #55/#56 `2f63d58`/`4f9eaf0`, execution plan #57 `c669f2956f2a5ddd3911f6de38b06dbb7b98b4ab`, H02-C watchdog #58 `36e25a1`).

## Consolidated BLOCKER/HIGH ledger — 2026-10-18

Release-state definitions used here and in the reconciled reviews: **implemented** (code merged to `main`); **tested in simulation** (mock/simulator CI and browser tests on the merged head, no physical I/O); **tested on physical hardware** (executed against the real Vötsch VT 4011 under supervised HIL with recorded evidence — the 2026-10-15 sessions are the only such evidence and are not certification); **independently approved** (qualified external human review of the exact accepted revision — not obtained for any finding); **certified for release** (signed site acceptance, W02 packaging/data approval and R01 GO — not obtained).

| ID | Severity | Finding / risk | Owner | Dependencies | Verification evidence (current) | Signoff | Closure status |
|---|---|---|---|---|---|---|---|
| B1 | BLOCKER (hardware) | Unbounded/ambiguous TCP exchange | Driver (D01) | — | Driver PR #2 merged `9323e37`; mocked transport/refusal tests; real commands exercised in supervised HIL 2026-10-15 | None (site) | Software merged, HIL exercised; **physical framing certification OPEN** |
| B2 | BLOCKER (hardware) | STOP verification and uncertainty | G04/G05 + H01 | B1 | G04 mock STOP fencing (#19); H01 STOP-during-ramp and soak evidence (#34, #36 merged) | None (site) | Software merged; **physical STOP/site authority OPEN** |
| B3 | BLOCKER (hardware) | Unsigned model envelope and failure response | Site + P00 | Signed site permit | `H01_HARDWARE_ACCEPTANCE_CHECKLIST.md` unexecuted; site data not supplied | Site signature absent | **OPEN — SITE** |
| B4 | BLOCKER (release) | Controller/persistence/auth/HIL incomplete | GUI program | B1–B3 | G04/G06/G07/G08-min/G05/G08-full/H02 software all merged (#24–#39); H01 supervised session passed 2026-10-15 | Independent review + site absent | **OPEN — release NO-GO; software scope largely merged** |
| H2 | HIGH | Null gradient inherits prior hardware state | G06/P00 | Site gradient envelope | Explicit baseline semantics plus G06 simulation tests | HIL gradient signoff absent | Simulation verified; **HIL OPEN** |
| H4 | HIGH | Loopback hardware auth gate too late | G08 | — | #25/#29 merged; G05/G07/G08 endpoints guard every mutation | None | Software merged; physical use gated by HIL/site policy |
| H7 | HIGH | SQLite/filesystem crash gap | G07 | Windows volume testing | #27 merged with journal/recovery/fault tests (mock) | Independent durability review absent | Software merged, mock-tested; **Windows power-cut certification OPEN** |
| H8 | HIGH | CI/dependency/driver pin insufficient | Release/W02 | Wheelhouse/hash lock | Direct pins + driver commit pin; W02 foundation #30 merged (connected CI only) | Independent supply-chain review absent | **OPEN — W02 certification gates** |
| H01-OPEN | RELEASE | Site safety signoff, signed HIL acceptance, hardware profiles/gradients/long soak | Site + GUI | H02 plan | 2026-10-15 supervised sessions (8/8 hardware tests, soak PASS); 2026-10-19 re-run on main `5680adb` — `tests/hardware` **8/8 PASS** | Signatures absent | **OPEN** |
| H02-WD | BLOCKER (physical) | Runtime composition and separate physical watchdog absent | GUI (H02-B/C) | Signed H02 permit | Preflight validator + test watchdog merged (#39 `1dae5ad`); supervised permit admission merged (#55 `2f63d58`, #56 `4f9eaf0`); independent watchdog merged (#58 `36e25a1`) | Independent safety review absent | Runtime composition + watchdog software merged; physical **OPEN** |
| G07-R items | HIGH (release) | Power-cut durability, measured-setpoint evidence, authenticated export anchoring, independent review | G07/G06/G08 | Windows volume + review | #27 merged ([merge-gate audit](G07_A_MERGE_GATE_AUDIT.md)) | None | **OPEN** as itemized in the audit |
| G08 review | HIGH (review) | Off-device audit anchoring, backup rollback, NTFS ACLs, LAN penetration | Security | External reviewer | #29 merged; adversarial tests green at merge | Independent reviewer absent | Software merged; **independent approval OPEN** |
| W02 | HIGH (release) | Air-gap wheel closure, reviewed SBOM/licenses, target verifier certification | Release/W02 | Signing station/QA | Foundation merged `0e9e9cd`; connected CI green | QA/site absent | **RELEASE NO-GO** ([W02 ledger](W02_OFFLINE_RELEASE.md)) |

### Historical 2026-10-12 review ledger (retained; statuses above supersede)

| ID | Severity | Finding | Work item / closure evidence | Status |
|---|---|---|---|---|
| B1 | BLOCKER (hardware) | Unbounded/ambiguous TCP exchange | Driver PR #2 merged as `9323e37` with 3.9/3.12 CI; H01 framing certification | SOFTWARE FIX MERGED; HIL OPEN |
| B2 | BLOCKER (hardware) | STOP verification and uncertainty | Driver PR #2 `9323e37` plus mock-only G04-A [PR #19](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/19): STOP-generation fencing and fresh readback, [Windows mock CI](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38282962585). Hardware STOP/HIL and site authority remain outstanding | DRIVER/G04-A SOFTWARE MERGED AND TESTED; HIL/SITE OPEN |
| B3 | BLOCKER (hardware) | Unsigned model envelope and failure response | P00 signed site limits/policy and H01 | OPEN: SITE |
| B4 | BLOCKER (release) | Controller, run persistence, authentication and HIL incomplete | G04-A mock-only controller PR #19 and G06-A simulated runner PR #24 merged as `28377a4eb0c7f651063c87ad5789810b036380fe`; G08-min mock-only authorization PR #25 merged `61d8aefaadcdb6f5035b6683410bee0abf76e9d1`; G07-A #27, G05 #28 and G08-full #29 merged 2026-10-15; H02 software foundation #39 merged `1dae5ad`; H01 supervised HIL passed (site signoff absent); W02 foundation #30 merged; R01 pending | OPEN — NO PHYSICAL/R01 AUTHORIZATION |
| H1 | HIGH | Non-finite driver numeric inputs | Driver PR #2 `9323e37` and unit tests | SOFTWARE FIX MERGED |
| H2 | HIGH | Null gradient inherits prior hardware state | P00 explicit baseline semantics + G06 tests/HIL | ENGINEERING CONTRACT DRAFTED; HIL PENDING |
| H3 | HIGH | Zero-stability, gaps, deadline ambiguity | P00 virtual-clock semantics + G06-A PR #24 simulation-only tests; Windows Python 3.10/3.12 [run 38289290272](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38289290272) green | SOFTWARE VERIFIED IN SIMULATION; HIL/SITE OPEN |
| H4 | HIGH | Loopback hardware authentication gate too late | G08-min [PR #25](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/25) merged `61d8aefaadcdb6f5035b6683410bee0abf76e9d1`; [3.10/3.12 CI 38438666305](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38438666305) passed; dependent endpoints must integrate its guards before writes | AUTH CORE + G05/G07/G08 GUARD WIRING MERGED; PHYSICAL/SITE OPEN |
| H5 | HIGH | Previous finding IDs undefined | This ledger and sequence linkage, P00 PR #6 | CLOSED (documentation) |
| H6 | HIGH | Legacy demo CSV migration ambiguous | GUI PR #8 `2ef81b6` adds strict parser and legacy-source-preserving ZIP; [GUI PR #12](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/12) adds transactional SQLite revisions with strict schema checks. G03-C authenticated editor PR #26 merged `fee88ab7929b414e02ac11d81881450e8c9ac365` | CORE + AUTHENTICATED EDITOR SOFTWARE VERIFIED; final-head Windows 3.10/3.12 NiceGUI [38441138681](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38441138681) green; HIL/G07 OPEN |
| H7 | HIGH | SQLite/filesystem crash gap | G07 journal/recovery/fault tests | G07-A PR #27 MERGED (SIMULATION); Windows power-cut certification OPEN |
| H8 | HIGH | CI/dependency/driver pin insufficient | [GUI #10](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/10) `ef473e1` pins direct dependencies and driver revision; [Windows CI green](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38261039285). W02 signed-release foundation #30 merged `0e9e9cd` (connected CI only); hash-locked transitive freeze, typing and offline VM gates pending | PARTIAL — W02 RELEASE GATE OPEN |
| M1 | MEDIUM | One-device multi-vendor architecture unproven | GUI PRs #7/#9 G01, PR #14 single-device Dashboard and G04-A PR #19 fake/alternate/Vötsch-mock substitution with mock-only serialized backend controller | G01/G02-A/G04-A MOCK SOFTWARE MERGED; G02-B/HIL OPEN |
| M2 | MEDIUM | Windows freezing/offline unverified | [GUI PR #18](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/18) Windows prototype + [packaging CI](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38283556276); W02 foundation PR #30 merged `0e9e9cd`; disconnected clean Win10/11 VM still required | W01-A + W02 FOUNDATION SOFTWARE MERGED (SIMULATION ONLY); W02 AIR-GAP CERTIFICATION OPEN |

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

See [DEVELOPMENT_SEQUENCE.md](DEVELOPMENT_SEQUENCE.md) for per-delivery-unit progress (2026-10-18: all software PRs through #52 merged; W02 certification pending), and [REMAINING_DEVELOPMENT_TASKS.md](REMAINING_DEVELOPMENT_TASKS.md) for the ordered closure program. **No site approval or HIL is recorded.** Hardware remains disabled. Status updates must distinguish phase-complete evidence from a merged foundation or demo.

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

## W02 signed offline Windows packaging checkpoint — 2026-10-14

- **Historical (2026-10-14):** [PR #30](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/30) was still draft at this checkpoint. **Closure: PR #30 merged 2026-10-15 as `0e9e9cd546cc675f06734272a67c4a8ce7a9da70`** after passing PR-head Windows checks; every W02 release gate below remains OPEN. The branch included merged H01 extended simulation/browser tests and PR #33 cross-platform *developer* setup.
- **W02-R01–R06 software remediations:** original 3.10/3.12 Ruff F401 failures repaired, pytest NiceGUI dependency installed, Python 3.10 hashing compatibility repaired, explicit signed-sidecar W01 cross-check, Windows path/key/copy protections and regression tests. Signed-inventory [Windows 3.10/3.12 run 38618267798](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38618267798) passed on intermediate head `29b6b73772dcc3d7a382367f55ae99806053ed36`; final commit matrix MUST be checked separately.
- **H8/W02 release BLOCKERS OPEN:** transitive hash-locked wheel closure, *reviewed* runtime SBOM and third-party license approvals, independent publisher keys and Python-free on-target verified signature chain, durable minimum-version trust state, atomic updater and profile/G07/G08 database snapshots/migrations/rollback, Windows NTFS/firewall/restart/logoff/credential handling, connected-vs-isolated egress proof, clean network-denied Win10/11 x64 VM and human security/supply-chain/QA acceptance. Initial CycloneDX and license/provenance output are explicitly labeled *provisional build-environment only*.
- **Site/physical status:** B1–B4 and H01 physical remain unchanged and **NO-GO**. Neither an unsigned frozen simulator nor a passing software CI runner enables hardware operation. See [W02 matrix](W02_OFFLINE_RELEASE.md) and [security review](W02_SECURITY_REVIEW.md).
## G08 full-security integration candidate (2026-10-13)

**Closure (2026-10-18):** [PR #29](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/29) merged 2026-10-15 as `2fdd143cb743fe52b30223f65ce7fe88cb4ff5e7` after green PR-head checks. It contained a mock-only G08 security implementation based on the **merged** G08-min PR #25; the independent review, LAN and physical gates below remain OPEN. The branch reconciliation preserves newer mainline profile/editor work. See [G08 threat model](G08_FULL_SECURITY.md), [review ledger](G08_SECURITY_REVIEW.md), and [unresolved tasks](G08_REMAINING_WORK.md). Final-head Windows 3.10/3.12 and offline packaging checks passed before the merge; independent review was **NOT obtained** and remains OPEN; no G08 production-security closure, LAN deployment authorization or physical-operation release is asserted.

## G08 integration follow-up (2026-10-14)

**Closure (2026-10-18): PR #29 merged 2026-10-15 as `2fdd143c`; independent security review remains OPEN.** The text below is the historical checkpoint.

G08 PR #29 remains software-only, with physical I/O disabled. H01 #32 and cross-platform setup #33 are now merged into main; this branch incorporates both without introducing hardware enablement. Windows NiceGUI testing exposed a previously missed G02-B test `Host: testserver` mismatch; test fixture corrected without relaxing middleware host enforcement. Final Windows CI and independent human security approval are still required. G05 #28 and G07-A #27 remain separate open PRs; their unmerged interfaces are not assumed available.

## G08-full review and mainline integration checkpoint — 2026-10-14

**Closure (2026-10-18): PR #29 merged 2026-10-15 as `2fdd143c`; the independent-review, LAN and signed P00/H01 gates below remain OPEN.** The text below is the historical checkpoint.

G08-full [PR #29](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/29) reconciled the merged H01 verification **preparation** #32 and environment setup #33 against `main`. Draft G05 #28 and G07-A #27 were not silently integrated. Python 3.10/3.12 [NiceGUI run 38457405604](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38457405604) exposed a test-client Host mismatch; the test now uses permitted loopback host instead of weakening production defenses.

The security code now checks the SQLite AUTOINCREMENT audit tail against the HMAC chain, with adversarial regression. This does **not** close the HIGH off-device audit anchoring, signed-backup rollback or NTFS ACL findings. External human review and final-head CI remain required for G08 software merge; signed P00/H01 physical HIL, LAN approval and W02 offline certification remain independent operational NO-GO gates.

Additional G08-full HIGH software findings: losing the security DB while retaining signing keys previously allowed accidental/new-admin bootstrap, and removal of all audit checkpoint/chain rows previously permitted false legacy resealing. These fail-closed cases now have corrected code and explicit negative tests, with positive G08-min upgrade coverage. The final-head Windows run and independent security review are required before treating either as software-verified. No site/LAN/HIL release status changes.

### G05 PR #28 integration checkpoint (2026-10-13)

**Closure (2026-10-18): PR #28 merged 2026-10-15 as `9ca7f5f67666ea2df7170b79682f1f8ab30372a6`; the independent-review and physical gates below remain OPEN.** The text below is the historical checkpoint.

G05 is a **mock-only software candidate with all five final-head Windows CI checks passed** at `3dc72ec7f8df73136a8822f7a201eac082320fab` ([G05/G08/G03-C Windows 3.10/3.12](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38453093551), [G06 3.10/3.12](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38453093490), [W01 packaging](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38453093491)). Independent review approval and PR merge remain pending. G03-C profile editing is retained. No real device activation is authorized. Site-approved chamber identity/limits, physical STOP procedures and HIL, driver capability/readback qualification, G07 recording integration, G08-full, W02 offline release and final site certification remain **OPEN**.


## G05 pre-merge rebase/synchronization — 2026-10-14

**Closure (2026-10-18): G05 #28 and G07-A #27 both merged 2026-10-15; post-merge integrated checks ran in the later PRs. Text below is historical.**

The existing G05 branch was integrated with latest `main`, preserving merged H01 #32 and environment setup #33. G07-A #27 had not merged at this checkpoint (merged 2026-10-15, as were G05 and G08; see the consolidated ledger above). No merged-runner/recorder production claim or site physical authorization exists. All physical I/O remains disabled, including on loopback.


## G05 final-head review requirements — 2026-10-14

**Closure (2026-10-18): PR #28 merged 2026-10-15 as `9ca7f5f6` after its final-head Windows/browser checks passed. The independent human approval item was NOT obtained and remains OPEN; RELEASE NO-GO unchanged. Text below is historical.**

- Existing draft PR #28 now includes the H01 #32/setup #33 merge, actual NiceGUI conditional-button initialization fix, role-guarded degraded STOP visibility, G06/manual exclusive-lease regression and H01 real-browser manual workflow assertions. Prior Chromium CI revealed an actual UI defect; exact final-head green browser and Windows CI are still required. Do not infer acceptance from earlier-head green CI.
- **UNRESOLVED MERGE GATES:** independent qualified human approval; exact final-head G05/G06/G08/NiceGUI/H01 Windows 3.10/3.12 and frozen Windows package checks; G07 #27 merge and subsequent G05 resynchronization/test; authenticated profile runner and G07 recording composition into the live app; engineering review of real browser session/Origin/CSRF deployment boundaries.
- **RELEASE NO-GO:** G08-full, W02, physical H01 signed site acceptance/STOP/operating limits, validated physical driver, Windows power-loss evidence. Simulation-only FakeBackend remains unconditional. Web STOP is not physical E-STOP.
## G07-A current readiness — 2026-10-13

**Closure (2026-10-18): PR #27 merged 2026-10-15 as `fa77998faff9343c1751e6c0bf5d5a78bb4712af`; the RELEASE HIGH/MEDIUM items below remain OPEN.** The text below is the historical checkpoint.

- [PR #27](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/27) source `c586bd563b60830130d1d098c0bf21ef3ab47a23` has recorded passing [G07 recorder + 1M samples](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38440410962), [G06](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38440410835), [NiceGUI](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38440411011) and [W01](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38440410963) workflows. These checks precede synchronization with `main` `7a481d1125148fdcd610c0e9fea1dd7621ac938a`; exact integrated-branch verification remains required.
- **RELEASE HIGH (open):** Windows power-loss/rename durability, G06 independently observed setpoint readback, G08 authorization and audit for any future G07 History/Logs/download routes, offline corruption disposition and independent human architecture/security approval. Existing Python-only read services do not constitute authenticated web routes.
- **MEDIUM (open):** stride-based plotting can miss extrema; CSV/ZIP hard bounds reject large runs. Simulator-only integration does not close H7, B1–B4, site STOP approval, H01 or W02.
- **NO MERGE** until reviewed final integrated head passes all G07/G06/G08/NiceGUI/W01 Windows gates, branch is GitHub-mergeable, and required independent approval is obtained. UNKNOWN/INTERRUPTED must never be reported as verified STOPPED; recovery must never issue chamber I/O.


## G07-A integration sync — 2026-10-14

**Closure (2026-10-18): PR #27 merged 2026-10-15 as `fa77998f`; the independent human durability/security acceptance item remains OPEN. Text below is historical.**

The existing G07-A branch was integrated with `main` including merged H01 #32 and environment setup #33. Original earlier-head CI evidence remains historical; final merge requires exact updated-head G07/G06/G08/NiceGUI/H01/Windows packaging checks and independent human architecture/durability/security acceptance. Physical hardware remains disabled; H01 site physical certification, G08-full, W02 and signed site safety approval remain NO-GO.

## G07-A remediation / outstanding release findings — 2026-10-15

| ID | Severity | Finding and closure | Status |
|---|---|---|---|
| G07-R9 | HIGH (software) | Missing SQLite DB with surviving run files or `-wal/-journal/-shm` sidecars previously recreated an empty history. Fail-closed preconnection guard and missing-DB, orphan-WAL regressions added on PR #27. | FIXED AND MERGED AS PART OF PR #27 (2026-10-15) |
| G07-R10 | HIGH (software lifecycle) | START_INTENT and STOP_INTENT recovery must avoid fabricated success or restart; STOP/cancel + UNKNOWN reconciliation + tamper denial integration test added. | FIXED AND MERGED AS PART OF PR #27 (2026-10-15) |
| G07-R1/R2/R3/R4/R7/R8 | HIGH (release/acceptance) | Windows power-cut directory durability, G06 measured-setpoint/generation evidence, future G08-min authenticated History/Logs/export routes, independent archival integrity/backup, exclusive startup ownership and independent human review. | **OPEN (release items); PR #27 MERGED 2026-10-15 `fa77998f` — items remain OPEN** |

The validated prior-source CI for `007e6053258680dd8df16175e66dfb00847c535d` was [G07 Windows/million samples](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38613839443) and [H01 Windows/Linux/Chromium](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38613839547); that evidence is not a result for the updated branch. Hardware activation, physical HIL, W02 Windows release and G08-full remain disabled/open. Do not interpret mock STOP as an emergency stop.


## Readiness after merges and first supervised HIL — 2026-10-15

| ID | Severity | Finding | Status |
|---|---|---|---|
| H01-F1 | HIGH (hardware) | VT 4011 `GET CONTROL_VARIABLE SET_POINT` returns the ramped instantaneous setpoint, not the target; immediate readback check made every setpoint change UNKNOWN (fail-safe). | FIXED in [#34](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/34): ramp-aware G04 path check + G05 convergence/settle; verified on hardware |
| H01-F2 | HIGH (safety labelling) | Any driver injected into `VotschBackend` was reported `is_simulation=True`, so a real chamber would show SIMULATION ONLY. | FIXED in [#34](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/34): HIL identity is physical; UI labels SUPERVISED PHYSICAL HIL |
| H01-F3 | MEDIUM (process) | Divergent ramp toward a wrong goal passes through the target and could be confirmed by a single read. | FIXED in [#34](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/34): settle window; regression test |
| T-1 | MEDIUM (test isolation) | Tests used the developer's real `~/.chamber_web`; persisted leases made local runs disagree with CI. | FIXED in #28 (`tests/conftest.py`) |
| H01-OPEN | RELEASE | Owner/site safety signoff, signed HIL acceptance, profiles on hardware, gradient control, long soak and STOP-during-ramp evidence. | OPEN |


## Real-hardware test suite and soak — 2026-10-15

VT 4011 SN 58566207770010, supervised, envelope 20–30 °C.

- `tests/hardware/` (opt-in): **8/8 passed** in 125 s — identity/gradients (5.0 up / 3.0 down K/min), telemetry max latency 31 ms, out-of-envelope 35/15 °C REJECTED with no write, no-lease command refused, ramped setpoint 23→24 °C in 12.8 s and 24→23 °C in 21.0 s, START → RUNNING → verified STOP, **STOP during a running setpoint ramp confirmed in 0.24 s** (pending set → UNKNOWN), Chromium claim/set/start/stop.
- `scripts/hil_soak.py`: **PASSED**, 1650 s, 312 samples, 0 non-GOOD, 12/12 commands confirmed, latency mean 15 ms / max 68 ms. Steady-state last-minute means: 24.91 °C @25, 26.15 °C @26, 24.03 °C @24, 24.18 °C @24 after restart; worst overshoot −0.5 °C cooling to 24 °C; settle to ±0.2 °C in 15–100 s. Chamber STOPPED and setpoint restored to 23.0 °C at the end.
- Found by the dry run: STOP keeps the operator lease (soak claims only if free), and a setpoint read right after a write is mid-ramp — the original setpoint is now recorded only once the readback has settled.
- Still open: owner/site safety signoff and signed acceptance, profile execution on hardware, gradient (ramp-rate) control.


## H02 outstanding review and readiness — 2026-10-15

Hardware blockers B1/B2/B3/B4 and H2/H4/H7/H8 must not be treated as closed by simulation results. The H02 software foundation adds permit validation and a software command watchdog, but physical-profile runner dispatch, supervision, G07 composition, independent review, signed site method and STOP evidence are still missing. See [H02 verification plan](H02_PROFILE_VERIFICATION_PLAN.md).

**Update 2026-10-18:** the H02 software foundation merged as PR #39 `1dae5ade00f67318f01c763e395f0e85f5310c6a` with all PR checks green (preflight validator and test watchdog only — no physical connection). Runtime composition (H02-B), the separate physical watchdog (H02-C) and site permits remain OPEN per [REMAINING_DEVELOPMENT_TASKS.md](REMAINING_DEVELOPMENT_TASKS.md). **GO/NO-GO unchanged: NO-GO. Hardware test result: NOT RUN.**

**Update 2026-10-18 (later):** H02-B runtime composition merged (#55 `2f63d58`, #56 `4f9eaf0`, 16/16 checks green) and the current execution plan was published as PR #57 `c669f2956f2a5ddd3911f6de38b06dbb7b98b4ab`. The H02-C independent watchdog implementation (separate OS process, authenticated loopback IPC with mutually verified heartbeats, one prioritized G04 STOP request with bounded fresh STOP verification, restart latch and `scripts/h02_watchdog_reset.py` review path) merged as PR #58 `36e25a1`. Site permit signature and independent safety review remain ABSENT. **GO/NO-GO unchanged: NO-GO. Hardware test result: NOT RUN.**

## Stage 2 package status — 2026-10-21

Stage 2 tracker: [STAGE_2_PILOT_READINESS_PLAN.md](STAGE_2_PILOT_READINESS_PLAN.md). This
section records Stage 2 package deliveries only. It does **not** close any
BLOCKER/HIGH above, does not change the R01 decision (**NO-GO**) and asserts
no physical, HIL or site-signature evidence.

| Package | Status | Evidence | Remaining |
|---|---|---|---|
| S2-01 HIL evidence closure | **NOT DELIVERED** — needs the site authority | No signed H01 acceptance form or controlled evidence index in the repository | Site signoff and raw H01 evidence ingest |
| S2-02 Combined regression baseline | **DELIVERED — implemented + simulation-tested** | GUI PR [#73](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/73) merged `014456b` (branch head `ea14bc7`); combined simulation job on Ubuntu 3.12 + Windows 3.10/3.12 ([main run 39678456898](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/39678456898)); restored NiceGUI job on Windows 3.10/3.12 ([main run 39678457039](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/39678457039)); local combined suite 536 passed / 1 skipped / 196 subtests; controlled evidence record [test-evidence/s2-02/S2_02_REPORT.md](../test-evidence/s2-02/S2_02_REPORT.md) | Independent review, S2-03/S2-04 Windows VM evidence, S2-07 physical H02 acceptance |
| S2-03 W02 offline signed bundle | **PARTIAL — air-gap dependency closure delivered** | GUI PR [#77](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/77) merged `bcdade3`: `requirements-w02-runtime.lock` (48 win_amd64/cp312 distributions, each pinned and hashed), `w02-closure-manifest.json`, the runtime CycloneDX SBOM derived from that closure, and a Windows CI job that reproduces the closure and installs it with `--no-index --require-hashes` ([closure job on PR](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/39684390357)); continuous gate on `main` added by PR [#78](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/78) | Vendored Vötsch driver wheel with its own recorded hash; signed artifact with a site publisher key; license approval (every row still `REVIEW_REQUIRED`); unattested build provenance; the frozen Windows package itself; the disconnected clean-Windows 10/11 acceptance (S2-04) |
| S2-04 Installation/upgrade/recovery | **NOT STARTED** | — | Clean air-gapped Win10/11 acceptance |
| S2-05 G07 evidence and operations | **PARTIAL** — journal readers merged (#74) | GUI PR [#74](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/74) | Authorized, SHA-verified exports; corruption/ENOSPC recovery |
| S2-06 G08 operational security acceptance | **NOT STARTED** | — | Independent deployment review |
| S2-07 H02 physical-profile acceptance | **NOT RUN — NO-GO** | No physical H02 result in the repository | New, separately signed H02 permit; witnessed run |
| S2-08 Pilot usability and supervised soak | **NOT STARTED** | — | Depends on S2-03/04/05/06/07 |
| S2-09 R01 release candidate decision | **NO-GO** | — | All applicable packages |

### Findings closed by S2-02

- **CI was blind on `main`.** `web-gui-demo.yml` carried a literal `\n` inside a
  YAML scalar (introduced by #62 on 2026-10-19), so the workflow produced **zero
  jobs** on every `main` push and reported failure without testing anything.
  Repaired in #73; the job now runs its Windows 3.10/3.12 matrix.
- **G05 refused a legitimate operator Start (product defect).** The Start-after-STOP
  path learned the operator-lease revision through a *best-effort, non-blocking*
  probe intended only for the priority STOP path. When the one-second dashboard
  refresh held the same registry lock, the probe reported "unknown", which the
  Start path could not distinguish from "no lease held": the Start was refused
  with `STOP recovery not verified; control remains locked` and the STOP fence
  stayed latched, stranding the operator. Reproduced deterministically before
  the fix; `AuthorizedChamber.ensure_manual_operator_lease_revision()` now reads
  the revision in the same critical section as the claim. The safety envelope is
  unchanged: the rearm still requires the exact lease revision, the caller's
  ownership, a latched `VERIFIED_STOPPED` controller and the exact G04
  generation, and G04 still performs its own fresh STOPPED readback.
- **Refusals were not diagnosable.** A refused manual command reported only the
  exception type; the bounded reason is now reported to the operator, the audit
  trail and CI.

### Findings closed by the S2-03 increment

- **The dependency closure was not hash-locked.** The W02 bundle recorded only
  the build host's installed packages, with every license `REVIEW_REQUIRED` and
  the scope property `unapproved-build-environment-not-runtime-closure`. The
  frozen Windows runtime closure is now a reviewed repository artifact:
  `requirements-w02-runtime.lock` pins 48 `win_amd64`/CPython 3.12
  distributions by SHA-256 in pip `--require-hashes` format, and
  `w02-closure-manifest.json` records every artifact's digest, source URL,
  declared license and `Requires-Python`.
- **The runtime SBOM was a build-host inventory.** It is now derived from the
  locked closure, so build-only tools (PyInstaller, pip, setuptools) can no
  longer be presented as shipped components.
- **Nothing proved an air-gap install.** `scripts/w02_closure.py` installs with
  `pip install --no-index --find-links <wheelhouse> --require-hashes`, so a
  damaged or missing artifact breaks the installation instead of falling back
  to the network. The Windows CI job reproduces the committed closure from the
  pinned requirements and installs from it, on `main` as well as on pull
  requests.
- **The closure's own input digest was platform-dependent.** Git checks text
  files out with CRLF on Windows and LF elsewhere, so the raw digest of the
  same tracked requirements file differed per platform and could never be
  reproduced on another host. The digest is now taken over the canonical (LF)
  line endings, and the closure artifacts are pinned to LF in `.gitattributes`.

**Still open inside S2-03:** the external Vötsch driver is not a PyPI
distribution and is not part of this closure; it must be vendored as a locally
built wheel with its own recorded hash before an air-gap install is complete.
The signed artifact still needs a site publisher key, every license row is
still `REVIEW_REQUIRED`, the build provenance is still unattested, and the
disconnected clean-Windows 10/11 acceptance is S2-04.

**Boundary:** S2-02 is simulation-only. `tests/hardware/` was **NOT RUN**, no
chamber was connected, no physical command was issued, and no device
authorization, H02 permit, W02 release, G08 operational acceptance or Stage 3
pilot use is granted or implied by this delivery.
