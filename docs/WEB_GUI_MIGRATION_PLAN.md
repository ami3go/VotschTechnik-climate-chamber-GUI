# NiceGUI web migration and profile execution plan

Status: PROPOSED — documentation only; no application code is changed by this plan.
Repositories reviewed: [GUI](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI) main and [Python driver](https://github.com/ami3go/VotschTechnik-climate-chamber-Python) main (2026-10-12).
Owner decision: The NiceGUI web application replaces Tkinter. Desktop GUI support will be discontinued after web acceptance.

## 1. Goals, boundaries, and non-goals

1. Provide a responsive, browser-based operator interface on a chamber-connected Windows/Linux/Raspberry Pi host.
2. Preserve ALL existing functional desktop workflows: connect/disconnect and chamber identity; current/target temperature; preset and custom setpoint; start/stop; limits; chart; logs.
3. Add operator-authored multi-step temperature profiles through an editable table, CSV import/export, profiles saved between sessions, and server-side execution with progress, pause/resume, abort, history and recovery.
4. Save sampled measurements incrementally to CSV during runs, not only after completion. Permit retrieval of profiles, measurement logs and event logs as CSV.
5. Apply Visteon-approved identity/logo to a clean and accessible UI.
6. All chamber TCP/protocol access MUST go through the installable `VotschTechnikClimateChamber` Python driver; no direct sockets/command numbers in the GUI package. Chamber connection is exclusively server side.
7. The web server remains responsible for ongoing runs when browser windows close or disconnect.

Non-goals for initial release: browser-to-chamber communications; chamber firmware programming; native chamber PROGRAM upload; humidity or unrelated instruments without confirmed driver capability; cloud dependency; preserving the old exe as a supported product.

## 2. Verified current implementation and gaps

### GUI repository
- `VotschTechnikClimateChamber-GUI-2.py` is a ~706-line monolithic Tkinter/Matplotlib application: `DarkThemeThermalChamber`.
- `create_control_tab` (~lines 89–287): IP/connect/disconnect, ID/status, current/target readings, presets, slider/manual temperature, start/stop and live plot.
- `create_settings_tab` (~lines 288–345): chamber IP, temperature bounds, and ramp-rate input.
- `create_logs_tab` (~lines 347–372): in-memory text console.
- `connect_chamber` (~460–484): instantiates `ClimateChamber`. It sets connected UI state before completing the network operation, so errors can leave inconsistent control state.
- `disconnect_chamber` (~486–501): drops the reference without calling driver `disconnect()` (call commented out).
- `save_settings` (~374–424): validates ramp input but does not apply it to the driver or persist settings across application restarts. Updating displayed limits does not update limits of an already-connected driver instance.
- `stop_chamber` (~606–619): calls `tcam.stop()` twice.
- `read_temperature` (~621–650): worker thread mutates Tkinter variables and plots via a 0.5-second loop; raw points retained at most 10,000 in memory with no durable recording or measurement-quality indicator.
- GUI README lists table/CSV temperature profiles only as a future feature. No installed dependency/CI/test or structured profile runner exists in the current tree.
- PyInstaller .spec, build outputs and .exe are tracked. No desktop maintenance after the defined web cutover.

### Python driver repository
- Installable `VotschTechnikClimateChamber`, version 0.2.0; it is a separate dependency and the sole device protocol owner.
- `ClimateChamber.py` supports `id`, `idn`, `temperature_measured`, `temperature_set_point`, `temperature_min/max`, `start()`, `stop()`, `is_running`, `gradient_up`, `gradient_down`, `disconnect()`; socket port 2049.
- Driver uses synchronous TCP, an `RLock` for queries and a default 1-second socket timeout. Query uses `socket.send` followed by one `recv(512)`. A driver-reliability PR should add protocol-focused unit tests, bounded lifecycle behavior and safe full-send/response framing as verified against actual protocol. Do NOT reimplement protocol in GUI.
- `set_and_wait` is synchronous, polls with sleep, prints to console and has no abort/cancel or maximum time to reach the setpoint; **do not use it as the profile engine**.
- Driver `gradient_up/down` setter ranges are 0.01–5 and 0.01–3.5 respectively, but practical units/model support MUST be verified with chamber documentation and VT4011 hardware before exposing them as °C/min.
- Driver `tests/test_package.py` tests package exports, command lookup and one encoding path; there are no comprehensive mocked transport, failure or HIL tests.
- Driver command dictionary mentions native PROGRAM commands but there is no high-level upload/start/status API. Run web-created profiles by sequenced manual setpoints in v1, not by sending undocumented native program commands.

## 3. Target architecture

    Browser(s) ─HTTPS/WebSocket─> NiceGUI UI (session-local widgets only)
                                   │
                                   ▼
                            Application services
                          auth / validation / audit
                        profile CRUD + export / CSV
                                   │
                                   ▼
                            ChamberController
                          single physical device owner
                      command serialization and polling
                                   │
                            Python driver package
                          VotschTechnikClimateChamber
                                   │
                              TCP 2049 to chamber

    Durable layer: SQLite for metadata, profiles/revisions, runs, events and operator lease;
                   per-run append-only CSV files for high-rate samples and exported events.
    Runtime layer: bounded command executor; poller; cancellable profile state machine;
                   immutable run snapshot; shared status event stream.

Critical invariants:
- Browser events never directly call blocking driver methods. Use a single per-chamber controller that serializes hardware I/O, enforces mutually exclusive control and produces immutable telemetry snapshots.
- At most one active profile or manual-control owner per chamber. Read-only viewers may connect concurrently. STOP is available to every authorized operator even when another operator owns the lease.
- No chamber object stored in NiceGUI user/session storage. A browser refresh/reconnect rehydrates state from the server.
- Driver calls must not block the event loop or delay STOP indefinitely; all operations have bounded timeouts and observable errors.
- Never infer physical stop/start solely from a UI command. Poll/verify `is_running`; report unverified result as UNKNOWN/FAULT.
- Physical emergency stop and chamber manufacturer safety limits remain mandatory; browser STOP is not an emergency-stop replacement.
- Web UI/profile runner never sends undocumented controller commands. Device protocol fixes belong in a separately reviewed driver PR with its own tests.

Suggested root-level package layout (no `src/` wrapper):

    chamber_web/
      __init__.py
      main.py                  # NiceGUI startup/routing
      pages/                   # dashboard, profiles, runs, settings, logs
      components/              # reusable chart, alarm, status, editor
      assets/                  # authorized local Visteon logo variants, CSS
      services/                # command service, telemetry, permissions
      execution/               # validated profile schema, profile runner
      persistence/             # SQLite repository, CSV writer, migrations
      adapters/driver.py       # ONLY wrapper around external driver
      design_tokens.py
    tests/
      unit/
      integration/
      e2e/
      hil/
    docs/
      WEB_GUI_MIGRATION_PLAN.md
    pyproject.toml
    README.md
    config.example.toml

## 4. User experience and screen map

Navigation: **Dashboard**, **Profiles**, **Run History**, **Logs**, **Settings**. Persistent app header carries the approved horizontal Visteon logo, 'Climate Chamber Control', selected chamber/model, connection and running state, current UTC/local time and signed-in role. Persistent fault banner and accessible STOP when a chamber is actively controlled.

### Dashboard
- Compact chamber selector (initially one physical chamber; architecture supports future multiple), Connect/Disconnect, ID/model/serial, last-successful reading age and connection status.
- 3 large KPI cards: measured temperature °C, effective setpoint °C, equipment status (OFF/RUNNING/UNKNOWN). Small secondary metrics: active step, remaining/elapsed time and acquisition status.
- Left: preset temperature chips and custom numeric entry/slider, apply/confirmation; start/stop manual operation. Manual setpoint changes are disabled or explicitly transferred/confirmed while a profile owns the chamber.
- Center: live measured + requested setpoint plot with chart legend, time selection, zoom, pause chart and download. Plot is for visualization only; raw CSV preserves every acquired measurement.
- Right: active profile card (profile name/version, step N of M, target, tolerance, stabilization/dwell clock, progress) and active alarms/latest events.
- Show a prominent SIMULATION banner for any fake-driver mode. No silently simulated measured values when disconnected.

### Profiles: operator table editor
- Browse/new/clone/rename/delete with confirm, revision, author and update time; import CSV; export CSV; save draft; validate; show estimate; run from validated immutable revision.
- Editable `ui.aggrid` or NiceGUI table with explicit save/validation events. Row add/remove/duplicate/reorder; enable/disable per step; bulk edit; keyboard navigation, copy/paste and undo where feasible.
- Columns: `step` (positive sequence), `enabled` (bool), `target_temperature_c` (float), `ramp_up_c_per_min` (nullable), `ramp_down_c_per_min` (nullable), `tolerance_c` (positive float), `stabilize_s` (>=0), `dwell_s` (>=0), `reach_timeout_s` (>0), `notes` (text). Profile-level: `name`, `description`, `repeat_count` (>=1), `completion_action` ('STOP' by default; optional explicit HOLD_SETPOINT).
- For ramp fields, `null` means hardware/default behavior, NOT 'zero ramp'. Any requested gradient is validated only after vendor unit/model confirmation.
- Input validation rejects NaN/Infinity, invalid/negative dwell, duplicate/nonsequential steps, empty enabled profile, out-of-range temperature, unsupported ramp, unreachable timeouts and unsafe repeat count. All values revalidated **server-side at run launch** against current driver/chamber safe limits.
- Validation/preview panel graphs intended target-vs-time, labels estimates as *estimates*, and shows warnings/total minimum dwell; it cannot promise hardware ramp times.

Example profile table:

| Step | Enabled | Target °C | Up °C/min | Down °C/min | Tolerance °C | Stable s | Dwell s | Reach timeout s | Notes |
| ---: | :---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | Yes | 25 | — | — | 0.8 | 60 | 300 | 3600 | initial condition |
| 2 | Yes | -20 | — | — | 0.8 | 180 | 600 | 7200 | cold soak |
| 3 | Yes | 85 | — | — | 0.8 | 180 | 600 | 7200 | hot soak |
| 4 | Yes | 25 | — | — | 1.0 | 120 | 300 | 7200 | return to ambient |

### Run History, Logs, Settings
- Run History: searchable run ID/profile revision/operator/start/end/outcome/elapsed; details show step timeline, plot, sampled data CSV and events CSV.
- Logs: structured timestamp/severity/chamber/operator/run/step/message with filtering and bounded browser rendering. Retain audited control actions.
- Settings: approved chamber IP allowlist and connection test, model/serial, temperature limits, readback units, poll/sample interval, startup defaults, data path/quota, CSV settings, user roles, safe stop/timeout policy; profile run settings editable only by authorized role. Do not expose generic raw driver commands.
- Responsive desktop/tablet layout (tablet minimum width to approve); touch-friendly buttons, clear contrast, descriptive units, keyboard support and no temperature-based rainbow styling as primary navigation.

### Branding
- Source logo from Visteon's official [media library](https://www.visteon.com/resources-insights/media-library/default.aspx); use the CURRENT, company-authorized variant (horizontal for header, appropriate monochrome where necessary). Do not redraw or recolor trademark artwork.
- Reusable design tokens: branded navy/teal/blue primary tones and restrained warm/orange accent where approved; light neutral surfaces, high-contrast text, status green/amber/red independently of brand decoration. Confirm final HEX values against approved company assets rather than guessing.
- Provide a consistent Visteon heading, rounded cards, compact data tables, clear active states and restrained animation. Never use color alone to indicate failure.

## 5. Profile execution semantics

Persist an immutable snapshot of the chosen profile revision, chamber identity, limits, operator, start time, application/driver versions and CSV paths for each run.

State diagram:

    IDLE -> VALIDATING -> STARTING -> RAMPING/REACHING -> STABILIZING -> DWELLING
                                      ^                    |               |
                                      |____________________|_______________|
                                             next enabled step / repeat
    RUNNING states -> PAUSED -> RUNNING state
    RUNNING/PAUSED -> STOPPING -> ABORTED
    RUNNING -> COMPLETING -> COMPLETED
    ANY unexpected failure -> FAULT -> best-effort safe STOP + readback
    Interrupted process after restart -> INTERRUPTED; never auto-resume

Rules:
1. Launch requires chamber connection, verified identity, no conflicting run/manual owner, valid temperature limits and operator authorization. Reserve ownership atomically; create run record and initialize recorder **before** issuing START.
2. Per step: set supported gradient only if enabled/validated; issue setpoint through driver; ensure chamber started; wait for measured temperature to enter the inclusive target ± tolerance band.
3. Stabilization requires **continuous** time in band. Every out-of-band sample resets the stabilization timer; missing/stale samples never count as stable.
4. Dwell begins after stabilization and counts only in-band elapsed monotonic time. Out-of-band dwell pauses counting, logs an excursion and can optionally trigger a stricter per-profile safety abort. A configurable absolute per-step watchdog bounds total elapsed time, including pauses.
5. `reach_timeout_s` is a deadline to achieve initial in-band temperature; timeout aborts safely. Separate finite limits on stabilization and dwell completion must be configured to avoid indefinite runs.
6. PAUSE freezes transitions and dwell accounting but keeps chamber at current target and keeps safety polling/logging. RESUME revalidates active state and condition. STOP cancels scheduled steps, requests driver `stop()`, verifies physical status, stops all future setpoint commands and finalizes recorded files. Software-stop failure is a prominent FAULT requiring local intervention.
7. No repeat/skip/manual overrides while RUNNING without explicit audited operator action. No automatic resume after server restart/network reconnect. On restart, reconcile chamber status; mark unfinished runs INTERRUPTED, alert operator and do not guess that physical chamber has stopped.
8. On browser disconnect, run continues server side. On chamber communication loss, mark readings stale immediately, stop advancing the profile, retry with bounded backoff, and attempt safe stop according to a reviewed site policy; fail visible rather than assuming safe shutdown.
9. Never use driver `set_and_wait()` or `time.sleep()` in the UI/event loop; implement cancellable orchestration around short driver reads/writes, monotonic deadlines and serialized I/O.

## 6. CSV contract and persistence

CSV has TWO separate workflows:
A. operator-prepared PROFILE CSV (import/export), and
B. automatically preserved measured run samples and events CSV (autosave during execution).

### Profile CSV v1
- UTF-8 with header, exactly one row per profile step; fields:
  `step,enabled,target_temperature_c,ramp_up_c_per_min,ramp_down_c_per_min,tolerance_c,stabilize_s,dwell_s,reach_timeout_s,notes`.
- Metadata such as name, repeat count, schema version and completion action stored with profile in SQLite, plus an export sidecar `profile.json` when fidelity is required. Optionally provide an export ZIP with both profile.csv and profile.json.
- Import accepts UTF-8 BOM, validates separator/comma vs semicolon, types, bounds, row count, headers, duplicates and schema version. Unknown columns error by default; empty ramp fields become null. Dry-run validation preview; no chamber writes on import.
- Canonical export separator comma, decimal dot, standard CSV quoting, deterministic order and header. Export must round-trip profile steps without precision loss. Formula injection characters in free text escaped for spreadsheet-safe export without breaking canonical machine-readable import (choose and document one reversible policy).

### Run samples CSV v1 (one per run)
Header:
`timestamp_utc,elapsed_s,run_id,chamber_id,step_index,phase,measured_temperature_c,target_temperature_c,chamber_running,sample_quality`.
- UTC RFC3339 timestamps with milliseconds; `elapsed_s` from monotonic clock; empty measured cell when acquisition fails; `sample_quality` indicates GOOD/STALE/ERROR. Do not record synthetic temperatures as valid readings.
- A companion events CSV uses `timestamp_utc,elapsed_s,run_id,step_index,severity,event_code,message,operator`.
- Create run folder and CSV headers at run start; stream append at configurable sample interval (default proposal: 2 seconds). Flush promptly (target <=5 seconds exposure window) and flush/fsync at transitions/finish. Create metadata atomically before first setpoint. If logging becomes unavailable, initiate a defined safe-stop/error policy.
- SQLite stores the run index and events for browsing; avoid storing millions of raw samples in SQLite unless necessary. Retain raw data, and downsample only in chart query response (e.g. <=2,000 rendered points preserving extrema).
- Keep files on server-owned directories with safe generated run IDs; sanitize filenames, guard against CSV injection, limit import size/rows, enforce disk space quota/retention and block user-controlled path traversal.
- Provide download links for profile CSV, run sample CSV, event CSV and an optional ZIP with manifest/checksums. Show data integrity warnings for recovered/incomplete runs.

## 7. Concurrency, security and operability

- Device access: one command serialization point, bounded queue, connection state machine and serialized poller. STOP/abort intent has priority; cancellation prevents previously queued setpoints from executing after STOP.
- Roles: VIEWER (monitor/download), OPERATOR (manual actions, create/edit profiles, run/stop), ADMIN (device config/users). Audit who did what and when. One exclusive control lease per chamber with heartbeat/expiry/recovery; STOP must not require the lease.
- Authentication for the browser, secure cookies and CSRF/origin protections for mutations/websockets. Bind to loopback by default; LAN access only after explicit config; use HTTPS or protected reverse proxy. Do not expose unauthenticated chamber control to the internet.
- Validate and restrict device target addresses to configured allowlist/LAN ranges to avoid use of connection form as arbitrary-network access.
- Support systemd/Windows service launch, configuration from environment/TOML, health/readiness endpoints and durable data path. Never auto-start chamber on server boot.
- Pin compatible driver and NiceGUI dependency ranges with lockfile; driver still maintained in its original repository.
- Choose a **single authoritative server process** for a connected device. Multi-worker processes require an explicit external owner/coordinator and are OUT of initial scope.
- Run count, sample/data retention, audit retention and recovery policy are administrator-configured; default to conservative safe choices.
- On critical warning (over-temperature per configured safe limit, repeated communication timeout, out-of-band dwell, disk full, unverified stop), prevent further profile advancement and surface actionable recovery guidance.

## 8. Delivery PR sequence and acceptance criteria

Every PR must pass lint/type check, unit tests and relevant fake-driver integration tests before merge; do not combine unrelated infrastructure and profile behavior changes.

| PR | Scope | Exit criteria |
|---|---|---|
| 01 | Foundation: packaging, clean root package, CI, settings schema, README, test harness, fake driver | `python -m chamber_web` serves placeholder locally; install/test CI clean; no chamber required. |
| 02 | Visteon NiceGUI shell + responsive layouts/components | Dashboard, Profiles, History, Logs, Settings route successfully; approved logo, tokens and keyboard/touch check; no device changes. |
| 03 | Device adapter, controller, poller, bounded execution, status stream | Driver is sole comm path; connection/identity/poll/stop/timeout behavior tested with fake; shared state survives browser reconnect. |
| 04 | Manual control parity + persistent settings | All existing functional controls operate; true start/stop readback; no erroneous state on connection failure; limit changes enforced. |
| 05 | Profile data/schema/CRUD + AG Grid editor + CSV import/export | Operator can create/save/edit/clone/reorder/reopen/validate/export/import profiles; malformed/out-of-range inputs never reach driver; CSV round trip. |
| 06 | Server-side cancellable profile engine, pause/resume, ownership | Test all state transitions, stable/dwell semantics, reach timeout, repeat, abort latency, browser disconnect and restart interruption. |
| 07 | Autosaving CSV, history, plots, events and downloads | Headers/quality fields valid, raw points preserved, downloadable logs, bounded visual chart points, recover partial runs. |
| 08 | Roles/auth/TLS/deployment, observability, HIL certification | Two browsers cannot start conflicting jobs; STOP always available; health checks; fault injection; real VT4011 test matrix signed off. |
| 09 | Cutover, updated README, desktop deprecation and removal | Support documentation points to web install; last parity checklist complete; stop distributing PyInstaller .exe/build artifacts. |

Driver changes are made as separate, backward-compatible PRs in `ami3go/VotschTechnik-climate-chamber-Python` before consuming new driver features; pin their tested version in GUI. PR 03 should NOT wait for unrelated driver improvements if existing functions can safely support mock/initial implementation.

### Minimum automated tests (fake transport + browser)
- Network connect succeeds/fails/timeouts; disconnect calls driver and clears session; recovery does not pretend chamber is stopped.
- Temperature setpoint boundaries, non-finite input, unsupported gradients, unauthorized actions.
- Start/Stop request/readback conflicts; two tabs/users race to start; concurrent polling never interleaves TCP transactions; no setpoint executes after STOP intent.
- Profile rows reorder/edit/duplicate/disable, CSV import/export/roundtrip, malicious CSV values and formula strings, profile revision conflict.
- Stable-time reset after excursion; dwell pauses on excursion; missing measurement cannot satisfy tolerance; reach/stabilization/absolute step timeout; pause/resume and repeat.
- Browser refresh/disconnect retains active profile; server restart marks run interrupted, never auto-resumes; recovery shows physical hardware readback.
- CSV flushed before chamber command, complete sample and event fields, disk-full behavior, ZIP protection and retention.
- High-volume chart test at >=100k samples, tablet layout and keyboard workflow; chart DOM remains bounded and controls usable.
- HIL: verified chamber VT4011 manual control, gradient unit/range, out-of-range hardware rejection, setpoint readback, stop after fault and network cable unplug.

### Release gates
1. Manual workflows from desktop demonstrated with a VT4011 and *no unimplemented settings falsely represented as functional*.
2. A 4-step cold/hot/ambient table profile successfully runs and produces correctly timed data/events, including pause, resume and controlled stop.
3. Importing then exporting valid CSV steps reproduces all step values, including optional gradients; failed import never changes current profile or chamber state.
4. At least two clients concurrently view one live run without competing hardware ownership; operator closes browser and server-side run continues.
5. Fault tests demonstrate bounded stopping, no unsafe queued setpoints, clear UNKNOWN/FAULT state after communication loss, correct handling of interrupted runs.
6. Full run sample CSV is readable while run is active and final downloads include no silently lost or invented samples; meaningful timestamps and units.
7. Web application runs headless with start-on-boot and documented backup/restore. Desktop artifacts are removed only after sign-off.

## 9. Decisions to confirm before implementation

- Supported physical chambers and actual temperature/gradient limits; validate model/controller differences, especially gradient command units.
- Approved **current** Visteon logo and design tokens; usage rights in a public MIT repository.
- Whether required profile semantics are software-driven only (recommended v1), or native chamber PROGRAM uploads are also needed later.
- In a failure or user STOP, what should the chamber do: power OFF (proposed default), maintain current setpoint, or return to safe ambient? This must follow site/hardware safety policy.
- Preferred run storage period/quota, operators/authentication method and network boundary (single local PC vs LAN-wide lab server).
- Clarify whether 'pre-save CSV' means profile CSV export, measurement autosave, or both; **this plan provides both**.

## 10. Readiness

GO for PR 01 and PR 02 (non-hardware foundation/UI) and fake-driver development.
CONDITIONAL GO for manual hardware integration and profile engine until gradient units, safe stop policy, operator ownership behavior and chamber-in-the-loop test access are settled.
NO-GO for desktop removal until the above release gates are verified on real hardware.
