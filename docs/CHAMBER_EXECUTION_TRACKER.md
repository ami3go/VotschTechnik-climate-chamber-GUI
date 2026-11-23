# Chamber execution tracker — work packages CH-WP-01…10

**Status:** active software engineering execution plan (not a certification or authority to energize hardware)  
**Audit timestamp:** 2026-11-19 UTC (baseline); updated checkpoint: 2026-11-20  
**GUI baseline:** [main d971a34](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/commit/d971a34a425570571a68dd6e6c6e121f1a13ed65) (GUI [PR #89](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/89) merged 2026-11-19)  
**Driver baseline:** [main d22dc05](https://github.com/ami3go/VotschTechnik-climate-chamber-Python/commit/d22dc05687cac4c5cdef440fb52b05965ed3d146)  
**Canonical execution state:** this tracker and its linked GitHub issues. **Live state verification:** always refresh GitHub main, issues, open PRs, exact-head CI, and actual test evidence before marking any item complete. This table is a dated snapshot, not an automatic GitHub status feed.

## Verified reconciliation checkpoint — 2026-11-22 (software-only)

This checkpoint supersedes the historical open-state claims in dated tables below. It reports exact repository revisions; do not transfer any emulator or simulated regression result to physical chamber qualification.

| Work | Verified repository outcome | Separate remaining gate / next action |
| --- | --- | --- |
| Operational Mode H01-OPER-02 [issue #113](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/113) | **SOFTWARE CLOSED.** [PR #114](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/114) merged into `main` at `11eab83972948e090d9123b5de80d495d5cbe62f`. Accepted PR head `171639061a1d821057a983d1671832e76a4a6847`: **10/10** successful workflows, including Windows/Linux S2-02, simulated watchdog child, G04 ownership/STOP and G08 settings checks. Issue #113 closed for software scope only | **H01 physical #112 OPEN.** Site serial/limits, real STOP/restart and power/network failures, independent hardware safeguards, security and site acceptance not certified |
| Automotive standards research and profile drafts [PR #111](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/111) | **MERGED** at `796366a0671f1feefb8da7c6be617944891b744c` after **7/7** exact-head workflows on `1c4e4296d57a1ceb4585dad93be7d7140172f9b3`. Catalogue: 86 researched standards, 60 extracted methods; 85% threshold applies to **enumerated temperature-setpoint occurrences only**. Research drafts rejected by both `ProfileExecutionService` and `ProfileRunner` before controller I/O | **Never treat source catalogue, 85% or created drafts as an approved OEM method.** Research provenance is not a signed/immutable approval workflow; controlled OEM procedure, DUT constraints and physical facility qualification remain separate |
| WT32-ETH01 emulator [draft #84](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/84) | **OPEN DRAFT**, reconciled with current GUI main. Pure C++ static IPv4 mask/host/gateway/DNS validation and regression added (`emulator_protocol.cpp`, `test_emulator.cpp`); firmware TCP now retries partial sends with a finite write deadline (`src/main.cpp`). Exact final-head CI must be inspected separately; previous green runs do not qualify later edits | Do not merge until actual ESP32 board/PHY identification and FLASH, physical Ethernet including slow-client/backpressure, WDT/network reset, protocol status capture, security enrollment and independent hardware review |
| Leonardo R3 + W5500 emulator [stacked draft #88](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/88) | **OPEN DRAFT**, synced to #84. `leonardo_main.cpp` refuses a second TCP client while an operator connection is live; `leonardo_core.h` admission helper and host regression added. Exact final-head native/firmware/driver CI pending as a separate software gate | Physical Leonardo/W5500 flash, EEPROM and SPI Ethernet behavior, link-loss/recovery, WDT, STOP and network isolation NOT RUN; #88 must remain stacked behind #84 until hardware approval |
| Direct physical chamber acceptance [issue #112](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/112) | **NOT RUN on current GUI main**. Earlier historical H02 engineering observations are not current-revision qualification. [H01 operational runbook](H01_OPERATIONAL_HARDWARE_QUALIFICATION.md) exists. | Operator-issued 24 h HIL PIN; exact chamber serial and approved temperature bounds; live identity/GOOD readback, START/STOP, failure/recovery, independent safety witness, captured evidence and site sign-off |
| Windows offline / G08 / R01 | WP-01…WP-10 software/documentation scopes reconciled as closed on 21 Nov, subject to their historical evidence | Clean disconnected Windows 10/11 QA, artifact signing/key custody, independent security and LAN review, power-loss recovery and **R01 RELEASE NO-GO** |

**Software verification discipline:** all multi-minute offline suites run with [bounded watchdog](../scripts/h02_watchdog_command.py), e.g. `python scripts/h02_watchdog_command.py --timeout-s 1200 --idle-timeout-s 300 --cleanup-s 15 --log-dir test-evidence/reconciliation -- python -m pytest -q tests --ignore=tests/hardware`. A new branch/merge commit must be rechecked at its own exact head. Never contact real chamber/board from CI; no emulator tests require or imply the 24 h physical HIL PIN.

## 0. Architectural contract and scope

- Application: NiceGUI web GUI in [Chamber GUI](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI), for one Vötsch chamber. All physical instrument communication remains **exclusively through** [Vötsch Python driver](https://github.com/ami3go/VotschTechnik-climate-chamber-Python), via the existing backend adapter and server-owned G04 services. No GUI-side vendor-protocol shortcuts.
- Simulation, native driver-emulator TCP, CI, static inspection, firmware cross-build and browser tests are **software-only** even when they emulate realistic chamber responses. They do not prove physical emergency-STOP performance.
- Physical HIL **test admission** uses the operator-issued, 8-digit 24-hour PIN from [HIL PIN runbook](HIL_PIN_RUNBOOK.md): operator runs scripts/hil_pin.sh setup/reset at the bench, agent requests only that PIN and executes test tooling via scripts/hil_pin.sh run. WP-02 addresses remaining bypasses. The existing H02 signed-permit **application runtime** is not yet migrated; its release/site acceptance requirements must not be silently discarded. A PIN does not replace physical STOP, device serial identity, approved temperature envelope, G04 fencing or independently observed STOPPED.
- Prior engineering evidence may show physical H01/H02 tests passed on earlier commits; it does not certify the current GUI SHA or the emulator hardware. Final production release is **R01 NO-GO** until separately accepted.

## 1. Single actionable work queue

The GitHub issues below are the execution units. Their checklists specify precise engineering tests and disposition criteria. All issues were **created open** on 2026-11-19; update status from live GitHub rather than this snapshot.

| Seq. | Issue | Priority | Execution outcome | Dependencies / related PRs | Software status at audit | HIL/site status |
|---|---|---|---|---|---|---|
| 01 | [#90 CH-WP-01](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/90) — restore CI baseline | P0 | Root-cause Windows 3.12 combined regression, W01 failure, PIN CI; exact-main verified regression | None; source PR [#89](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/89) | **OPEN**; W01 latest main FAIL, combined CI pending | Not required; CI prohibited from using chamber |
| 02 | [#91 CH-WP-02](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/91) — complete HIL PIN admission | P0 | Harden all intended agent HIL test entry points, soak, concurrency, expiry, platform support | PR [#89](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/89) merged; merge gated by #90 | **PARTIAL**; physical GUI and direct soak admission not consistently PIN-gated | HIL admission software ≠ site acceptance |
| 03 | [#92 CH-WP-03](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/92) — safe Start/STOP/restart | P0 | Fresh GOOD/STOPPED preflight before admin lab start; deterministic lease/restart tests | PR [#87](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/87) merged; merge gated by #90 | **OPEN**; admin override bypasses normal STOPPED gate | Physical STOP/restart certification still OPEN |
| 04 | [#93 CH-WP-04](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/93) — old driver PR disposition | P1 | Compare old functions with maintained driver, implement only genuine gaps or close stale PR | Python driver [PR #1](https://github.com/ami3go/VotschTechnik-climate-chamber-Python/pull/1), merge-conflicted | **OPEN**; do not merge blindly | Physical protocol conformance remains separately qualified |
| 05 | [#94 CH-WP-05](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/94) — G07 evidence reliability | P1 | Extrema-preserving plots, accurate sample semantics, authorized checked exports, fault recovery | Existing [G07 audit](G07_A_MERGE_GATE_AUDIT.md), GUI PR #74 merged; merge gated by #90 | **PARTIAL**; fixed-stride plots and Windows recovery acceptance gaps | Power-loss/storage certification OPEN |
| 06 | [#95 CH-WP-06](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/95) — ESP32 emulator | P1 | Reconcile, review native core/driver TCP/firmware and protocol cases | GUI draft [PR #84](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/84), currently merge-conflicted | **PARTIAL**; latest head emulator CI PASS | Actual ESP32 flash, Ethernet, WDT, HIL acceptance NOT RUN |
| 07 | [#96 CH-WP-07](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/96) — Leonardo/W5500 emulator | P1 | Rebase stacked target and validate AVR build, memory budget and driver TCP | **Hard dependency #95 / PR #84**; GUI draft [PR #88](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/88) targets #84 branch | **PARTIAL**; latest 4 emulator CI jobs PASS | Actual Leonardo/W5500 board, link, WDT NOT RUN |
| 08 | [#97 CH-WP-08](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/97) — W02 offline release | P1 | Lock build backend, verify signed artifact pipeline/rollback and prepare clean-VM QA | GUI PRs #77/#80/#82 merged; CI gate #90 | **PARTIAL**; runtime closure built; builder provenance/license review incomplete | Actual publisher key ceremony, disconnected Win10/11 QA, R01 approval OPEN |
| 09 | [#98 CH-WP-09](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/98) — G08 operational security | P1 | File/line security audit, confirmed code fixes, session/WS/audit/backup/ACL tests | G08 [remaining work](G08_REMAINING_WORK.md); CI gate #90; final site QA needs #97 | **PARTIAL**; core G08 merged, acceptance incomplete | Independent security / LAN site review OPEN |
| 10 | [#99 CH-WP-10](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/99) — reconcile tracker | P1 | Current issue/PR/CI ledger, source crosslinks, maintained status discipline | Issues #90–#98; **no requirement to finish them before closing tracker issue** | **IN PROGRESS — documentation PR** | Document, never infer, pending site gates |

**PR inventory at audit:** GUI [#84](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/84) and [#88](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/88) are open **drafts**; #88 is stacked on #84. Python driver [#1](https://github.com/ami3go/VotschTechnik-climate-chamber-Python/pull/1) is open, old and merge-conflicted. GUI [#89](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/89) is merged. GitHub previously counted these PRs as open issues; new tracking issues are distinct from PR records.

### Observed CI state at audit

| Source / platform | Evidence | Verified assessment |
|---|---|---|
| GUI main d971a34, Windows packaging W01 | [run 44612119513](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/44612119513) | **FAIL**; determine failing step/root cause (#90) |
| GUI main d971a34, S2-02 combined regression | [run 44612119523](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/44612119523) | **In progress** at audit; no blanket PASS |
| Earlier GUI main 27e9c1c, Windows 3.12 S2-02 | [run 40313253568](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/40313253568) | **FAIL** (other matrix jobs passed); JUnit artifact inspection needed |
| GUI main d971a34, HIL PIN test matrix | [run 44612119576](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/44612119576) | Ubuntu/Windows Python 3.12 **PASS**, Python 3.10 jobs **queued** at audit |
| ESP32 PR #84 head 6f9015b | [run 39766079997](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/39766079997) | C++ native-driver TCP and firmware CI **PASS**; not a physical hardware PASS |
| Leonardo PR #88 head 3b02325 | [run 44288007615](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/44288007615) | Native and firmware CI **4/4 PASS**; no board qualification |
| Driver main d22dc05 | [driver Actions](https://github.com/ami3go/VotschTechnik-climate-chamber-Python/actions) | Latest recorded driver test workflows passed; update at implementation time |

Do **not** copy a historical green CI state onto later head commits; test evidence is bound to exact revisions.

## Verified implementation checkpoint — 2026-11-19

**This checkpoint supersedes only the 2026-11-19 issue/PR states in the original table above; it does not rewrite historical test evidence or grant hardware authorization.**

| WP | Source changes / outcome | Exact review or CI gate | Physical / release disposition |
|---|---|---|---|
| 01 #90 | Windows/W02 reviewed-wheelhouse drift and Playwright Ubuntu 26.04 browser runner fixed in [PR #101](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/101), **MERGED** `c54e1c7f260a2905f75e4c7ee64c7546899e69e4` | All 5 final-head PR workflows **PASS**: W01, W02, H01, H02 and combined S2-02. Main W02 PASS; main W01/S2-02 rechecks were in progress at this update | No physical HIL; #90 stays OPEN until exact-main checks close |
| 02 #91 | Direct soak PIN gate + fail-closed tests and POSIX limitations in [PR #103](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/103), HEAD rebased onto fixed main | Latest-head CI **pending**; not merged | Ordinary product GUI / signed H02 runtime policy intentionally separate; physical admission review remains OPEN |
| 03 #92 | Lab G04/G06 safety preflight and admin lease takeover fix in [PR #102](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/102), HEAD reconciled with fixed main | New exact-head regression **pending**; not merged | Physical STOP/restart acceptance OPEN |
| 04 #93 | [Driver PR #1](https://github.com/ami3go/VotschTechnik-climate-chamber-Python/pull/1) reviewed function by function and **CLOSED WITHOUT MERGE** (obsolete APIs already on driver main); [issue #93](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/93) **CLOSED** | Driver main `d22dc05` had passing driver CI; no new driver code or hardware operations | Legacy-PR disposition complete; physical gradient acceptance remains separate |
| 05 #94 | G07 measured-temperature extrema-preserving plot downsampling in [PR #104](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/104), HEAD rebased onto main | New Windows recorder/1M-sample and GUI regression **pending**; not merged | Export durability, Windows power-cut and independent evidence acceptance OPEN |
| 06 #95 | ESP32 [draft PR #84](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/84) reconciled to main at `164c060f4` using non-force merge; no firmware change | GitHub compares show **0 commits behind**, mergeable; new-head native/firmware CI pending | **DO NOT MERGE** until real board, Ethernet/WDT and independent review |
| 07 #96 | Leonardo stacked [draft PR #88](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/88) rebased onto updated #84 at `0edae55e5` | **0 commits behind** #84, new-head emulator CI pending | **DO NOT MERGE** until actual Leonardo/W5500 tests and hardware review |
| 08 #97 | W02 dependency reproducibility software fix delivered by merged #101 | Software build/verification successful, *not* certified signed Windows package | Publisher key, licenses, attested provenance, clean Win10/11 and R01 gates OPEN |
| 09 #98 | G08 NiceGUI cookie-secret filesystem validation in [PR #105](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/105), HEAD reconciled onto main | Symlink, nonregular, ownership/mode negative tests added; exact-head CI pending | LAN/NTFS, independent security assessment and release approval OPEN |
| 10 #99 | Initial tracker [PR #100](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/100) **MERGED** `fbc150f2c8d6aea70eec42956f1d47eaabd612c0`; [issue #99](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/99) **CLOSED** | All 10 issue links and documentation links verified; docs-only CI passed | Documentation closure only; other gates remain OPEN |

Software work has **not** earned R01 approval. Close each remaining issue only after its own exact final-head tests, review, merge and separately applicable HIL/site gates. The active PR branches listed above are staged and intentionally not merge-claimed while final-head CI is pending.

## Verified issue/CI reconciliation — 2026-11-20

**Current source of truth:** [GUI main `aad7bbbf8`](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/commit/aad7bbbf8fbd4a8a8200563dfd18fb19979413bf), [driver main `d22dc0568`](https://github.com/ami3go/VotschTechnik-climate-chamber-Python/commit/d22dc05687cac4c5cdef440fb52b05965ed3d146). The original 19-Nov table and checkpoint above are **historical**, not present-tense issue state. Verify live GitHub again before execution.

| WP | Live tracker issue | Verified software / PR disposition | Remaining independent gate |
|---|---|---|---|
| 01 [#90](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/90) | **CLOSED** | #101 merged; [main W01](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/44808676609) and [S2-02](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/44808676583) completed successfully on `aad7bbbf8` | No hardware implication |
| 02 [#91](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/91) | **CLOSED** | PIN admission #103 merged and issue software-only closure recorded | Existing product H02 authorization and physical bench acceptance remain separate |
| 03 [#92](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/92) | **CLOSED** | Verified STOPPED preflight #102 merged | Real STOP/restart hardware qualification not inferred |
| 04 [#93](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/93) | **CLOSED** | Maintained driver supersedes obsolete driver PR #1; closed without merge | Real gradient/output conformance requires physical evidence |
| 05 [#94](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/94) | **CLOSED** | G07 extrema-preserving plots #104 merged; [main G07 CI](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/44808676786) success | Windows crash/power-loss durability, off-device audit acceptance |
| 06 [#95](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/95) | **CLOSED** | ESP32 [draft #84](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/84) remains unmerged; [exact-head emulator CI](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/44810984040) success | Actual WT32-ETH01 board, Ethernet/WDT, independent review **NOT RUN** |
| 07 [#96](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/96) | **OPEN** | Leonardo stacked [draft #88](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/88) remains unmerged; [exact-head emulator CI](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/44813347988) success; physical runbook documented | Depends on #84; real Leonardo/W5500 flash, link recovery/WDT, GUI trust gate **NOT RUN** |
| 08 [#97](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/97) | **OPEN** | Reviewed runtime wheelhouse CI fixed via #101; builder lock, signed target policy and staging remain unfinished | Clean disconnected Win10/11, publisher signing/key custody, license approvals, R01 **NO-GO** |
| 09 [#98](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/98) | **OPEN** | Cookie-key integrity [PR #105](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/105) updated to `af2d7f6bd`: POSIX `O_NOFOLLOW`/descriptor-read fix and additional tests; **new exact-head CI pending**, no merge claim | Session/WS/ACL, off-device audit and independent security review OPEN |
| 10 [#99](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/99) | **CLOSED** | Authoritative initial tracker #100 merged; this reconciliation is PR #106, pending final CI/merge | Documentation only |

**Main CI checkpoint:** at GUI SHA `aad7bbbf8`, all eight reported latest-main workflows for the commit completed with `success` (G07, W01, S2-02, NiceGUI scaffold, discovery, profile readiness, identity, credential persistence). The older PR #105 S2-02 Windows failures **cannot** be relabeled PASS: only CI at its new head can prove the reconciliation.

**Merge policy:** PRs #84 and #88 remain hardware-gated draft by explicit acceptance contract. #105 and #106 may merge only after current exact-head checks and independent diff review. The 24-hour PIN admits operator-supervised *physical test procedures*; it is not a release authorization and it is unnecessary for offline emulators. **R01 RELEASE NO-GO.**

## Verified software closure reconciliation — 2026-11-21

**Current source of truth:** [GUI main `d24ce9842`](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/commit/d24ce9842f05a025f39f8aafbb348334cd8a0e64). Live GitHub shows tracker issues [#90](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/90) through [#99](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/99) **CLOSED** for their documented software or documentation scopes. This is not a physical, site, signing, or release closure.

| WP | Final software disposition | Independent gate that remains open |
|---|---|---|
| 01–05 | #101, #103, #102 and #104 merged; obsolete driver PR #1 closed without merge; issues #90–#94 closed with exact-revision software evidence | Any applicable device, site, evidence-storage and release acceptance remains separate |
| 06 [#95](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/95) | Software/native/firmware checks recorded; ESP32 [PR #84](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/84) deliberately remains an **OPEN DRAFT** | Actual WT32-ETH01 board flash, Ethernet/link recovery, watchdog, long-run behavior and independent hardware review **NOT RUN** |
| 07 [#96](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/96) | Software/native/firmware checks recorded; Leonardo [PR #88](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/88) deliberately remains an **OPEN DRAFT** stacked on #84 | Actual Leonardo/W5500 flash, network isolation, link recovery, watchdog, long-run behavior and GUI trust qualification **NOT RUN** |
| 08 [#97](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/97) | W02 build-foundation [PR #108](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/108) merged as [`3563d6953`](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/commit/3563d6953f6a60d20d3d0b7b22a57aefd68fa04b); all 14 accepted-head hosted checks passed. Superseded PR #107 was closed without merge | Publisher signing/key ceremony, complete license acceptance, attested provenance policy, disconnected clean Windows 10/11 QA, trusted policy distribution and R01 approval |
| 09 [#98](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/98) | G08 cookie-secret integrity [PR #105](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/105) merged as [`d24ce9842`](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/commit/d24ce9842f05a025f39f8aafbb348334cd8a0e64). Accepted head `6381702fd`: local bounded suite 92 tests + 23 subtests passed; all 12 hosted jobs passed, including Linux/Windows combined suites, W01, NiceGUI/import, credential persistence and simulated H01/Chromium | Independent security/penetration review; live LAN browser/cookie/WebSocket validation; Windows service-account and NTFS owner/DACL/reparse qualification; firewall/PKI/site acceptance; off-device audit sealing and trusted backup freshness |
| 10 [#99](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/99) | Initial authoritative tracker [PR #100](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/100) merged; #99 already closed. PR #106 is the final historical-to-current reconciliation | Documentation does not authorize hardware, signing, deployment or release |

**Open-PR boundary at reconciliation:** only emulator drafts #84 and #88 plus this documentation PR #106 were open. #84/#88 must not be merged from software evidence alone. No physical chamber, emulator board, site network, operator PIN, publisher key or release artifact was exercised for this reconciliation.

**Final software disposition:** CH-WP-01…10 are closed for their stated software/documentation scopes after exact-head validation and merge evidence. Production remains **R01 RELEASE NO-GO** until the external gates above and the release contract in section 5 are independently satisfied.

## 2. Execution dependency and sequencing

**Stage A — execute sequentially, safety first**

1. [WP-01 #90](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/90): reproduce and resolve exact-main CI red/queued jobs; capture baseline.
2. [WP-02 #91](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/91): unify operator PIN admission for automated physical HIL test entry points. Simulation requires no PIN. No expansion to production H02 without an explicit separate scope decision.
3. [WP-03 #92](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/92): harden admin override to require fresh verified STOPPED and preserve benign operator handoff.

**Stage B — branches may develop independently after the Stage A code freeze, but merges require a green exact-head baseline**

4. [WP-04 #93](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/93) driver legacy PR disposition.
5. [WP-05 #94](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/94) G07 evidence correctness.
6. [WP-06 #95](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/95) ESP32 emulator branch conflict and native protocol/firmware tests.
7. [WP-07 #96](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/96) Leonardo must follow #95/PR #84; its code must not be flattened independently onto main without intentional review.
8. [WP-08 #97](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/97) Windows signed/offline release **software** closure; physical Windows QA is separate.
9. [WP-09 #98](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/98) security code audit and corrections; certification remains external.

**Stage C — documentation convergence**

10. [WP-10 #99](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/99) is the **creation and maintenance of this tracker**, not a dependency requiring every other package to close first. Merge the docs-only tracker PR promptly, then update rows as work packages actually change state.

### Ownership boundaries and parallelism

| Stream | File/area ownership | Can run in parallel with | Coupling |
|---|---|---|---|
| Safety/HIL #91, #92 | chamber_web/hil, chamber_web/services/profile_execution.py, scripts and tests | Driver #93 / W02 #97 | Do not merge contradictory safety behavior |
| Driver #93 | Python driver repo and narrow GUI adapter tests | G07 #94, packaging #97 | GUI only delegates to driver |
| G07 #94 | persistence/runs.py, run readers, tests | Emulator #95/#96 | Coordinate G08 export auth changes |
| Emulator #95, #96 | firmware directory and simulator CI | W02 #97, G08 #98 | #96 **requires** #95 integration |
| W02 #97 | offline freeze/verification/release files | G07 #94, emulator #95 | Final G08 security QA depends on packaging |
| G08 #98 | security code, auth/WS/backup tests | Emulator #95, W02 #97 | Coordinate with G07 if touching evidence export |
| Tracker #99 | docs, README, AI execution links | All | Mergeable independently |

If file ownership overlaps, integrate serially or split by scoped files rather than allow two agents to overwrite each other.

## 3. Common acceptance and evidence model

**These are separate gates and must never be collapsed:**

| Gate | Meaning | Minimum evidence |
|---|---|---|
| CODE COMMITTED | Implementation exists on a branch | Link to commit and reviewed diff |
| CODE MERGED | PR merged into intended base | Actual merged PR URL and merge SHA; CI results separately recorded |
| SOFTWARE VERIFIED | Exact revision passed software-only unit, integration, GUI, mock/TCP and applicable firmware build checks | Named tests and counts, OS/Python, driver SHA, CI jobs, logs and watchdog results |
| HIL VERIFIED | A named test scope was physically executed on the approved device | Operator-issued PIN for test admission, serial/firmware, approved limits, raw observed readback, supervised STOP/restore, test logs and explicit result |
| SITE ACCEPTED | Qualified site or independent authority accepted a documented physical/release scope | Decision/signature/acceptance record; never inferred from a PIN or HIL test count |
| RELEASE APPROVED | R01 GO for the specific packaged artifact and deployment | W02 verified release, G08 acceptance, closed P0 issues, QA evidence, signed release decision |

No merge by itself completes HIL or release acceptance. Any failed, skipped, queued, cancelled or undocumented check is **not PASS**. A newly introduced fail-closed physical security check must have negative-path tests; no agent may bypass it to satisfy an automated test.

### Work package completion record (mandatory in issue comments and tracker updates)

- Task ID, affected repo(s), tested branch head SHA(s), reviewed diff and explicit files/lines.
- PR URL, actual merge SHA and whether the PR is still draft/open/closed.
- Per-platform test commands, pass/fail/skip counts, CI run/job links and watchdog exit.
- For external driver changes, pinned driver revision and GUI adapter contract checks.
- Unresolved BLOCKER/HIGH findings, dependency status, risk owner and next safe step.
- **Hardware field:** NOT RUN / ENGINEERING HIL PASS / HIL FAIL / SITE ACCEPTED; cite exact independent evidence. Do not report CI PASS as HIL PASS.
- Final disposition: SOFTWARE CLOSED; OPEN SOFTWARE; BLOCKED EXTERNAL; or RELEASE NO-GO. Never quietly drop external blockers when closing a code issue.

## 4. Watchdog and no-hardware rules for every agent

For software-only work likely to run long, use the repository's existing standard-library command watchdog with a finite wall-clock deadline and bounded cleanup. Example (from GUI repository root):

    python scripts/h02_watchdog_command.py \
      --timeout-s 900 --idle-timeout-s 300 --cleanup-s 10 \
      --log-dir test-evidence/CH-WP-01 \
      -- python -m pytest -q tests --ignore=tests/hardware

Use an appropriate timeout for the test duration, and omit idle timeout or supply a **trusted** heartbeat if a legitimate compiler is silent. GitHub Actions jobs also need a finite maximum duration. A watchdog exit of 124/125, missing logs, subprocess termination or absent test summary is NOT a successful test. Review the process cleanup evidence before retrying.

**For physical HIL (not automatically performed here):** operator issues the PIN interactively; agent uses it for test admission, checks exclusive bench ownership, pinned serial and approved software temperature envelope; an independent GOOD/STOPPED readback is required before a new start. Any long physical test requires an **application-level bounded deadline, live telemetry/watchdog supervision, a controlled STOP request and a fresh authoritative STOPPED readback**. Do not apply a blind process-kill watchdog to an energized chamber. Observe and respect existing physical emergency controls and human site restrictions. Explicitly distinguish acceptance of a simulator from real device qualification.

**Forbidden shortcuts:** asking agent to issue/reset its own PIN; accepting a copied or expired PIN; deriving device identity from an untrusted emulator as if it were a certified chamber; using a GUI-owned raw S!MPAC socket; weakening UNKNOWN/FAULT or STOP barriers; accepting stale telemetry as proof of STOPPED; silently skipping failures or claiming HIL from CI.

## 5. Release and non-software handoff

Even after WP-01…09 code merges, the following are independently OPEN unless new direct evidence exists:

- Site hardware inventory, controller limits and signed/approved model-specific hazard envelope. See [H01 hardware checklist](H01_HARDWARE_ACCEPTANCE_CHECKLIST.md).
- Final physical H02 profile acceptance, auxiliary/gradient baseline/restoration (if those options are enabled), real controller STOP/fault behavior and approved return-to-baseline. Earlier physical tests are engineering evidence for their **historical** SHAs only.
- Actual WT32-ETH01 and Leonardo/W5500 board identification, wiring/flash, LAN link loss/recovery, watchdog resets and long-run stability. Draft PR #84/#88 software builds cannot close these gates.
- Disconnected Windows 10/11 clean-machine installation, power/restart, non-admin NTFS ACLs, backup/upgrade/rollback, final publisher signing ceremony and trusted policy distribution.
- Independent G08 security assessment, site/network deployment approval, G07 storage integrity acceptance and the signed R01 release decision.

**Final production R01: NO-GO.** The PIN-only simplification is *operator test admission*, not production certification.

## 6. Tracker maintenance and authority precedence

1. Read this tracker first for active task sequencing; read linked issues for acceptance details and action ownership.
2. Refresh live GitHub issue states, branch heads, PR base/head, exact-head CI, actual merged state and device/site evidence before changing any status. Confirm the branch or commit is the one cited.
3. Update tracker status only after evidence is linked. A PR may be merged while the work package remains PARTIAL because a mandatory HIL or external qualification gate is not satisfied.
4. For new work, create a distinct issue with file:line evidence, test matrix and rollback/safety scope; add its ID and dependency to this tracker, rather than editing unrelated historical plans into a misleading current queue.
5. Historical documents remain valid design, test and release **contracts**. Their old dates/status tables are not live implementation state. In particular consult [Stage 2 plan](STAGE_2_PILOT_READINESS_PLAN.md), [readiness findings](READINESS_FINDINGS.md), [remaining development scope](REMAINING_DEVELOPMENT_TASKS.md), [W02 release ledger](W02_OFFLINE_RELEASE.md), [G08 security tasks](G08_REMAINING_WORK.md) and [HIL PIN runbook](HIL_PIN_RUNBOOK.md).
6. WP-10 #99 can close once this tracker PR is merged, links verified, and README/AGENTS point here. It does **not** certify or close any other WP.

**Prepared from:** GitHub GUI/driver PR and issue lists, main source tree, source-level safety/evidence review and current Actions states on 2026-11-19. The execution ledger is intentionally conservative where site/hardware evidence does not exist.
