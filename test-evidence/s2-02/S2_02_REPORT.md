# S2-02 — Combined regression baseline (exact-main, simulation only)

**Package:** S2-02 / P0 (Stage 2 plan, §3 order 2)
**Executed:** 2026-10-20, Europe/Sofia
**GUI head:** `c212ed7780f12ca83f1ca59690198f54845c0d50` (main, clean tree at run start)
**External driver:** pinned `b56cfbd54570e66cddf83106505487d3b19d9677` (verified by `scripts/verify_driver_install.py` during setup)
**Host:** Linux x86_64, Python 3.12.15 (uv-managed, venv `.venv`), NiceGUI 3.18.0, pytest 9.1.1
**Hardware:** none connected; `CHAMBER_HIL_RUN_TESTS` unset — all runs simulation-only. No physical command was issued.

## Method

Each group executed under `scripts/h02_watchdog_command.py` (finite wall + idle
deadlines, process-group cleanup, `timeline.jsonl`/`summary.json`/logs per run).
A watchdog TIMEOUT/NO_OUTPUT kill counts as FAIL. Runner: `run_s2_02.sh`.
Per-group JUnit XML retained. Run 1 (before remediation) XMLs kept as `*.run1.xml`.

Note: host `/tmp` (tmpfs) was full; `TMPDIR` redirected to the root filesystem.
This affected environment setup only, not test semantics.

## Final matrix (run 2 — PASS)

| Group | Scope | Tests | Fail | Skip | Wall | Watchdog |
|---|---|---|---|---|---|---|
| A | G04 controller/STOP, G05 manual/leases, G06 runner, profiles, dashboard | 235 | 0 | 0 | 118.6 s | EXITED rc=0 |
| B | G07 run recording, H02 admission/supervision/watchdog | 132 | 0 | 1 | 37.8 s | EXITED rc=0 |
| C | G08 security, web/UI, infra, W02 packaging | 239 | 0 | 0 | 137.1 s | EXITED rc=0 |
| D | H01 simulated full-stack/transport | 109 | 0 | 0 | 45.8 s | EXITED rc=0 |
| E | Real Chromium browser↔NiceGUI lifecycle | 3 | 0 | 0 | 31.0 s | EXITED rc=0 |
| **Total** | | **718** | **0** | **1** | **~5.4 min** | all rc=0 |

Plus pytest subtests (A: 30+, B: 51, C: many) — none failed in run 2.

**The 1 skip:** `test_run_recording.py::test_one_million_samples_real_sqlite_and_bounded_plot`
— deliberately opt-in via `G07_STRESS=1` (not a defect; stress job).

## Run 1 findings (remediated)

1. **Test rot on main — `tests/test_profile_runtime.py` (1 failure).**
   PR #70 (`4c97cb0`) added `get_profile_manual_guard` to the composition getter
   import in `chamber_web/pages/profiles.py:72`; the test's stubbed
   `chamber_web.main` module did not provide it → `ImportError`.
   **No GitHub workflow executes `tests/test_profile_runtime.py`**, so this
   merged green. Fix: stub now returns `SimpleNamespace(_security=None)`, which
   takes profiles.py's documented isolated-test path (`manual_guard=None` on
   security-store mismatch). Test-only change; uncommitted, awaiting review.
2. **CI dependency gap, not a code defect (7 failures + 1 collection error).**
   `cryptography` is installed explicitly by workflows
   (`cryptography==46.0.2`/`46.0.3`) and pinned in `requirements-w02-build.txt`,
   but is absent from `requirements-dev.txt`. Local/first setup therefore failed
   all Ed25519 permit-signing tests (`test_h02_supervised_profile.py`) and could
   not collect `test_w02_release.py`. Fix: install `cryptography==46.0.2`.
   **Recommendation:** add it to `requirements-dev.txt` so a single dev
   requirements file reproduces the CI test environment.

## CI-run findings (combined job, working as designed)

The GitHub combined job (`.github/workflows/s2-02-regression-ci.yml`, run
`39391025193` @ head `eba0c6c`) ran the whole simulation suite in one process on
Ubuntu 3.12 and Windows 3.10/3.12. Its first executions exposed two further
test-hermeticity defects that **no existing workflow executes** — the per-file
jobs never ran `tests/test_security_credential_reset.py`, and the dashboard UI
test only ever ran in isolation with no combined-suite ordering/load.

3. **`tests/test_security_credential_reset.py` (Windows legs).** Only linted by
   `web-gui-demo.yml` (ruff); no workflow executes it. `subprocess.run(
   capture_output=True)` did not pin stdin, so the child inherited the Windows
   console handle (`isatty()` True) and `_local_reset_console()` fell through to
   the database check instead of the intended "interactive console" refusal.
   Fix: drive the refusal through the explicit `SSH_TTY` indicator (a plain env
   lookup, rejected before any stdin test) **and** pin `stdin=subprocess.DEVNULL`.
   Platform-deterministic; the guard is exercised, not weakened.
