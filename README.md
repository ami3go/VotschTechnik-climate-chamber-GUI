# Vötsch Climate Chamber Control

## New NiceGUI web interface (simulation scaffold)

The new browser-based interface is being developed in `chamber_web/`, based on the supplied Visteon-themed dashboard concept. It provides a responsive dashboard, editable temperature profile, simulated test sequence, chart, and profile CSV import/export.

**Safety:** The web scaffold is a DEMO only. It does not communicate with chamber hardware. Real device control will use the separate [Python driver](https://github.com/ami3go/VotschTechnik-climate-chamber-Python) in a later, tested integration. See [web setup and current limitations](README_WEB.md) and the [migration plan](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/3).

## Offline administrator credential reset

From the **complete GUI repository checkout**, use the installed Python
environment to run `python -m scripts.reset_credentials` or execute
`python scripts/reset_credentials.py` directly. Running a standalone
copy without the `chamber_web/` directory is not supported. Alternatively use
`server/ClimateChamberServer.exe --reset-credentials` in a frozen Windows
distribution. The prompt accepts the existing administrator password **or**
a previously escrowed one-time recovery token. It resets the password,
clears the administrator PIN, switches to General login, and revokes all
sessions without deleting operator accounts or run data.

See [offline credential reset and recovery](docs/CREDENTIAL_RESET.md).
Neither an unauthenticated reset nor browser-based recovery is supported.

## Cross-platform Python setup (Windows/Linux)

Install Python 3.10+ (CI-tested on 3.10 and 3.12) and Git. From a repository checkout, run:

**Windows** (PowerShell):

```powershell
py -3.12 setup_environment.py
.venv\Scripts\python.exe main.py
```

**Linux**:

```bash
python3 setup_environment.py
.venv/bin/python main.py
```

The setup detects the operating system, creates or reuses `.venv`, installs the NiceGUI web requirements and the **commit-pinned external Vötsch Python driver**, then runs `pip check`. No hardware I/O is performed. Open http://127.0.0.1:8080 after starting the app.

To install pytest, ruff and Playwright for HIL/browser testing, add `--with-tests`; add `--browser` to download Chromium as well. For a simulation-only installation without the external driver or Git, use `--no-driver`. Use `--run` to start the GUI after installation. An internet connection is needed for fresh package installs; this is **not** the offline Windows release process (see [offline packaging](README_OFFLINE_WINDOWS.md)).

See [web setup and safety limitations](README_WEB.md) for details. Physical chamber operation remains disabled pending site authorization/HIL validation.

---

## Legacy Tkinter desktop GUI

 ![image](/pictures/main-tab.png)

Executable file for windows is available [here](/dist/)

Old chambers frequently have broken touch, which don't allow to operate chamber. 

Original software also frequently give an error. 

This simple gui may be used to bypass original software, or create a touch screen based on raspbery Pi

Software tested with VT4011
 
Communication protocol based on https://github.com/ami3go/VotschTechnik-climate-chamber-Python - (fork from [this project](https://github.com/SengerM/VotschTechnik-climate-chamber-Python))

Features: 
* start and stop chamber
* Set temperature, read current temperature 

Features to be impemented:
* Temperature profile from table or csv file 

