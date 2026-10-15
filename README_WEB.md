# NiceGUI climate chamber — G02-A server-backed simulation

The dashboard now obtains **read-only server-owned telemetry** through
`DashboardService → ChamberManager(chamber_id) → ChamberBackend`. The server
starts a single hard-coded Fake backend; browser refreshes and disconnections
do not destroy the backend or its bounded (1,500-point) in-memory graph data.
Backend polling runs independently of browser clients, in worker threads,
and failed/stale reads show **UNKNOWN/unverified** rather than the last
measured value. The domain/manager are manufacturer-neutral.

**No physical hardware control is enabled.** Start, Stop, Hold and manual
setpoint controls are deliberately disabled. G04/G08-min and site safety/HIL
approval are prerequisites for any live mutation. The external Vötsch
driver is not imported by the NiceGUI page or generic services.

The profile editor and CSV import/export are **page-local drafts**, not
a persisted revision store or executable profile; G03-C will connect those
to the existing server-side SQLite profile services. Run History and
device logs are also not implemented. Draft events are not hardware logs.

## Automatic environment setup (Windows / Linux)

Prerequisites: Python 3.10+ (CI-tested on 3.10 and 3.12), Git, and internet
access for downloads. The script detects Windows or Linux, creates/reuses
`.venv`, installs the web app and pinned external Vötsch driver, and runs
`pip check`. Installing the driver **does not enable physical hardware I/O**.

Windows PowerShell:

```powershell
py -3.12 setup_environment.py
.venv\Scripts\python.exe main.py
```

Linux:

```bash
python3 setup_environment.py
.venv/bin/python main.py
```

Open http://127.0.0.1:8080. The development app binds to loopback only.

Optional script arguments:

- `--with-tests`: install pinned pytest, pytest-asyncio, ruff and Playwright.
- `--with-tests --browser`: also download Chromium for browser tests. On Linux,
  required system browser libraries must be present or installed separately.
- `--no-driver`: simulation-only installation without Git/external driver.
- `--run`: launch the local simulated GUI after dependency installation.
- `--venv PATH`: choose a custom venv; a non-venv directory is never overwritten.
- `--recreate`: delete and rebuild the venv (refused unless it contains `pyvenv.cfg`).

Rerunning the script reuses the virtual environment. Run
`python setup_environment.py --help` for options. This source installation
requires network access for first-time downloads; use the separate
[offline Windows bundle](README_OFFLINE_WINDOWS.md) for offline deployment.

## Supervised physical HIL (one Vötsch chamber)

Physical I/O is disabled by default. Only a server started with a **complete**
set of the variables below drives the real chamber; any missing or invalid
value refuses to start. Nothing can be selected from the browser.

```bash
CHAMBER_HIL_ADDRESS=192.168.0.11            # private IPv4 literal
CHAMBER_HIL_EXPECTED_SERIAL=58566207770010  # checked at connect and on every read
CHAMBER_HIL_TEMP_MIN_C=20                   # software envelope, span <= 30 °C
CHAMBER_HIL_TEMP_MAX_C=30
CHAMBER_HIL_ACK=SUPERVISED-PHYSICAL-HIL     # a person is present at the chamber
python main.py
```

HIL is loopback-only (LAN mode with HIL is refused) and needs the external
driver (`requirements-hardware.txt`). The Vötsch setpoint readback ramps at the
chamber gradient, so **Set Target** is confirmed only after the ramp settles.
Profile execution remains simulation-only. Web STOP is not an emergency stop;
the chamber's own controls and emergency stop remain primary.

## Verification

```bash
python -m unittest discover -s tests -p "test_chamber_*.py" -v
python -m unittest discover -s tests -p "test_web_*.py" -v
python -m pytest -q tests/test_web_ui.py
```

Sequential Fake, alternative-vendor test stub and injected Vötsch-mock
tests cover the same read-only service. They run in separate single-chamber
instances and do not certify any physical hardware. Production Vötsch
connections remain blocked by the G01 adapter.

## Early Windows packaging feasibility (W01-A)

The separate [W01-A Windows guide](README_OFFLINE_WINDOWS.md) documents an early
Windows launcher and simulated NiceGUI offline ZIP build. The bundle has a
pinned external Vötsch dependency (unless explicitly built in simulation-only
mode), but the service selects **FakeBackend only** and real hardware I/O stays
disabled. W01 records frozen assets and dependency versions/integrity hashes;
a clean air-gapped Windows certification and full transitive hash lock remain
release-blocking W02 tasks.
