# H02 — Physical profile execution and verification

**Current status (2026-10-21): ENGINEERING PHYSICAL PROFILE PASS EVIDENCED;
INDEPENDENT/SITE ACCEPTANCE AND R01 RELEASE REMAIN NO-GO.**

The successful run `60e8f4da-ea08-4806-9c5c-1c2124f89eb0` tested GUI
`a0ecf17414cc7d3f4847f15aabcb9cd0692396f4` and driver
`9323e3701f3befedcc23b45170a851fd327f0bcc` under a signed, scope-specific
permit. It completed all five steps, recorded 227 G07 events and 198 samples,
disarmed the independent watchdog cleanly, left no restart latch and ended with
fresh `GOOD · STOPPED` readback. See the [result](H02_PHYSICAL_PROFILE_RESULT_2026-10-20.md)
and [controlled evidence](../hil-evidence/h02-v3-2026-10-20/README.md).
The site acceptance form remains unsigned. The historical foundation status
below is retained to explain the implementation sequence.

## Historical foundation snapshot — 2026-10-18

Inspected GUI main 875c1e078578ca52ee41461383ed582544cd717f and driver main 9323e3701f3befedcc23b45170a851fd327f0bcc. Existing GUI PRs #27, #28, #29, #30, #34, #36, #37 and #38 are merged. These SHAs are the inspection baseline, not authorization to operate hardware.

### Safety boundaries at that snapshot

At that snapshot G06 ProfileRunner rejected non-simulation identity. H01 manual
HIL opt-in did not authorize G06 profiles. Physical outputs/gradient changes
from profile v2 remained denied, and physical tests had not run. A separate
H02-specific signed site permit and independent safety review were mandatory.

### Implemented on the original H02 branch

- H02 signed site admission *preflight* primitive, not connected to physical execution: Ed25519 signature using administrator-provisioned trusted public key, exact H02 scope, chamber serial, immutable profile digest, exact GUI/driver commits, named operator and witness, specimen restrictions, Celsius envelope, validity period, and approved watchdog configuration.
- Explicit fail-closed live-check structure for G04 ownership/stopped state, G07 writable reconciled storage, G08 authorization, on-site staff, STOP readiness, and supervisor presence. Integration MUST derive checks from trusted services, never client-supplied booleans.
- Cross-platform independent-process test command watchdog with monotonic deadline, heartbeat/output stall timeouts, process group kill, nonzero timeout exit, PID and timestamped stdout/stderr/JSONL evidence.
- Unit/fault-injection tests and proposed Ubuntu/Windows Python 3.10/3.12 + existing Chromium simulation CI.

No implementation of physical command dispatch is included, by design. This initial foundation is not physical admission; production configuration still does not create a ProfileRunner.

### Branch integration and local verification (2026-10-17)

