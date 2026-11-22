# Vötsch Climate Chamber Control

NiceGUI browser-based interface for a single Vötsch environmental chamber. The maintained entry point is `main.py`, which launches `chamber_web.main`; the browser UI uses server-owned services and the separate [Vötsch Python driver](https://github.com/ami3go/VotschTechnik-climate-chamber-Python) for authorized physical communication.

The application includes a dashboard, manual chamber controls, persistent temperature profiles, profile execution, run recording and operator authorization. Simulation is the default. **Physical HIL is explicitly opt-in, not certified production use**. Agent-operated hardware **tests** use a locally issued 24-hour operator PIN rather than per-run signed permits. Historical H02 supervised *runtime* permit support and the separate production/offline release gates remain; see [the PIN runbook](docs/HIL_PIN_RUNBOOK.md). See the [detailed remaining development and release plan](docs/REMAINING_DEVELOPMENT_TASKS.md), [web setup and operating limitations](README_WEB.md), [development sequence](docs/DEVELOPMENT_SEQUENCE.md), [hardware safety acceptance](docs/H01_HARDWARE_ACCEPTANCE_CHECKLIST.md), the [canonical readiness findings and release blockers](docs/READINESS_FINDINGS.md) and the [W02 offline release gates](docs/W02_OFFLINE_RELEASE.md).

## Current execution and pending tasks (November 2026)

The **[authoritative Chamber execution tracker](docs/CHAMBER_EXECUTION_TRACKER.md)** links the ten current GitHub work packages, open emulator PRs, legacy driver PR, exact-head CI gates, mandatory watchdogs, and separate software/HIL/release acceptance criteria. Use the tracker and [linked issues](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues) for current execution status; the older dated Stage 2 plan and readiness findings remain historical evidence and design/release contracts.

## Current engineering phase — Stage 2 (2026-10-19)

The recorded supervised physical **H01** test suite passed 8/8 on 19 October
2026 ([evidence entry](docs/DEVELOPMENT_SEQUENCE.md)). The project has
advanced its **design and engineering work queue** to
[Stage 2 — Pre-production hardening and controlled pilot readiness](docs/STAGE_2_PILOT_READINESS_PLAN.md).
This does not assert signed site acceptance, independently accepted H02
physical profile runs, W02 air-gap certification, or R01 release approval.

## Physical Operational Mode (supervised pilot)

Administrators can select **Settings → Chamber configuration → Enable supervised Operational Mode**, enter the real chamber address, pinned serial, and site-approved temperature envelope, and restart the server. This mode requires a live independent G06/H02-C watchdog to start profiles; it deliberately rejects plain-HTTP lab networking, H02 permit mixing, unqualified gradients and physical digital outputs. A healthy watchdog on the host **does not** replace the chamber's independent hardware interlocks or emergency stop, especially after host/network/power failure. No current-head physical HIL or signed site/release approval is claimed; see [operational qualification](docs/H01_OPERATIONAL_HARDWARE_QUALIFICATION.md), [H01 issue #112](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/112) and [software issue #113](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/113).

## Isolated lab: full-range unattended operation

For agent-managed physical HIL tests, first use `bash scripts/hil_pin.sh setup` at an operator terminal, then `bash scripts/hil_pin.sh run -- COMMAND` (see [runbook](docs/HIL_PIN_RUNBOOK.md)). This PIN does not replace physical STOP, chamber limits or bench ownership.

On a closed lab network, administrators can enable **Settings → Physical
profile runs → isolated lab mode**, which launches the server with
`CHAMBER_LAB_MODE=ISOLATED-LAB-UNATTENDED` and lets the physical chamber run
profiles across the full envelope without the H02 permit workflow. The same
variable can be set directly in the server environment. Separately,
`CHAMBER_NETWORK_MODE=lab` serves the UI to the lab laptop over plain HTTP. `scripts/hil_lab_acceptance.py` is the unattended full-range HIL
acceptance run (`--simulate` validates it without hardware). See
[README_LAB.md](README_LAB.md).

## Install and run (Windows / Linux)

Install Python 3.10+ (CI-tested with 3.10 and 3.12) and Git.

**Windows PowerShell**

```powershell
py -3.12 setup_environment.py
.venv\Scripts\python.exe main.py
```

**Linux**

```bash
python3 setup_environment.py
.venv/bin/python main.py
```

Open http://127.0.0.1:8080 after starting the server. The setup creates or reuses `.venv`, installs NiceGUI and the commit-pinned external driver, and runs `pip check`. It does not connect to physical hardware. Use `--no-driver` for simulation-only installs, `--with-tests` to install test dependencies, `--with-tests --browser` for Playwright Chromium, or `--run` to start the app after setup. First-time dependency installation needs internet; use the separate [Windows offline packaging procedure](README_OFFLINE_WINDOWS.md) for offline deployments.

## Offline administrator credential reset

From the **complete GUI repository checkout**, use the installed Python environment to run `python -m scripts.reset_credentials` or execute `python scripts/reset_credentials.py` directly:

```bash
python -m scripts.reset_credentials
```

Direct execution resolves `chamber_web` from the checked-out repository, so it also works from an unrelated working directory. Running a standalone copy of the script without the `chamber_web/` directory is not supported.

For a frozen Windows deployment, run `server/ClimateChamberServer.exe --reset-credentials`. This server-host-only recovery does not require the old password, PIN, or recovery token. After explicit interactive confirmation, it restores factory administrator values and General login, revokes sessions and preserves other users and run data. It is not available through the browser; the server OS account must have permission to access the security database. See [credential recovery](docs/CREDENTIAL_RESET.md).

## Desktop GUI retirement

The original Tkinter GUI, archived Tk/Qt prototypes, legacy PyInstaller spec, compiled desktop executable and generated build artifacts have been removed from the active repository. The maintained Windows executable is the **NiceGUI web launcher/server**, not a desktop UI. Historical source and binary revisions remain available in Git history; deletion from the active tree does **not** approve physical operation or decommission existing validated field installations. See [legacy cleanup details](docs/LEGACY_DESKTOP_RETIREMENT.md).
