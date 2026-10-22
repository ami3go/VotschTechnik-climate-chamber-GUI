# Stage 2 — Pre-production hardening and controlled pilot readiness

**Plan revision:** 1.3 (2026-10-21 — S2-02/S2-03 package status merged with the H02 physical-pass evidence)  
**Design stage:** **STAGE 2 ACTIVE — engineering and pilot preparation**  
**Prior milestone:** H01 supervised manual-control HIL executed; 8/8 physical tests PASS (2026-10-19).  
**Site acceptance:** **PENDING DOCUMENTED SIGNATURES**.  
**H02 physical profile engineering test:** **PASS EVIDENCED (2026-10-20 at `a0ecf17`; repeated 2026-10-21 at `74a816d`)**; independent/site acceptance signatures pending.  
**R01 production release:** **NO-GO**.  
**GUI tested:** `a0ecf17414cc7d3f4847f15aabcb9cd0692396f4` (2026-10-20), `74a816d9d9bbb7acbb901334ef457dbc416f7641` (2026-10-21); S2-02 combined regression baseline inspected at `014456bfa2604e1bdf8b21207bbbe598d5ba03dc`.  
**External driver tested:** `9323e3701f3befedcc23b45170a851fd327f0bcc` (physical HIL runs); driver PR #5 inspected at `b56cfbd54570e66cddf83106505487d3b19d9677`.
**Scope:** one Vötsch chamber, isolated/local network, NiceGUI web UI.

> **Engineering-stage advancement is not equipment authorization.** The owner reports HIL verification complete, and the repository records passing H01 manual-control tests. Preserve the signed-site, H02 physical-profile, operational security and W02 release gates independently. This plan does not request any live hardware test or unreviewed control action.

## 1. Transition decision and evidence