The H02 branch was integrated with GUI main `1c324af` (factory administrator credentials, PR #49) in merge commit `9f51492`. The only conflict, in `docs/DEVELOPMENT_SEQUENCE.md`, was resolved by keeping both progress entries. The merge does not connect the H02 preflight to production: no composition root creates a ProfileRunner for physical execution.

Local software verification after the merge (Linux, CPython 3.12.15):

- `tests/test_h02_profile_admission.py` + `tests/test_h02_watchdog.py`: 9 tests OK.
- `tests/test_profile_runner.py` 38 OK, `tests/test_run_recording_integration.py` 4 OK, `tests/test_h01_full_stack.py` 10 OK, `tests/test_h01_simulation.py` 9 OK, `tests/test_w02_release.py` 24 OK.
- `python -m compileall -q chamber_web main.py scripts/h02_watchdog_command.py` OK; `ruff` clean on the H02 files.
- `scripts/h02_watchdog_command.py` produced valid PID/timestamped stdout/stderr/JSONL evidence for a clean child exit (exit code 0).

Branch CI (`h02-simulation-ci.yml`, Ubuntu/Windows Python 3.10/3.12 and Chromium) passed on the merged head: [PR #39](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/39) merged 2026-10-18 as `1dae5ade00f67318f01c763e395f0e85f5310c6a` with all checks green. These are software-only results: physical HIL, H02 site permit and independent review remain ABSENT/BLOCKED, and the physical decision below is unchanged.

## Closure phases — current status

| Phase | Gate | State |
|---|---|---|
| Physical admission | Signed permit, G04/G07/G08 live service binding, checks before every write | IMPLEMENTED; exercised on physical run |
| G06/G04 runtime | Authoritative ramp convergence, profile transitions, exclusive control, STOP priority, finite command timeouts | ENGINEERING PHYSICAL PASS for tested profile |
| G07 runtime | Composition-root EventSink, immutable snapshots, durable intent before writes, observed setpoint vs target, recorder failure STOP/UNKNOWN | 227-event/198-sample physical record verified and preserved |
| Separate physical watchdog | Mutual bounded heartbeats, independent liveness, approved single G04 STOP request, bounded verification and restart latch | IMPLEMENTED; clean v3 arm/disarm evidenced after two fail-closed corrections |
| Web/GUI | Authorized execution controls, multiple sessions, revocation, run state and evidence export | IMPLEMENTED for tested workflow; broader pilot usability remains open |
| Simulation verification | One/multi-step, dwell/stabilize, blocked I/O, crashes, reconciliation and watchdog fault injection | Full local suite passed before physical run |
| Windows/Linux | Python 3.10/3.12, W02 packaging and real Chromium | Software CI history exists; W02 clean-airgap release remains open |
| Site permit and intrusive test permits | Explicit signed H02 method, staffed/observed test, model/firmware policy | Run-specific permit PRESENT; no authorization for other/intrusive tests |
| Physical acceptance | Approved short run, fresh STOP evidence, G07 manifest, signed witness review | TECHNICAL RUN PASS; human acceptance signatures PENDING |

## Physical HIL acceptance procedure (only AFTER approval)

Capture exact deployed commits, chamber serial/model/firmware and operating envelope, site method and signatures, immutable profile checksum, UTC/monotonic timing and watchdog config. Independently verify STOPPED before writes; perform one short authorized step and small permitted ramp-aware target change; record fresh measured/observed setpoint vs intended target, G04 generations, step lifecycle, G07 sequence/sample indices, STOP intent and independent verification. Verify immutable manifest/CSV SHA-256 and return to site-approved stopped baseline with physical witness. Prohibit unattended execution.

Power interruption, intentional STOP failure, process kill, disconnect and sensor fault injection require EXTRA hazard review and permission. H01 manual soak is not substitute evidence. UNKNOWN after unverified STOP; NEVER auto-resume.

## Results ledger

| Area | Result |
|---|---|
| Signed H02 validator and watchdog tests | Added; merged via PR #39 (`1dae5ad`, 2026-10-18) with green Ubuntu/Windows 3.10/3.12 + Chromium CI; local Linux 3.12 green 2026-10-17 |
| Physical execution implementation | IMPLEMENTED and exercised at tested revision `a0ecf17` |
| G07 physical composition | PASS for run `60e8f4da-ea08-4806-9c5c-1c2124f89eb0`; raw artifacts retained |
| Independent physical watchdog | PASS for v3 run; matching arm/disarm, no v3 fault/latch |
| Web/Chromium full H02 scenario | Physical web workflow completed; screenshots retained |
| Site H02 authorization | Run-specific signed permit retained; formal acceptance signatures pending |
| Actual hardware test | **ENGINEERING PASS** on 2026-10-20 |
| Physical execution decision | Permit-scoped engineering test complete; unrestricted/pilot/production **NO-GO** pending separate approvals |

Software merge or this single run never enables unrestricted physical action.
No independent human safety assessment is asserted by this document.
