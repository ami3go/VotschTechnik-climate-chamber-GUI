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

## Residual gaps (documented, out of S2-02 scope)

- Windows/Python 3.10 legs: this baseline is Linux/3.12 only; Windows matrix is
  covered by GitHub Actions on the same head and by S2-03/S2-04 VM evidence.
- `tests/hardware/` physical tests: **NOT RUN** (require `CHAMBER_HIL_RUN_TESTS=1`
  plus signed site authorization; S2-07 scope).
- `G07_STRESS=1` million-sample stress job: not run.
- CI coverage gap: consider adding `tests/test_profile_runtime.py` (and a full
  `pytest tests/` combined job) to a workflow so local-only rot like finding 1
  cannot merge again.

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
