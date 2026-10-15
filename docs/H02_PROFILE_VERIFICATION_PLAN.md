# H02 — Physical profile execution and verification

**Status (2026-10-15): PARTIAL IMPLEMENTATION / PHYSICAL NO-GO.**

Inspected GUI main 875c1e078578ca52ee41461383ed582544cd717f and driver main 9323e3701f3befedcc23b45170a851fd327f0bcc. Existing GUI PRs #27, #28, #29, #30, #34, #36, #37 and #38 are merged. These SHAs are the inspection baseline, not authorization to operate hardware.

## Safety boundaries

G06 ProfileRunner currently rejects non-simulation identity, and remains unchanged. H01 manual HIL opt-in does not authorize G06 profiles. Physical outputs/gradient changes from profile v2 remain denied. Physical tests NOT RUN. Separate H02-specific signed site permit and an independent safety review are mandatory.

## Implemented on H02 branch

- H02 signed site admission *preflight* primitive, not connected to physical execution: Ed25519 signature using administrator-provisioned trusted public key, exact H02 scope, chamber serial, immutable profile digest, exact GUI/driver commits, named operator and witness, specimen restrictions, Celsius envelope, validity period, and approved watchdog configuration.
- Explicit fail-closed live-check structure for G04 ownership/stopped state, G07 writable reconciled storage, G08 authorization, on-site staff, STOP readiness, and supervisor presence. Integration MUST derive checks from trusted services, never client-supplied booleans.
- Cross-platform independent-process test command watchdog with monotonic deadline, heartbeat/output stall timeouts, process group kill, nonzero timeout exit, PID and timestamped stdout/stderr/JSONL evidence.
- Unit/fault-injection tests and proposed Ubuntu/Windows Python 3.10/3.12 + existing Chromium simulation CI.

No implementation of physical command dispatch is included, by design. This initial foundation is not physical admission; production configuration still does not create a ProfileRunner.

## Required closure phases

| Phase | Gate | State |
|---|---|---|
| Physical admission | Signed permit, G04/G07/G08 live service binding, checks before every write | Preflight validator only; INCOMPLETE |
| G06/G04 runtime | Authoritative ramp convergence, profile transitions, exclusive control, STOP priority, finite command timeouts | OPEN |
| G07 runtime | Composition-root EventSink, immutable snapshots, durable intent before writes, observed setpoint vs target, recorder failure STOP/UNKNOWN | Existing mock integration only; OPEN |
| Separate physical watchdog | Mutual bounded heartbeats, independent liveness, approved single G04 STOP request, bounded verification and restart latch | BLOCKER |
| Web/GUI | Authorized execution controls, multiple sessions, revocation, run state and evidence export | OPEN |
| Simulation verification | One/multi-step, dwell/stabilize, pause, blocked I/O, disk full, crashes, reconciling and watchdog fault injection | Partial existing suites plus new tests |
| Windows/Linux | Python 3.10/3.12, W02 packaging and real Chromium | Proposed CI, results unverified |
| Site permit and intrusive test permits | Explicit independently signed H02 method, staffed/observed test, model/firmware policy | ABSENT |
| Physical acceptance | Approved short run, fresh external STOP evidence, G07 manifest, signed witness review | NOT RUN |

## Physical HIL acceptance procedure (only AFTER approval)

Capture exact deployed commits, chamber serial/model/firmware and operating envelope, site method and signatures, immutable profile checksum, UTC/monotonic timing and watchdog config. Independently verify STOPPED before writes; perform one short authorized step and small permitted ramp-aware target change; record fresh measured/observed setpoint vs intended target, G04 generations, step lifecycle, G07 sequence/sample indices, STOP intent and independent verification. Verify immutable manifest/CSV SHA-256 and return to site-approved stopped baseline with physical witness. Prohibit unattended execution.

Power interruption, intentional STOP failure, process kill, disconnect and sensor fault injection require EXTRA hazard review and permission. H01 manual soak is not substitute evidence. UNKNOWN after unverified STOP; NEVER auto-resume.

## Results ledger

| Area | Result |
|---|---|
| Signed H02 validator and watchdog tests | Added; CI result pending |
| Physical execution implementation | NOT IMPLEMENTED; G06 simulation-only |
| G07 physical composition | NOT IMPLEMENTED |
| Independent physical watchdog | NOT IMPLEMENTED, blocking |
| Web/Chromium full H02 scenarios | NOT RUN; existing H01 smoke scheduled |
| Site H02 authorization | NOT PRESENT |
| Actual hardware tests | NOT RUN |
| Physical execution decision | **NO-GO** |

Software merge alone never enables any new physical action. No independent human safety assessment is asserted by this document.
