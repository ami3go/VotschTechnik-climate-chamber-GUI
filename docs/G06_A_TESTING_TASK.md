# G06-A — Profile runner testing and acceptance task

**Task state:** OPEN — integration/acceptance testing required on current `main`.  
**Scope:** Software simulation **only**. Physical Vötsch equipment, networked hardware and HIL operation **must remain disabled**.  
**Prepared:** 2026-10-13.  
**Implementation:** [merged PR #24](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/24); original source head `ef2e602b3d56b21ae1e7c9b5bfd2a86f817c690f`; merge commit `28377a4eb0c7f651063c87ad5789810b036380fe`.  
**Contract:** [G06_A_PROFILE_RUNNER_CONTRACT.md](G06_A_PROFILE_RUNNER_CONTRACT.md). Also read [P00_DECISION_CONTRACTS.md](P00_DECISION_CONTRACTS.md), [G04_A_CONTROLLER_CONTRACT.md](G04_A_CONTROLLER_CONTRACT.md), [CHAMBER_ABSTRACTION_CONTRACT.md](CHAMBER_ABSTRACTION_CONTRACT.md), [G08_MIN_SECURITY.md](G08_MIN_SECURITY.md).  
**Related active integration PRs at task creation:** G07-A [#27](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/27), G05 [#28](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/28), G08-full [#29](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/29). Review their updated state at execution time; they are **not** implicit prerequisites to the G06 unit tests.

## Baseline already established — not a substitute for new testing

The exact final source head of merged G06-A PR #24 passed these **2026-10-12** Windows GitHub Actions checks:
- [G06 runner regression, Python 3.10/3.12](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38289290272) — SUCCESS.
- [NiceGUI demo regression](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38289290361) — SUCCESS.
- [W01 frozen simulated Windows package](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38289290197) — SUCCESS.

These runs validate **that earlier code head only**, not all subsequent `main` merges, pending G05/G07/G08 integration, physical STOP or hardware limits. No tasks below should be marked complete without recorded new evidence.

## 1. Baseline, isolation and static architecture

- [ ] Check out fresh latest `main`, record exact commit SHA, Python version(s), OS/build, dependencies, executor and test date. Confirm G06-A is present on `main` and `git status` is clean.
- [ ] Confirm one configured/chamber-owned G04 controller per deployment and that physical backend connect is rejected **before** any adapter I/O. No port, socket, live address, or physical driver instance is allowed in these tests.
- [ ] Audit `chamber_web/execution/profile_runner.py` and imports: no direct device adapter/driver usage, vendor/model conditionals, raw sockets, browser state, NiceGUI-owned execution loop, or second-chamber scheduler. Commands must go via `ChamberManager`/G04; STOP via G04 fencing.
- [ ] Verify G03 immutable profile revisions and capability/identity snapshots are bound to correct `chamber_id`; a profile edited after PREPARED never changes an active run.
- [ ] Review the [G06-A contract](G06_A_PROFILE_RUNNER_CONTRACT.md) against the current implementation. Record every material mismatch with file/line, severity, test name and proposed remediation.

## 2. Automated tests (all simulated)

Run on latest `main` in an isolated environment, on Windows Python 3.10 and 3.12:

```powershell
python -m pip install -r requirements-web.txt pytest==9.1.1 ruff==0.17.0
python -m compileall -q chamber_web/execution tests/test_profile_runner.py
python -m ruff check chamber_web/execution tests/test_profile_runner.py --select E4,E7,E9,F
python -m pytest -q tests/test_profile_runner.py tests/test_chamber_controller.py tests/test_profile_storage.py tests/test_chamber_backend.py tests/test_profile_schema.py
python -m pytest -q tests/test_profile_security_integration.py tests/test_security_core.py tests/test_profile_editor.py tests/test_web_profiles_ui.py
python -m pytest -q
```

- [ ] All focused G06-A unit tests pass without intermittent timing failures.
- [ ] G04 command/ownership/lease/STOP regressions and G03 profile revision/CSV regressions pass.
- [ ] G08-min integration tests verify that server-side auth is required; denied/unowned or VIEWER client mutations cannot start/pause/resume/cancel unlawfully; explicitly authorized STOP remains independent of the operator lease.
- [ ] Full repository test suite passes; capture the count and any skipped tests or warnings. Investigate recurring failures; never waive BLOCKER/HIGH concerns.
- [ ] Run `profile-runner-windows.yml`, `web-gui-demo.yml` and `windows-packaging.yml` at the exact review head. Confirm successful Python 3.10/3.12 jobs where configured; attach individual GitHub Actions run URLs.

**Important:** `profile-runner-windows.yml` currently uses `pull_request` or `workflow_dispatch` (not `push` to main). Use GitHub Actions **Run workflow** on `main` or an appropriate new test PR; do not assume merely committing this Markdown file triggered that workflow.

## 3. Deterministic state-machine/timing acceptance

Run each case with injected `VirtualClock`, a mock-only `FakeBackend`, and **sequential, separate** `AlternateStubBackend` fixture, never simultaneously controlling two devices.

- [ ] Normal 1-step and repeated/multi-step runs traverse PREPARING, REACHING, optional STABILIZING, DWELLING, TRANSITIONING, STOP_REQUESTED, COMPLETED; final state requires verified G04 STOP.
- [ ] Zero dwell transitions only after eligible observation (not just a setpoint write). Nonzero stabilization requires two *distinct* qualified samples spanning the full interval.
- [ ] Exactly `target ± tolerance` is inclusive; a value immediately outside fails qualification. Negative temperature values are accepted only inside capability limits; NaN, infinity and out-of-range values are denied.
- [ ] Only eligible GOOD, identity-matched, fresh measurements count. Duplicate or regressing source timestamps, observation gaps >5s and out-of-band excursions never accrue stabilization/dwell; excursions reset dwell.
- [ ] Positive dwell credits only intervals bracketed by two eligible observations; jitter or repeated/sparse polls cannot fabricate duration.
- [ ] Reach at the exact deadline can succeed, but later readings time out. Whole-step/whole-run deadlines remain finite and **absolute**, including while paused, and cannot be bypassed by slow polls or event-loop blockage.
- [ ] PAUSE is explicitly logical: chamber remains RUNNING with same setpoint and safe verified identity; RESUME resets qualification. Operator ownership and invalid pause/resume transitions fail closed.
- [ ] Reject explicit gradient/ramp writes while G04 lacks verified baseline capture, ramp readback and safe restoration; profiles with null ramp fields issue **zero gradient commands**.

## 4. Cancellation, concurrency, faults and STOP fencing

- [ ] Two simultaneous starts result in **at most one** reserved active run; another operator cannot steal the run's setpoint or pause/resume permission.
- [ ] CANCEL during a queued setpoint and a blocked in-flight synchronous poll returns promptly to the requesting service, initiates prioritized G04 STOP fencing and never claims preemption of already-admitted I/O.
- [ ] Repeated cancellation submits no duplicate STOP intent. STOP request is permitted to independently authorized operators even when another actor owns the run.
- [ ] No setpoint or START admitted after a new STOP generation. After STOP, the controller remains latched until an **explicit** authorized, fresh stopped readback and reconciliation; never auto-resume.
- [ ] Force stale/ERROR telemetry, disconnected backend, changed identity, readback mismatch, invalid temperature and backend FAULT. Each execution must stop progressing, request STOP and conservatively terminate UNKNOWN if effect cannot be verified.
- [ ] Inject hung/time-out I/O, STOP failure, and race between STOP, start, pause/resume and shutdown. A synchronous call already in flight may not be preemptible. Neither timeout nor disconnect proves the device stopped; process lease/fencing uncertainty is retained.
- [ ] Closing the runner with a live run is rejected, and a **closed runner cannot accept another start**. Verify no background worker survives cleanup in an unsafe state.
- [ ] Inject EventSink PREPARED/START_INTENT/STOP_INTENT/SAMPLE/TERMINAL errors. No command before failed PREPARED or START_INTENT; a recording failure after command intent must fail closed and preserve uncertainty.

## 5. G07 event contract and crash handoff (integration gate)

- [ ] Verify `EventSink.prepare(ExecutionSnapshot)` precedes first mutation; `START_INTENT` is emitted **before the first setpoint**, not only before backend START. Any persistence exception prevents unsafe progression.
- [ ] Check immutable run UUID/chamber/backend/capability/revision/actor identity, monotonic event sequence, per-run `sample_index`, `monotonic_elapsed_s`, and timezone-aware `observed_at_utc`/`source_sampled_at_utc`.
- [ ] Confirm diagnostic ring buffer has a 1024-event ceiling **without** resetting emitted event or sample sequence numbers.
- [ ] For G07-A PR #27, once integrated, verify SQLite/filesystem PREPARED → START_INTENT → RUNNING → FINALIZING sequencing, fsync/rename/checksum behavior, simulated kill/restart at every critical boundary and fail-closed recovery of all nonterminal runs to INTERRUPTED/UNKNOWN. Never fabricate STOP, duplicate samples or auto-resume.
- [ ] Simulate full disk/recorder failure and process exit. Run result/history must remain recoverable and namespaced to the original `chamber_id`. This part is **not implemented by the G06 runner alone** and must not be marked G06-complete merely from ephemeral in-memory events.

## 6. NiceGUI/security/Windows acceptance (integrated simulator)

- [ ] Verify server remains the sole run authority across page refresh, multi-tab browser sessions, disconnect/reconnect, two authenticated operators and service restart. If no UI run control is integrated yet, mark UI scenario BLOCKED BY G05/G08/G07 integration, **not** PASSED; validate the service headlessly instead.
- [ ] Verify a missing/expired G08 authorization session cannot mutate run state. No browser-provided role, token or trusted username substitutes for server-side permission and audit; deny VIEWER/unauthenticated mutations.
- [ ] Validate on Windows 10/11 x64 only with the extracted **simulated** W01 bundle; ensure no hardware connection, no runtime driver download, and no silent simulator fallback from a physical backend configuration. Clean disconnected-VM certification remains W02, not this task.
- [ ] Check process restart/frozen-app shutdown with an interrupted simulated profile: do not restart it, replay writes, mark STOP verified or release physical readiness gates.

## 7. Evidence, review and completion criteria

Create a new **testing-only PR** (unless fixes are needed, then use a separate named correction PR) with an evidence report, e.g. `docs/G06_A_TEST_RESULTS.md`. Record:
- exact tested `main` SHA; exact test-PR head SHA;
- test date, reviewer(s), Python/Windows versions and selected Fake/alternate fixture identities;
- commands, all PASS/FAIL/BLOCKED results, pytest counts, errors and Windows workflow URLs **for the exact tested source head**;
- deterministic virtual-clock schedules and observed transitions for deadline equality, dwell/stabilization and STOP races;
- documented G07/G08/G05 cross-service gaps and any failed integration scenario;
- severity-ranked issues with reproduction instructions, expected vs observed behavior and linked correction PRs.

**Software test task can be closed** when all applicable G06 simulated scenarios pass on current integrated `main`, final-head Windows CI is green and all BLOCKER/HIGH issues affecting G06 software behavior are closed by reviewed commits. Integration scenarios not yet implemented must be explicitly **BLOCKED**, assigned to their owner (G05, G07, G08), and tracked separately—not claimed as passed. Obtain a separate reviewer’s approval; this document and AI-assisted review do not replace independent signoff.

**Physical operation/release stays NO-GO regardless of software test outcome:** pending signed model/firmware/site limits, certified gradient baseline/restoration policy, STOP/fault behavior, HIL on one approved chamber, complete G08 LAN security and W02 clean-air-gap Windows qualification. Web STOP is **not** an emergency stop.