4. **`tests/test_dashboard_profile_ui.py` second-run Stop (all legs; deterministic
   on Linux once reproduced).** The test clicked the **second** `Stop Run` while
   the control was still **disabled**: `execution.runner` is published by the
   service worker thread inside `start_async`'s `to_thread` call, before the page
   resumes and calls `refresh_run()` to enable Stop; NiceGUI silently drops
   clicks on disabled elements. The following `should_see("STOP requested")`
   then passed on the **retained first-stop toast** (the test harness's
   `UserNotify` never expires notifications), so a run stuck at `REACHING`
   looked green. Fix: wait for the Stop control to be enabled before clicking and
   clear retained toasts before asserting the fresh STOP; the
   `state == "CANCELLED"` assertion is unchanged and now genuinely exercised.

Result after fixes: `518 passed, 1 skipped, 196 subtests passed`, and all three
CI legs green with JUnit `tests=715 failures=0 errors=0 skipped=1` per leg and
every watchdog `result: EXITED, returncode: 0` (no timeout kills).

> The 715 vs 718 difference is the grouped runner (A..E) versus the single
> combined process: grouping re-collects parametrised UI cases. Both are zero
> failures; the single-process figure is the one the CI job asserts.

## Repaired-workflow findings (2026-10-20/21)

Repairing the malformed `web-gui-demo.yml` step (finding 5 below) re-enabled a
CI job that had produced **zero jobs on every `main` push since 2026-10-19**
(`fb6014a` introduced a literal `\n` inside a YAML scalar). With the job
running again, its order-sensitive NiceGUI simulations exposed one more
defect that the combined single-process job did not.

5. **`tests/test_manual_ui.py::test_dashboard_stop_without_claim_then_start_recovers_as_operator`
   — G05 refused a legitimate operator Start (product defect, not test rot).**
   The job failed at `tests/test_manual_ui.py:122` with the page showing
   `REJECTED · start · C…` while the controller stayed
   `VERIFIED_STOPPED` with the STOP fence still latched (the "Verified STOP"
   profile hint). Diagnosis: the G05 Start path learned the operator-lease
   revision through `AuthorizedChamber.owned_lease_revision_now()` — a
   *best-effort, non-blocking* probe that exists so a priority STOP never
   waits for the registry lock. The dashboard refreshes the manual view once
   a second and reads the same registry; when that reader held the lock, the
   probe returned "no revision", which the Start path could not distinguish
   from "no lease held", so it refused the Start with
   `STOP recovery not verified; control remains locked` and left the operator
   with no way to clear the fence.
   Reproduced deterministically: with the probe forced to report contention
   the Start is refused with exactly the CI signature
   (`REJECTED` / `ChamberSafetyError` / `VERIFIED_STOPPED` / `stop_latched`).
   **Fix:** `AuthorizedChamber.ensure_manual_operator_lease_revision()` reads
   the revision in the same critical section as the claim, so contention can
   no longer masquerade as "not the lease owner". The rearm still requires the
   exact lease revision, the caller's ownership, a latched `VERIFIED_STOPPED`
   controller and the exact G04 generation, and G04 still performs its own
   fresh STOPPED readback — the safety envelope is unchanged.
   Regression tests: `test_contended_lease_probe_never_refuses_an_operator_start`
   (deterministic) and
   `test_start_after_stop_survives_a_concurrent_registry_reader` (concurrency).
6. **Refusals were not diagnosable.** A refused manual command reported only
   the exception *type* (`Command refused or unverified: ChamberSafetyError`)
   to the operator, the audit trail and CI. The bounded refusal reason is now
   included (`_bounded_reason`), so an operator sees *why* a command was
   refused and a CI failure is self-explaining.

## Residual gaps (documented, out of S2-02 scope)

- Windows/Python 3.10 legs: this baseline is Linux/3.12 only; Windows matrix is
  covered by GitHub Actions on the same head and by S2-03/S2-04 VM evidence.
- `tests/hardware/` physical tests: **NOT RUN** (require `CHAMBER_HIL_RUN_TESTS=1`
  plus signed site authorization; S2-07 scope).
- `G07_STRESS=1` million-sample stress job: not run.
- CI coverage gap: consider adding `tests/test_profile_runtime.py` (and a full
  `pytest tests/` combined job) to a workflow so local-only rot like finding 1
  cannot merge again.
- The G05 Start-after-STOP contention window was intermittent (1 of 7 repaired
  workflow runs). It is now closed by construction rather than by retry, and
  the deterministic regression test replaces the need to catch it by luck.

## Evidence index

- `environment.txt` — exact head, interpreter, `pip freeze`
- `run_s2_02.sh` — deterministic runner (grouping, watchdog bounds)
- `A..E/watchdog-*/` — per-run `summary.json`, `timeline.jsonl`, stdout/stderr
- `s2-02-{a..e}*.xml` — run-2 JUnit; `*.run1.xml` — pre-remediation run-1 JUnit
- `summary.txt` — group exit codes (run 1 and run 2)

**Verdict:** S2-02 combined regression baseline **PASS** on Linux/Python 3.12 at
`c212ed7`, with two findings fixed (one test-rot patch pending review, one
dependency documentation gap). H01 physical evidence and H02 physical profiles
remain **NOT RUN / NO-GO** per Stage 2 gates.