| Aspect | Verifiable repository status | Next-stage disposition |
|---|---|---|
| H01 manual functional HIL | [PR #60](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/60), 2026-10-19: `tests/hardware` 8/8 PASS, 132.6 s, VT4011 physical chamber; STOP during ramp and real-browser path exercised. Details: [development sequence](DEVELOPMENT_SEQUENCE.md). | **Technical test execution complete** for the recorded eight cases; preserve raw JUnit/timeline and site record. |
| Hardware evidence provenance | H01 and H02 raw evidence, screenshots and checksums are indexed under `hil-evidence/`; no completed human acceptance form is in the repository. | **Technical evidence retained; human signoff pending**; no inference from test count to certification. |
| H02 signed-permit runtime | H02-B/C runtime and watchdog were corrected and tested on the physical chamber at GUI `a0ecf17`; run `60e8f4da-ea08-4806-9c5c-1c2124f89eb0` completed with clean disarm and final STOPPED readback. Repeated 2026-10-21 at GUI `74a816d` under permit `H02-2026-10-21-01`: run `5be68792-77f7-471b-946c-20558f1e6502`, 5/5 steps, 200/200 GOOD samples, audited pre-run STOP reconciliation, clean `RUN_ARM`/`RUN_DISARM`, final `GOOD · STOPPED`. | **Engineering physical test PASS**; independent reviewer/site acceptance remains open. |
| Manual operator experience | GUI PRs #68, #69 merged: routine verified Start/Stop/Start; retained/manual auto-claim operator lease. | Move to pilot usability and fault handling evaluation. |
| Profile UX | GUI PR #70 merged: saved profile selection, operator-to-G06 handoff and repeat run after verified STOP. | Test on **simulator** and in specifically authorized H02 scope; not proof of real profile execution. |
| Driver integration | Driver PR #5 merged; GUI uses the external driver exclusively through `VotschBackend`. | Keep exact pin; verify clean offline installation and unchanged driver communication contract. |
| G07 recording / G08 security | Server-owned G07 journals/history and G08 role/profile infrastructure implemented. | Operational audit, backup, fault/recovery and security acceptance still pending. |
| W02 Windows offline release | Signed bundle design and CI build foundation exist. | Complete cryptographic provenance, offline Win10/Win11 clean-VM deployment and rollback tests. |
| R01 | No site-signed production approval. | **NO-GO** until every applicable gate in §4 closes. |

**What the existing HIL proves:** supervised functional control of the actual unit with a limited software envelope and selected STOP/readback paths.

**What it does *not* prove:** final signed site equipment/safety acceptance,
power-cut and worst-case failure handling, certified gradient/auxiliary output
operation, long-duration unattended operation, Windows air-gap release, LAN
security accreditation or production certification.

### Gate handoff record

- **Stage 1 (functional HIL):** engineering test result = **PASS** for the eight recorded cases; independent physical acceptance = **PENDING**.
- **Stage 2 (hardening/pilot readiness):** **ACTIVE NOW**; software and documentation can progress without HIL signatures, but live tests still require their own permits.
- **Stage 3 (controlled on-site pilot):** **CONDITIONAL GO**, only after a signed pilot test method, operator/witness coverage, reviewed site limits and deployment controls for the exact scope.
- **Stage 4 (R01 release):** **NO-GO**, requires all relevant site, software, security and W02 approvals; cannot be auto-unlocked by a CI job or UI flag.

## 2. Target design for Stage 2

```text
Browser (NiceGUI Dashboard / Profiles / History / Admin)
       | authenticated session + per-mutation CSRF/role/audit
Server-owned services: G03 immutable revisions / G05 manual control
       | G06 profile runner / G07 recorder and recovery
       | G08 security policy / H02 permit + supervision
Single G04 ChamberManager -> STOP fence / generation / lease
       |
VotschBackend (the ONLY GUI adapter for physical communication)
       |
Pinned VotschTechnikClimateChamber external Python driver
       |
One approved Vötsch chamber (opt-in; signed site scope only)

W02 Windows offline packaging + local launcher + backup/rollback
External physical emergency-stop and on-site supervision (not the web STOP)
```

Retain **one live physical controller** per deployment, generic Python packages at repository root, one shared G06 runner, no generic GUI vendor wire commands, and no browser-owned equipment state. Do not introduce a parallel chamber service, alternate transport driver, automatic post-crash restart, or multi-chamber orchestration in Stage 2.

### Operating modes

- **Simulation:** default, CI and development use; no physical connection.
- **Isolated LAN pilot:** optional site-approved local deployment, with configured host/origin/client access and operator roles. Security-profile convenience (including persistent login) must not be mistaken for site approval; factory credentials should be rotated, logged and acknowledged as a security risk. Credential warnings are not an alternate physical authorization.
- **Physical supervised HIL:** remains opt-in with pinned model/serial/temperature envelope, approved on-site STOP readiness, and an H02 scope-specific signed permit + independent watchdog for any scripted physical profile.
- **Released production:** disabled pending R01 signed approval.

## 3. Next work packages and implementation order

| Order | Package / priority | Deliverable and acceptance test | Prerequisite |
|---|---|---|---|
| 1 | **S2-01 HIL evidence closure** / P0 | Ingest existing *unaltered* H01 raw JUnit, timeline, environment, exact revisions, readback screenshots/logs, deviation record and operator/witness signoffs into a controlled evidence index. Cross-reference each case; flag any missing items. No new physical commands. | Completed H01 session evidence + site authority |
| 2 | **S2-02 Combined regression baseline** / P0 | Exact-main Windows/Linux Python tests, NiceGUI/Chromium test, G04 STOP/races, G05 lease transitions, G06 repeat profiles, G07 crash journal, G08 permissions and H02 simulated watchdog loss, with deterministic evidence. | PRs #68–#70 merged |
| 3 | **S2-03 W02 offline signed bundle** / P0 | Build reproducible frozen Windows x64 package with complete offline wheel/dependency closure, approved SBOM/licenses, independent trusted Ed25519 verification, build provenance and reproducible file inventory. No runtime downloads. | Existing W01/W02 foundation |
| 4 | **S2-04 Installation/upgrade/recovery** / P0 | Clean air-gapped Win10/Win11 VM acceptance: fresh install, local web access, service restart, backup/restore of profiles/credentials/journals, rollback, crash recovery, shutdown without false STOPPED, non-admin OS account/NTFS ACL proof. | S2-03 |
| 5 | **S2-05 G07 evidence and operations** / P1 | Profile/manually initiated runs consistently recorded; exports are authorized, indexed, SHA-verified, and retain measured/observed values; corruption/ENOSPC/rollback fail closed with documented recovery. | G07, G08, S2-02 |
| 6 | **S2-06 G08 operational security acceptance** / P0 | Independent deployment review of local/LAN origins, host/ACL/firewall/TLS assumptions, role separation, sessions, credentials, reset script, audit export, backups and recovery. Resolve HIGH findings; document accepted isolated-LAN residual risks. | S2-03/04 for final deployment check |
| 7 | **S2-07 H02 physical-profile acceptance** / P0 physical | Only under a *new, separately signed H02 permit*: short immutable-revision run, independent external STOPPED readback, watchdog heartbeat/abort evidence, sample and journal fidelity, witness record, return to approved baseline. Additional disconnect, fault, power tests require distinct approvals. | S2-01 site policy + S2-02 + H02 permit |
| 8 | **S2-08 Pilot usability and supervised soak** / P1 physical | Named operator/witness exercise normal manual controls, profile selection, repeat Start/Stop, browser reconnect, warning clarity, durable data and recovery on the approved host; accept deviations and issue resolution. Exclude unapproved dangerous faults. | S2-03/04/05/06 and S2-07 where physical profiles are in scope |
| 9 | **S2-09 R01 release candidate decision** / P0 | Version/tag/release manifest, signed decision memo with all applicable gate signoffs, unresolved risks/waivers, deploy/run/rollback guide and designated site owner. **NO-GO** if any critical item remains. | All applicable work packages |

**Optional/deferred:** H03 manufacturer typed auxiliary outputs, gradients and output restoration require verified OEM capabilities, signed baseline/restoration policy and their own HIL acceptance. Do **not** make an unapproved gradient or output API a hidden prerequisite for safe temperature-only v1 operation; leave the feature unavailable. Multi-chamber remains out of scope.

### Package status — 2026-10-21

| Package | State | Note |
|---|---|---|
| S2-01 HIL evidence closure | **NOT DELIVERED** | Blocked on the site authority and the raw H01 evidence; no new physical command was issued. |
| S2-02 Combined regression baseline | **DELIVERED — implemented + simulation-tested** | PR [#73](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/73) merged `014456b`. Added the order-independent combined simulation job (Ubuntu 3.12, Windows 3.10/3.12), committed the controlled evidence record, repaired the `web-gui-demo.yml` workflow that had produced **zero jobs on every `main` push since 2026-10-19**, and fixed a G05 defect that refused a legitimate operator Start after a verified STOP. `tests/hardware/` **NOT RUN**; no chamber connected. |
| S2-03 W02 offline signed bundle | **PARTIAL — complete air-gap dependency closure delivered** | PR [#77](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/77) merged `bcdade3` and PR [#80](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/80) merged `747aee3`. The frozen Windows runtime closure is now hash-locked and **complete**: `requirements-w02-runtime.lock` pins 50 `win_amd64`/CPython 3.12 distributions, including the vendored external Vötsch driver built reproducibly from its pinned revision and the driver's own dependency `colorama`; the runtime SBOM is derived from that closure instead of the build host; every requirement of every closure member is proven to be inside the closure; and a Windows CI job reproduces the closure and installs it with `--no-index --require-hashes` on `main` as well as on pull requests. PR [#82](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/82) merged `fcdc9f9` then built the **frozen bundle itself from that closure** with no index access, and the bundle reports the runtime closure in its SBOM, license inventory and provenance. Still open: the signed artifact with a site publisher key, license approval (every row still `REVIEW_REQUIRED`), attested build provenance, the hash-locked build backend (PyInstaller is still installed from connected pip), the independent supply-chain review and the disconnected clean-VM acceptance (S2-04). |
| S2-04 Installation/upgrade/recovery | **NOT STARTED** | Depends on S2-03. |
| S2-05 G07 evidence and operations | **PARTIAL** | G07 journal readers merged (#74); authorized, SHA-verified exports and corruption/ENOSPC recovery remain open. |
| S2-06 G08 operational security acceptance | **NOT STARTED** | Independent deployment review; starts after S2-03/04 deployment evidence. |
| S2-07 H02 physical-profile acceptance | **NOT RUN — NO-GO** | Still blocked by a separately signed H02 permit and the S2-01 site policy. |
| S2-08 Pilot usability and supervised soak | **NOT STARTED** | Depends on S2-03/04/05/06 and S2-07. |
| S2-09 R01 release candidate decision | **NO-GO** | Unchanged; no S2-02 result advances the release decision. |

**S2-02 changed no device authorization.** The delivery is simulation-only and
does not approve physical HIL, a W02 release, operational G08 acceptance or
Stage 3 pilot use. Detailed status and the findings closed are recorded in the
[readiness ledger](READINESS_FINDINGS.md#stage-2-package-status--2026-10-21) and
in [test-evidence/s2-02/S2_02_REPORT.md](../test-evidence/s2-02/S2_02_REPORT.md).

### Parallel execution with ownership

- **Track A, evidence + safety:** S2-01 → S2-07 → S2-08. Owns site evidence; real-device work stays **blocked by scoped signed authorization**.
- **Track B, Windows delivery:** S2-03 → S2-04. Can proceed offline/in clean VMs in parallel with site documentation.
- **Track C, QA/data/security:** S2-02 and S2-05 in parallel; S2-06 begins policy review immediately and closes after Windows deploy evidence.
- **Integration owner:** merges one domain at a time after exact-head CI and review; refreshes [readiness ledger](READINESS_FINDINGS.md), this document, and the [development sequence](DEVELOPMENT_SEQUENCE.md).

## 4. Stage 2 exit gates (traceable GO/NO-GO)

| Gate | Evidence required | Current |
|---|---|---|
| H01 signed acceptance | Named approver + operator/witness + scope, exact serial, dated raw report and deviation closure; valid site-certified temperature/STOP policy | **OPEN: user reports complete, repository signature not present** |
| H02 if physical profiles enabled | Signed *H02-specific* site permit, exact profile digest/GUI/driver revisions, witnessed run, separate watchdog and G07 independent readback evidence | **TECHNICAL PASS EVIDENCED** for the 2026-10-20 run at `a0ecf17` and the 2026-10-21 run at `74a816d`; independent/site acceptance signatures **OPEN** |
| G04/G05/G06 safe control | Simulator races and browser workflows plus approved site physical scope; no unverified/competing restart | **PARTIAL: code/CI and recorded manual HIL** — S2-02 added the combined simulation baseline and closed a G05 refusal of an operator Start after a verified STOP; the approved *site physical scope* is still absent |
| G07 evidence and recovery | Storage/readback/audit/export integrity, crash/restart evidence on target Windows storage | **OPEN** |
| G08 local/LAN operations | Site-reviewed security profile, bounded network exposure, credential handling, ACL, independent review | **OPEN** |
| W02 delivery | Reproducible signed offline bundle, trusted verifier, Win10/11 clean-airgap deployment and rollback | **OPEN** |
| H03 outputs/gradients (if enabled) | OEM certified units/limits, baseline and restoration tests, additional signed on-device scope | **DEFERRED / DISABLED** |
| R01 | Final signed release GO/NO-GO and approved pilot handover | **NO-GO** |

A package may be software-complete before its site evidence is complete. Always report these as different states: **implemented**, **simulation-tested**, **hardware-tested**, **independently approved**, **released**. Retain original immutable raw evidence outside Git when sensitive; store hashes, indexed references and redacted review metadata in the repository.

## 5. Watchdog, regression and evidence contracts

For every task expected to run long or emit extensive output, use the existing
`python scripts/h02_watchdog_command.py --timeout-s <finite> --idle-timeout-s <finite> --log-dir <evidence-dir> -- <command>`
wrapper where supported. GitHub Actions jobs must also have finite `timeout-minutes`.
Preserve exit codes, stdout/stderr, UTC timestamps, wall/monotonic durations,
artifacts and any failure/timeout. A watchdog-killed job is **FAIL**, not a
successful partial run. Do not use this development command wrapper as a
substitute for the independent H02-C physical supervisor.

Per PR: base on current `main`; inspect exact diffs, permissions and driver
boundary; test focused unit/integration plus relevant Windows/Chromium/HIL
**simulation** suites; obtain independent review for safety-relevant changes;
merge only if configured checks and approvals pass; update status and affected
manuals. No GitHub CI shall connect to actual hardware. Hardware test scripts
require a separate written site permit for that specific scope.

## 6. Immediate next action

**Complete S2-01 human evidence signoff and S2-02 exact-head regression; continue
S2-03 offline packaging work.** The H02 engineering run is now evidenced, but
it does not declare H01/H02 independently accepted or authorize unrestricted
physical profiles. Complete the
[H01 equipment/acceptance checklist](H01_HARDWARE_ACCEPTANCE_CHECKLIST.md) and
the prepared [H02 site acceptance record](H02_SITE_ACCEPTANCE_2026-10-21.md)
(the 2026-10-20 record remains open as well). Every later physical profile still
needs a new signed permit bound to its exact clean revision.

**No changes to device-side authorization, STOP safety, signed-site controls,
or production-enable flags are authorized by this design transition.**
