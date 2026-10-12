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

## Start on Windows (Python 3.10+)

```powershell
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements-web.txt
.venv\Scripts\python main.py
```

Open http://127.0.0.1:8080. The development app binds to **127.0.0.1 only**.
The "Visteon" wordmark remains a placeholder pending approved brand assets.

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
