# H01 extended simulated HIL / Web / NiceGUI verification

**Status: software test implementation only; physical chamber NO-GO.**

This change extends H01 PR #32. Existing H01-01 to H01-20 are **future site-supervised hardware procedures**, not tests that can safely execute on CI. This suite adds concrete, executable tests at the G04/G06/G08 software boundaries and real Chromium end-to-end checks against the existing **FakeBackend-only** NiceGUI composition root.

## Execute locally

With Python 3.10 or 3.12, install the application dependencies:

```bash
python -m pip install -r requirements-web.txt
python -m unittest discover -s tests -p "test_h01_simulation.py" -v
python -m unittest discover -s tests -p "test_h01_full_stack.py" -v
python -m unittest discover -s tests -p "test_h01_web_transport.py" -v
```

For real-browser checks, install the *test-only* dependencies. Chromium must be installed once on the development/test host (never by the deployed offline server):

```bash
python -m pip install pytest==9.1.1 pytest-asyncio==1.4.0 playwright==1.58.0
python -m playwright install chromium
python -m pytest -v -s tests/test_h01_browser_e2e.py
```

The browser suite starts the real NiceGUI process on **127.0.0.1:8080**, using a new disposable directory containing freshly bootstrapped credentials. It must run on a machine where that port is free. A failure prints the bounded server log, and process termination is guaranteed by the test fixture.

GitHub Actions workflow: `.github/workflows/h01-extended-ci.yml`. All tests run **without** a hardware driver, chamber endpoint, physical credentials or service activation flag.

## Evidence and coverage

| Test file | Layer | Verified invariant |
|---|---|---|
| `tests/test_h01_simulation.py` | G04 / FakeBackend | Invalid target, STOP latch, readback timeout, stale/mismatch, physical connect blocked |
| `tests/test_h01_full_stack.py` | G08 -> G04 -> FakeBackend; G06 | Anonymous/VIEWER/CSRF/invalid command denial, no dispatch, two-operator lease, non-owner STOP, session revocation, no success after ambiguous STOP/readback, profile snapshot and ordered event journal |
| `tests/test_h01_web_transport.py` | ASGI G08 middleware | Same-origin NiceGUI traffic, rejected foreign/missing origin/Host for HTTP and WebSocket, no downstream dispatch |
| `tests/test_h01_browser_e2e.py` | Live NiceGUI + Chromium | Browser login, Dashboard read-only safety, saved Profiles route, independent sessions, page reload and revoked session |

The G06 in-memory EventCapture test is not G07 durable journal certification; G07 recording must be integrated and subjected to power-loss, ENOSPC, recovery and full browser History/download checks after G07-A merges.

The browser tests deliberately **do not pretend the G05 manual-control page exists on H01's upstream main baseline**. G05 PR #28, G07-A PR #27 and G08-full PR #29 are separate draft changes. Once accepted and merged, extend the real-browser tests with an operator claim -> setpoint -> START -> live telemetry -> web STOP -> history/export workflow. This test must additionally assert the simulated backend command ledger, STOP fencing, role/CSRF enforcement and exported G07 hashes. Never mark that future integration case PASS before the code and evidence exist.

## Test environment separation

- **CI / mock only:** fake/alternate backends, isolated SQLite, virtual time, no real socket to VT4011.
- **Offline Windows QA:** frozen server process and local browser under W02; failures preserved; no real hardware.
- **Physical HIL:** **not implemented/executed by this workflow**. Requires signed P00/H01 site authorization, exact chamber identity/firmware/limits, trained operator, local emergency stop, independent calibrated observation and a separately reviewed hardware-access implementation. Hardware STOP verification is not inferred from a command acknowledgement or mock readback.

Never add an environment-variable or CLI escape hatch to the H01 test suite for physical-device activation. The GUI must continue using the external pinned Python driver **only via VotschBackend** for any separately authorized later HIL implementation.

## Release gate

An H01 software PASS means the test program passed on the exact CI commit; it does not assert physical certification, secure LAN deployment, G05/G07/G08 integration, or W02 offline release readiness. Evidence must include CI URL/SHA, junit results and any failure details. H01 site acceptance remains **BLOCKED**.
