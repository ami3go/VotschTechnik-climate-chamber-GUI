# Visteon Climate Chamber NiceGUI dashboard — first implementation

This initial web scaffold uses the [operator-supplied NiceGUI concept](chamber_web/main.py), with the same Visteon-inspired navy/orange layout, sidebar, chamber controls, chart, active profile, inline step editor, import/export and live event table.

**Important: demo only.** This code is an isolated browser-local simulation. It does **not** connect to a Vötsch chamber, never opens device sockets and is not safe for unattended hardware runs. Temperature readings are **simulated** and labelled accordingly. Device integration will exclusively use the separate [Python chamber driver](https://github.com/ami3go/VotschTechnik-climate-chamber-Python) via a server-side controller in a later PR. Browser closure currently ends the demo; persistence and autonomous execution have not been implemented yet.

## Run on development workstation

Requires Python 3.10+ and a compatible browser.

~~~powershell
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements-web.txt
.venv\Scripts\python main.py
~~~

Open http://127.0.0.1:8080. The server intentionally binds **localhost only** until access control exists.

## Features implemented

- Responsive NiceGUI Visteon-inspired header/sidebar and dashboard.
- Start, Stop and Hold for the **simulation only** (no hardware controls).
- Manual target display (demo only), simulated temperature measurement, ECharts live curve.
- In-page editable profile steps, add/duplicate/delete and atomic CSV import/validated export.
- Strict CSV columns: `target,ramp,tolerance,dwell,description,enabled`, with seconds for dwell, °C for target/tolerance and °C/min for **simulated** ramp. Import limit: 1 MB, 200 rows. The profile name and run history are **not** persisted in this phase.
- Recent in-memory measurement/event tables; 1,500-point plot retention.

## Deliberately not implemented yet

Physical driver adapter/connection, live chamber setpoints, real gradient control, user authentication, official brand-logo asset licensing, profile database, autonomous server-side execution, persisted CSV measurements, historical runs and Windows launcher/offline bundles. These remain in the migration plan.

### UI and safety notes

The demo temperature range (-40 to +130 °C) and ramp limits are **not hardware specifications**. Real limits must be discovered and validated for each chamber via the Python driver and operating manuals. The user-supplied text "Visteon" is a **brand placeholder** until an approved corporate logo is supplied. This app intentionally does not contact an external CDN or cloud service from its own code, but offline packaging must independently verify framework static-asset loading.

To exercise profile CSV parsing without starting a UI:

~~~bash
python -m unittest discover -s tests -p "test_web_*.py"
~~~

Source: `chamber_web/main.py`, `chamber_web/model.py`, `chamber_web/assets/style.css`.
