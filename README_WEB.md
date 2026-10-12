# Climate Chamber NiceGUI — G02-A server-backed simulation

The Visteon-inspired NiceGUI Dashboard now reads normalized status and
capabilities from a **single shared server-side DashboardService**, backed by
the vendor-neutral ChamberManager and ChamberBackend contract. It no longer
creates one DemoChamber per browser tab or uses a browser timer to advance a
profile. Browser reloads and disconnects do not reset the shared backend
object. The root Python package remains in `chamber_web/` (no `src/`).

**SIMULATION ONLY. No physical I/O.** The application composition root
(`chamber_web/bootstrap.py`) hardcodes an allowlisted FakeBackend. It does
not read a physical backend from browser input, a config file or an environment
variable; it cannot connect to a Vötsch chamber. The G01 Vötsch adapter
continues to reject real connections. Hardware commands remain disabled until
the separate G04 controller, G08-min authorization, signed site safety policy
and HIL gates are satisfied. Web STOP is not a certified emergency stop.

## Run (Python 3.10+)

~~~powershell
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements-web.txt
.venv\Scripts\python main.py
~~~

Open http://127.0.0.1:8080. The server deliberately binds only to loopback
until authentication, origin checks and LAN transport requirements are met.

## G02-A delivery

- Live measured/setpoint/operation-state/reading-quality fields come from
  `ChamberSnapshot`, with chamber identity and detected capabilities.
- Temperature graph and recent observations use a bounded **server-owned,
  volatile** dashboard cache, not a durable telemetry/run recording. A read
  fault displays UNKNOWN/ERROR and never reuses a formerly GOOD measurement.
- Every browser tab binds to the same stable `chamber_id` and the same server
  service; status reads run off the NiceGUI event loop.
- The layout retains the single-device Dashboard, profile draft CSV
  import/export/editor, chart, history/settings placeholders and navigation.
  Drafts are page-local, non-persisted and **cannot be executed**. The legacy
  `DemoChamber` class remains solely for existing `test_web_model.py`
  backward-compatibility tests, not as the NiceGUI state source.
- Start, Stop, Hold, manual target and gradient controls are disabled even
  though the FakeBackend supports test-only simulated mutations. Unsupported
  adapter features are labelled using capabilities, never vendor-name checks.

G02-B/G03-C will implement the remaining service-backed pages and persisted
profile editor, G04 will implement serialized controller ownership/fencing,
G06/G07 will add execution and durable logging, and G08-min is mandatory for
any future physical mutation.

## Verification

~~~powershell
py -m unittest discover -s tests -p "test_chamber_*.py" -v
py -m unittest discover -s tests -p "test_web_*.py" -v
py -m pytest -q tests/test_web_ui.py
~~~

`tests/test_web_dashboard_service.py` exercises server sharing, wrong-ID
rejection, read-fault fail-closed behavior, bounded observations and sequential
Fake/alternate/Vötsch-mock substitution. UI tests render the same page using
those three backends in separate fixture instances. The Vötsch mock test uses
only an injected fake driver; no physical connections occur.

The externally maintained driver is pinned separately in
`requirements-hardware.txt`; neither that dependency nor these mock tests
certify hardware or authorize its operation. Packaging/offline verification,
Windows service supervision and physical HIL remain open release gates.
