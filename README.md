# Vötsch Climate Chamber Control

NiceGUI browser-based interface for a single Vötsch environmental chamber. The maintained entry point is `main.py`, which launches `chamber_web.main`; the browser UI uses server-owned services and the separate [Vötsch Python driver](https://github.com/ami3go/VotschTechnik-climate-chamber-Python) for authorized physical communication.

The application includes a dashboard, manual chamber controls, persistent temperature profiles, profile execution, run recording and operator authorization. Simulation is the default. **Physical HIL is explicitly opt-in, not certified production use**; signed site safety authorization and outstanding hardware/offline release gates remain required. See [web setup and operating limitations](README_WEB.md), [development sequence](docs/DEVELOPMENT_SEQUENCE.md) and [hardware safety acceptance](docs/H01_HARDWARE_ACCEPTANCE_CHECKLIST.md).

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
