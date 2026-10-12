# NiceGUI web migration and profile execution plan

Status: **ACTIVE SPECIFICATION / PARTIALLY IMPLEMENTED** (GUI `main` `ef473e1`, driver `main` `9323e37`, verified 2026-10-12). D01 driver transport, G01 backend foundation, P00 software contracts and G03 CSV/ZIP core have merged. The web GUI is still a demo without production control/persistence/authentication/runner; physical release remains **NO-GO** pending site signoff, HIL and offline gates. Current phase statuses and proposed PR sequence: [DEVELOPMENT_SEQUENCE.md](DEVELOPMENT_SEQUENCE.md); findings: [READINESS_FINDINGS.md](READINESS_FINDINGS.md).
Repositories reviewed: [GUI](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI) main and [Python driver](https://github.com/ami3go/VotschTechnik-climate-chamber-Python) main (2026-10-12).
Owner decision: The NiceGUI web application replaces Tkinter. Desktop GUI support will be discontinued after web acceptance.

## 1. Goals, boundaries, and non-goals

1. Provide a responsive, browser-based operator interface on a chamber-connected Windows/Linux/Raspberry Pi host.
2. Preserve ALL existing functional desktop workflows: connect/disconnect and chamber identity; current/target temperature; preset and custom setpoint; start/stop; limits; chart; logs.
3. Add operator-authored multi-step temperature profiles through an editable table, CSV import/export, profiles saved between sessions, and server-side execution with progress, pause/resume, abort, history and recovery.
4. Save sampled measurements incrementally to CSV during runs, not only after completion. Permit retrieval of profiles, measurement logs and event logs as CSV.
5. Apply Visteon-approved identity/logo to a clean and accessible UI.
6. ALL GUI screens, profile editor/runner, persistence and shared services MUST depend on a generic `ChamberBackend` abstraction, never directly on a manufacturer driver. Only `VotschBackend` uses the separately maintained `VotschTechnikClimateChamber` driver for Vötsch hardware communication. Future manufacturers use their own adapters/external drivers. The GUI package never reimplements physical chamber protocol. See [CHAMBER_ABSTRACTION_CONTRACT.md](CHAMBER_ABSTRACTION_CONTRACT.md).
7. The web server remains responsible for ongoing runs when browser windows close. In v1 only ONE physical chamber per deployment is allowed; device-scoped `chamber_id` contracts prepare for future multiple chambers. See [FUTURE_MULTI_CHAMBER_ARCHITECTURE.md](FUTURE_MULTI_CHAMBER_ARCHITECTURE.md).

Non-goals for initial release: browser-to-chamber protocol, firmware programming, native PROGRAM upload, unverified humidity, cloud dependency, old desktop support, second real vendor driver, and MULTIPLE simultaneous physical chambers/fleet UI/parallel profiles. v1 MUST have a future-proof stable `chamber_id`, one-device cardinality validation, generic backend interface and sequential alternate-backend tests.

## 2. Verified current implementation and gaps

### Current implementation, post-fix (2026-10-12)

- The NiceGUI `chamber_web/main.py` continues to use the demo simulator; generic G01 backends are **not yet connected to the pages or production controller**.
- G01 abstraction, stable chamber identity, fake/alternate/mock Vötsch adapters and one-device guard are merged in [GUI #7](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/7) and [#9](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/9); physical Vötsch connections deliberately remain disabled.
- G03 CSV/ZIP profile core and lossless legacy-source ZIP preservation are merged in [GUI #8](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/8), without SQLite revision storage, AG Grid editor, profile runner or run recorder.
- D01 driver transport/STOP uncertainty improvements are merged in [driver #2](https://github.com/ami3go/VotschTechnik-climate-chamber-Python/pull/2) (`9323e37`) and pinned by [GUI #10](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/10). Automated driver tests pass, **physical STOP/framing is not HIL certified**.
- The following original Tkinter and pre-D01 driver observations are **historical audit context**, not a claim that these merged foundations remain absent.

### Legacy Tkinter GUI baseline (historical)
- `VotschTechnikClimateChamber-GUI-2.py` is a ~706-line monolithic Tkinter/Matplotlib application: `DarkThemeThermalChamber`.
- `create_control_tab` (~lines 89–287): IP/connect/disconnect, ID/status, current/target readings, presets, slider/manual temperature, start/stop and live plot.
- `create_settings_tab` (~lines 288–345): chamber IP, temperature bounds, and ramp-rate input.
- `create_logs_tab` (~lines 347–372): in-memory text console.
- `connect_chamber` (~460–484): instantiates `ClimateChamber`. It sets connected UI state before completing the network operation, so errors can leave inconsistent control state.
- `disconnect_chamber` (~486–501): drops the reference without calling driver `disconnect()` (call commented out).
- `save_settings` (~374–424): validates ramp input but does not apply it to the driver or persist settings across application restarts. Updating displayed limits does not update limits of an already-connected driver instance.
- `stop_chamber` (~606–619): calls `tcam.stop()` twice.
- `read_temperature` (~621–650): worker thread mutates Tkinter variables and plots via a 0.5-second loop; raw points retained at most 10,000 in memory with no durable recording or measurement-quality indicator.
- The original desktop README listed table/CSV profiles as future work; the current NiceGUI tree now has CI and CSV/ZIP profile-core tests but still lacks a persistent editor and server-runner.
- PyInstaller .spec, build outputs and .exe are tracked. No desktop maintenance after the defined web cutover.

### Python driver repository
- Installable `VotschTechnikClimateChamber`, version 0.2.0; it is a separate dependency and the sole device protocol owner.
- `ClimateChamber.py` supports `id`, `idn`, `temperature_measured`, `temperature_set_point`, `temperature_min/max`, `start()`, `stop()`, `is_running`, `gradient_up`, `gradient_down`, `disconnect()`; socket port 2049.
- **Pre-D01 historical issue:** driver previously called `socket.send` with a single `recv(512)` and set timeout after connect. Driver `9323e37` now sets connection deadlines, uses `sendall`, and reads bounded frames under test. Site firmware behavior still requires HIL. Do NOT reimplement protocol in GUI.
- `set_and_wait` is synchronous, polls with sleep, prints to console and has no abort/cancel or maximum time to reach the setpoint; **do not use it as the profile engine**.
- Driver `gradient_up/down` setter ranges are 0.01–5 and 0.01–3.5 respectively, but practical units/model support MUST be verified with chamber documentation and VT4011 hardware before exposing them as °C/min.
- `tests/test_package.py` covers package fundamentals; D01 added mocked transport/STOP/failure regression tests in `tests/test_transport.py`, passing Python 3.9/3.12. **Site-approved physical HIL remains absent.**
- Driver command dictionary mentions native PROGRAM commands but there is no high-level upload/start/status API. Run web-created profiles by sequenced manual setpoints in v1, not by sending undocumented native program commands.

## 3. Target architecture

    Browser(s) --> NiceGUI pages --> application services / profile engine
                                             |
                                             v
                             ChamberController(chamber_id)
                    ownership / STOP fencing / serialized device I/O
                                             |
                                             v
                          ChamberBackend Protocol (vendor-neutral)
                                             |
                                    allowlisted registry
                                        /           \
                                       v             v
                                 VotschBackend    FakeBackend
                                       |          (simulation/test)
                                 Vötsch Python driver       Future backend adapter
                                       |                       | external vendor driver
                                     VT4011

    Durable layer: SQLite for metadata, profiles/revisions, runs, events and operator lease;
                   per-run append-only CSV files for high-rate samples and exported events.
    Runtime layer: bounded command executor; poller; cancellable profile state machine;
                   immutable run snapshot; shared status event stream.

**Normative contracts:** [CHAMBER_ABSTRACTION_CONTRACT.md](CHAMBER_ABSTRACTION_CONTRACT.md) defines the vendor-independent driver interface; [FUTURE_MULTI_CHAMBER_ARCHITECTURE.md](FUTURE_MULTI_CHAMBER_ARCHITECTURE.md) specifies strict v1 one-device enforcement and the deferred MC01–MC05 multi-chamber design. The architecture is ready for future fleet expansion; no fleet implementation is included in v1.

Critical invariants:
- Browser events never directly call blocking backend methods. The generic, `chamber_id`-scoped controller owns serialization, STOP and leases, and provides normalized status snapshots; **v1 allows only one configured physical controller**.
- At most one active profile or manual-control owner per chamber, enforced by a single OS-level server process/chamber lock plus transactional SQLite control lease and generation fencing. STOP is allowed for any authorized OPERATOR/ADMIN without lease ownership, and invalidates queued older-generation writes.
- No chamber object stored in NiceGUI user/session storage. A browser refresh/reconnect rehydrates state from the server.
- Driver calls never block the NiceGUI event loop. STOP intent must be registered and fence future writes immediately; an in-flight blocking transport call cannot be assumed preemptible. Use finite driver deadlines and report attempted STOP separately from verified physical stop. On failed/unavailable readback report UNKNOWN/FAULT and local intervention.
- Never infer physical stop/start solely from a UI command. Poll/verify `is_running`; report unverified result as UNKNOWN/FAULT.
- Physical emergency stop and chamber manufacturer safety limits remain mandatory; browser STOP is not an emergency-stop replacement.
- Web UI/profile runner never import manufacturer-specific libraries, create device sockets, inspect vendor/model names to select control logic, or send raw commands. Only `chamber_web/adapters/votsch.py` imports the Vötsch driver; manufacturer-specific protocol fixes stay in the corresponding external driver repository.

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
      domain/chamber.py         # ChamberBackend Protocol, identity/capability/status/errors
      adapters/registry.py      # typed allowlisted backend factory
      adapters/votsch.py        # sole import of existing Vötsch driver
      adapters/fake.py          # deterministic simulated backend
      services/chamber_manager.py # chamber_id-based interface; v1 maximum one physical device
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

### v1 physical-device limit and far-future extension seam

- First release: zero or one configured physical chamber, one live device controller and at most one running profile; fail validation if a second physical chamber is configured. Different Fake/vendor-stub devices are tested as **substitutes in separate single-device runs**, never simultaneously.
- Keep stable `chamber_id` in command routing, device configuration, ownership, run manifests, samples/events/audits, and namespaced server-owned `data/chambers/<chamber_id>/runs/<run_id>/`. Profiles remain hardware-neutral.
- Define a small controller manager interface returning the only configured physical chamber in v1; unknown IDs are rejected. Do not implement multi-controller instantiation, multi-device polling, selectors, parallel profile scheduling or fleet management.
- When multi-chamber support is actually scheduled, perform separate MC01–MC05 requirements, safety review, implementation, tests and HIL as described in [FUTURE_MULTI_CHAMBER_ARCHITECTURE.md](FUTURE_MULTI_CHAMBER_ARCHITECTURE.md).

## 4. User experience and screen map

Navigation: **Dashboard**, **Profiles**, **Run History**, **Logs**, **Settings**. Header shows approved Visteon logo, the sole configured chamber's identity/connection/running state, UTC/local time and role. STOP applies to that chamber; any fleet/selector view is deferred.

### Dashboard
- In v1 show only the configured chamber's label/ID/model/serial, Connect/Disconnect, reading age and connection status; no multi-chamber selector or overview required. Keep service data bound to explicit `chamber_id` and capability-driven controls.
- 3 large KPI cards: measured temperature °C, effective setpoint °C, equipment status (OFF/RUNNING/UNKNOWN). Small secondary metrics: active step, remaining/elapsed time and acquisition status.
- Left: preset temperature chips and custom numeric entry/slider, apply/confirmation; start/stop manual operation. Block manual changes while a profile owns the chamber; manual takeover requires audited abort/finish, confirmed safe release of the owner lease and an explicit new action.
- Center: live measured + requested setpoint plot with chart legend, time selection, zoom, pause chart and download. Plot is for visualization only; raw CSV preserves every acquired measurement.
- Right: active profile card (profile name/version, step N of M, target, tolerance, stabilization/dwell clock, progress) and active alarms/latest events.
- Show a prominent SIMULATION banner for any fake-driver mode. No silently simulated measured values when disconnected.

### Profiles: operator table editor
- Browse/new/clone/rename/delete with confirm, revision, author and update time; import CSV; export CSV; save draft; validate; show estimate; run from validated immutable revision.
- Editable `ui.aggrid` or NiceGUI table with explicit save/validation events. Row add/remove/duplicate/reorder; enable/disable per step; bulk edit; keyboard navigation, copy/paste and undo where feasible.
- Columns: `step` (positive sequence), `enabled` (bool), `target_temperature_c` (float), `ramp_up_c_per_min` (nullable), `ramp_down_c_per_min` (nullable), `tolerance_c` (positive float), `stabilize_s` (>=0), `dwell_s` (>=0), `reach_timeout_s` (>0), `notes` (text). Profile-level: `name`, `description`, `repeat_count` (>=1), `completion_action` ('STOP' by default; optional explicit HOLD_SETPOINT).
- For ramp fields, null means **RESTORE_VERIFIED_BASELINE** (not zero, inherited previous-step gradient, or an arbitrary hardware default). Preflight must read/capture a certified baseline for *both* gradient directions, resolve every step to an explicit effective value, and restore/read back baseline when a prior step changed a gradient. No writes at all when every step is null and verified baseline remains unchanged. If baseline/readback/restore is unavailable, a profile requiring a changed gradient is not runnable. Fault/STOP must attempt restoration according to signed site policy and never claim success without readback. All non-null gradients remain disabled until model-specific HIL certification. See [P00_DECISION_CONTRACTS.md](P00_DECISION_CONTRACTS.md).
- Input validation rejects NaN/Infinity, unsupported/stale model capabilities, conflicting limits, nonsequential steps, empty enabled profiles, impossible timeouts, unsafe repeat counts, unsupported ramps and out-of-range targets. Validate on the server at save AND launch, using the intersection of certified physical/model/configured safe limits, never plot bounds.
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
- Settings: validated single-device `chamber_id`/backend/configuration with `physical_device_count <= 1` in v1, safe model limits, sample interval, storage, roles and fault policy. Reject a second physical chamber BEFORE connection; disallow backend changes during running/UNKNOWN status.
- Responsive desktop/tablet layout (tablet minimum width to approve); touch-friendly buttons, clear contrast, descriptive units, keyboard support and no temperature-based rainbow styling as primary navigation.

### Branding
- Source logo from Visteon's official [media library](https://www.visteon.com/resources-insights/media-library/default.aspx); use the CURRENT, company-authorized variant (horizontal for header, appropriate monochrome where necessary). Do not redraw or recolor trademark artwork.
- Reusable design tokens: branded navy/teal/blue primary tones and restrained warm/orange accent where approved; light neutral surfaces, high-contrast text, status green/amber/red independently of brand decoration. Confirm final HEX values against approved company assets rather than guessing.
- Provide a consistent Visteon heading, rounded cards, compact data tables, clear active states and restrained animation. Never use color alone to indicate failure.

## 5. Profile execution semantics

Persist an immutable snapshot of profile revision plus `chamber_id`, `backend_id`, manufacturer/model/serial, adapter/driver versions, certified capabilities/envelope fingerprint, canonical units, operator, start time and CSV paths. Profiles remain vendor-neutral and are revalidated against backend capabilities at execution.

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
2. Per step: validate current `ChamberCapabilities`; only request certified supported gradients, send target setpoint and start via `ChamberController`/`ChamberBackend`, verify running/setpoint status and wait for measured temperature to enter inclusive tolerance. Fail closed if required features are unsupported; no vendor-specific shortcuts.
3. Stabilization is governed by [P00_DECISION_CONTRACTS.md](P00_DECISION_CONTRACTS.md): for positive stabilize_s, two distinct GOOD/fresh in-band readings must span the configured interval with no disqualifying gap; for zero stabilize_s, the first GOOD/fresh in-band reading is enough. Any gap, stale/error sample or excursion resets stabilization. Samples do not prove physical continuity between observations.
4. Dwell starts after stabilization and accumulates only monotonic intervals bracketed by GOOD/fresh in-band readings. Missing/stale/out-of-band/PAUSED time never counts; excursions are logged and may trigger policy-driven abort. An absolute step watchdog continues even on PAUSE.
5. reach_timeout_s starts at successful setpoint dispatch and bounds initial valid in-band observation; independent finite stabilization, dwell-completion, absolute step and total run deadlines are mandatory. All time accounting uses monotonic clocks.
6. PAUSE freezes transitions/dwell but retains physical regulation, polling and absolute watchdogs. RESUME revalidates state, identity, owner lease and fresh data. STOP atomically fences queued control, attempts driver stop and verifies physical readback when possible; unverified results remain UNKNOWN/FAULT, never 'stopped'.
7. No repeat/skip/manual override during RUNNING. On process restart, acquire process lock, invalidate old command generations, mark unfinished runs INTERRUPTED, poll real hardware, require deliberate operator reconciliation, never auto-resume or auto-clear alarms.
8. Browser disconnect does not stop supervised server-side execution; on chamber communication loss invalidate freshness, stop advancing profile, retry with bounded policy and attempt safe action per signed site matrix. A disconnected chamber must never be asserted physically stopped.
9. Never use driver `set_and_wait()` or `time.sleep()` in the UI/event loop; implement cancellable orchestration around short driver reads/writes, monotonic deadlines and serialized I/O.

## 6. CSV contract and persistence

CSV has TWO separate workflows:
A. operator-prepared PROFILE CSV (import/export), and
B. automatically preserved measured run samples and events CSV (autosave during execution).

### Profile CSV v1
- UTF-8 with header, exactly one row per profile step; fields:
  `step,enabled,target_temperature_c,ramp_up_c_per_min,ramp_down_c_per_min,tolerance_c,stabilize_s,dwell_s,reach_timeout_s,notes`.
- Standalone profile.csv is *step-only* and requires separately supplied/defaulted metadata. Canonical lossless full-profile interchange MUST be a versioned ZIP containing profile.csv and profile.json with name/description/repeat_count/completion_action/schema version, plus checksums and archive limits.
- Import accepts UTF-8 BOM and normal quoted CSV newlines, validates delimiter without silently changing decimal meaning, duplicate headers, finite types, row/size limits and schema version; ZIP imports validate entry names, expansion, checksums and metadata. Unknown columns error by default; null gradients are empty. Failed import never changes saved profile or chamber. **Demo six-column CSV must be detected explicitly**: legacy `ramp` is simulation-only, is NEVER promoted to certified up/down hardware gradients, and its original value is preserved as migration metadata in a canonical ZIP (otherwise import/export reports a lossy-conversion warning). See [P00_DECISION_CONTRACTS.md](P00_DECISION_CONTRACTS.md).
- Canonical machine CSV uses comma delimiter, decimal dot, reversible numeric/text values, deterministic quoting/order and no precision loss; formula-like text is preserved but is NOT spreadsheet-safe. Provide a separate explicitly labeled spreadsheet-safe export with a documented potentially non-lossless neutralization policy.

### Run samples CSV v1 (one per run)
Header:
`sample_index,timestamp_utc,elapsed_s,run_id,chamber_id,step_index,phase,measured_temperature_c,target_temperature_c,chamber_running,sample_quality`.
- UTC RFC3339 timestamps with milliseconds; `elapsed_s` from monotonic clock; empty measured cell when acquisition fails; `sample_quality` indicates GOOD/STALE/ERROR. Do not record synthetic temperatures as valid readings.
- A companion events CSV uses `timestamp_utc,elapsed_s,run_id,chamber_id,step_index,severity,event_code,message,operator`, with backend/driver/serial/capabilities in immutable run metadata.
- Before any START/setpoint, commit an immutable run/settings/profile snapshot and recording-ready state, create run folder/CSV headers/atomic manifest, then stream samples with monotonically increasing sample_index (proposed 2 s polling). Flush within the defined exposure window (target <=5 s), fsync critical transitions, checksum/finalize after close. SQLite and filesystem are **not one atomic transaction**; implement the durable PREPARED/START_INTENT/RUNNING/FINALIZING/TERMINAL recovery protocol and crash matrix in [P00_DECISION_CONTRACTS.md](P00_DECISION_CONTRACTS.md). Detect incomplete fragments/SQLite mismatch on restart; recorder failures trigger signed FAULT/stop policy and never fabricated samples.
- SQLite stores the run index and events for browsing; avoid storing millions of raw samples in SQLite unless necessary. Retain raw data, and downsample only in chart query response (e.g. <=2,000 rendered points preserving extrema).
- Keep files on server-owned directories with safe generated run IDs; sanitize filenames, guard against CSV injection, limit import size/rows, enforce disk space quota/retention and block user-controlled path traversal.
- Provide download links for profile CSV, run sample CSV, event CSV and an optional ZIP with manifest/checksums. Show data integrity warnings for recovered/incomplete runs.

## 7. Concurrency, security and operability

- Device access: one per-chamber serialized bounded queue, generation-fenced writes, poller and OS process lock. STOP intent is latched before queue scheduling, cancels/fences stale writes and is never equated with physical confirmation. Handle uncertain TCP acknowledgements without blindly repeating non-idempotent commands.
- Roles: VIEWER (monitor/download), OPERATOR (manual, profile CRUD/run/STOP), ADMIN (config/users). **G08-min must authorize all physical mutations on loopback as well as LAN before G05 or live HIL.** Audit mutations/denials. Transactional SQLite exclusive lease with generation and expiry plus OS process lock; check ownership token immediately before dispatch. STOP needs authorization, not the owner's lease; expiration does not clear physical faults.
- Browser authentication requires offline local first-run admin enrollment, credential recovery, secure cookies, session expiry and HTTP/WebSocket CSRF/origin checks; loopback by default, explicit HTTPS/protected proxy when LAN-enabled, no unauthenticated mutations or internet exposure.
- Validate and restrict device target addresses to configured allowlist/LAN ranges to avoid use of connection form as arbitrary-network access.
- Support independently supervised Windows service/systemd lifecycle and an explicitly limited portable per-user mode; closing a browser/launcher cannot stop an active service run, while user logoff MAY stop portable mode and must be documented/guarded. Distinguish process liveness, application readiness, driver connectivity and verified physical equipment state. Never auto-start chamber on server boot.
- Pin NiceGUI, contract version, registered backend versions and tested external driver dependencies. Vötsch transport stays in its separately maintained driver; supporting another vendor adds a dedicated adapter and its separately maintained driver, not GUI command logic.
- Enforce one authoritative server process and **one physical chamber/controller in v1**. Keep OS lock, lease and command fencing scoped to `chamber_id` for later expansion; do not implement parallel controllers or fleet orchestration yet.
- Run count, sample/data retention, audit retention and recovery policy are administrator-configured; default to conservative safe choices.
- On over-temperature per certified safety envelope, communication failure, invalid identity, stale data, out-of-band safety alarm, disk full or unverified STOP: prevent profile advancement, apply signed fault matrix and surface operator recovery guidance. Freeze target IP, safety limits, poll policy and recording path for each active run.

## 7A. Mandatory review-closure contracts

All of the following are required before a physical-control release and are expanded into specific PR tasks/tests in [DEVELOPMENT_SEQUENCE.md](DEVELOPMENT_SEQUENCE.md). Unknown decisions remain PENDING SITE SIGNOFF, not automatically approved defaults.

1. **Signed physical failure matrix:** specify requested device action, verification evidence, UNKNOWN/FAULT, operator alarm/intervention and HIL test for completion, STOP, communication error, readback mismatch, over-limit temperature, logging outage, service crash/logoff, power cycle and hardware alarm. Web STOP is not an emergency stop; do not assume ambient ramp is inherently safe.
2. **Verified device capability registry:** `ChamberBackend` reports actual manufacturer/model/serial and site-certified safe temperature limits, supported start/stop/readback, gradients, units/ranges and polling behavior. UI/profile engine automatically reject unsupported actions. Require conformance testing and safe capability snapshots; see [abstraction contract](CHAMBER_ABSTRACTION_CONTRACT.md).
3. **Driver and adapter boundary:** `VotschBackend` alone imports `VotschTechnikClimateChamber`, and real Vötsch I/O passes exclusively through that hardened external driver. Future vendor adapters must use independent dedicated drivers. Generic GUI/controller/runner must not import vendor drivers, implement protocols or silently fall back to simulation.
4. **Control ownership and fencing:** generic `ChamberController(chamber_id)`, one-device manager, per-device-ready lock/lease/generation and STOP fence. Reject second physical device and wrong/stale ID before I/O. Future multi-device controller concurrency and cross-chamber isolation HIL are deferred to MC01–MC05.
5. **Observational profile semantics:** monotonic time, fresh GOOD samples only, inclusive tolerance, gap resets stabilization, dwell credit only for eligible observed intervals, explicit PAUSE/deadline behavior and finite per-stage/per-run watchdogs. Deterministic virtual-clock tests required.
6. **Lossless persistence:** canonical versioned ZIP with profile.csv + profile.json; plain CSV is step-only. Reversible machine CSV and separately spreadsheet-safe export; sample_index, atomic run manifest, crash reconciliation, durable event recording, quota/ENOSPC response and incomplete-file warnings.
7. **Offline operational/security lifecycle:** local admin first-run enrollment, role permissions, LAN TLS/proxy, browser-independent supervised server, documented portable logoff limits, separate liveness/readiness/device status, migration backups, rollback compatibility, verified offline assets and Visteon licensing.
8. **Quality evidence:** adapter/static import tests, different-vendor stubs tested ONE AT A TIME, second-physical-device rejection, wrong/stale `chamber_id` dispatch denial, namespace/metadata checks, scale tests, offline Windows and VT4011 HIL. No simultaneous multi-chamber testing in v1.
## 8. Windows builds: native web launcher and complete offline distribution

Two separate, maintained build scripts are **mandatory**, committed to the GUI repository and exercised by Windows CI. The scripts MUST have distinct responsibilities; a shortcut, README-only instructions, or a Windows desktop rewrite does not satisfy this requirement.

### Script A — `scripts/build_windows_launcher.ps1`

**Purpose:** Build a Windows **web launcher** executable (`ClimateChamberLauncher.exe`) and a Start Menu/Desktop shortcut configuration that opens the NiceGUI application in the default browser, without reimplementing any UI as a Windows desktop application.

Required behavior and output:
- Build on Windows using a pinned toolchain; emit `dist/windows-launcher/ClimateChamberLauncher.exe`, version information, Visteon-authorized icon and a generated build manifest.
- The launcher discovers an installed independently supervised server using an authenticated instance identity/OS lock, never trusts arbitrary process occupying port; starts/attaches as configured and waits for distinct app readiness, then opens local browser. In portable mode document logoff/reboot limits; never create duplicate controller.
- Default to loopback. Respect configured host/port and open the proper URL when HTTPS/reverse-proxy mode is configured, while ensuring the launcher never inadvertently exposes the service publicly. Distinguish an occupied non-app port from a running authenticated app; never blindly trust another process at the configured port.
- Show actionable dialogs or log locations for missing server installation, invalid configuration, blocked port, startup failure, missing permissions and initial authentication. Avoid spawning visible terminal windows during normal operator operation.
- Closing browser or launcher must not end a supervised service run; per-user portable mode cannot promise logoff continuity. Explicit service shutdown follows signed STOP/reconciliation matrix; forced power loss is not a verifiable physical STOP.
- Launcher build may target an already-installed online application; **the launcher alone is not represented as an offline install**. Document the dependency on the installed application and distinguish its artifact clearly from the complete distribution.
- Build flags: `-Clean`, `-OutputDir`, `-Configuration`, `-Version` (or equivalent documented parameters). The build fails nonzero if a step or artifact verification fails.

### Script B — `scripts/build_windows_offline.ps1`

**Purpose:** On an **internet-connected Windows build host**, construct a complete, portable, self-contained **offline Windows application bundle** (versioned ZIP or installer) which can be transferred by USB to a Windows computer **without internet access** and launched locally. The **installed runtime must make zero network calls to package repositories, CDNs or cloud services**. Local loopback and configured LAN access to the physical chamber are allowed.

Mandatory artifact and dependencies:
- Emit `dist/ClimateChamber-Web-Windows-x64-<version>-offline.zip` and a SHA-256 checksum manifest; optionally emit signed installer as an additional artifact, not a substitute for the ZIP.
- Include NiceGUI server, Windows launcher, runtime, all allowlisted backend adapters plus their pinned vendor drivers (including the existing Vötsch driver), NiceGUI/Quasar/AG Grid/plot assets, local fonts/icons, approved branding, configuration, licenses and manifest. Do not load plugins/dependencies dynamically from internet on target.
- Do not ship or depend on a **copied virtual environment** that embeds development-host absolute paths. Prefer a pinned, reproducible Windows `PyInstaller --onedir`-style frozen server distribution (or an equivalently verified embedded-Python layout). Build natively on Windows for supported architecture; no assumed Linux-to-Windows cross-compilation.
- Preserve the Python `VotschTechnikClimateChamber` driver as the sole protocol owner for Vötsch chambers, called only through `VotschBackend`. Future vendors each use their own external driver under `ChamberBackend`; generic UI never duplicates device protocol.
- Installer/ZIP extracts writable user data/CSV/SQLite to persistent Windows user or ProgramData location separate from installation, protected by OS ACLs, with backup-before-schema-migration, incompatible-downgrade refusal and recovery policy; requires offline first-run admin enrollment. Normal portable launch needs no admin privileges.
- Treat the Windows browser as an explicitly verified OS prerequisite (e.g. installed Edge/other default browser); if an air-gapped target cannot provide one, supply an optional legally redistributable bundled browser or compatible offline webview mode, without downloading components on the target.
- Self-contained web assets: audit rendered pages for remote scripts, fonts, stylesheets, CDN-hosted assets, telemetry/update checks and online authentication. Configure local alternatives or disable these features. No `pip`, `uv`, `npm`, `dotnet restore`, Git, remote URLs or network installer steps on the **target PC**.
- Test against a clean Windows x64 VM with **no Python, pip, uv, Node.js, development tools or internet connectivity**; only the documented OS baseline/browser and direct chamber LAN (or fake device) may be assumed.
- Provide `README_OFFLINE_WINDOWS.md`: how to build, version/support matrix, transfer via USB, verify SHA-256, extract/install, start/stop server, open UI, select/configure chamber IP, store/backup logs and profiles, update to a newer offline bundle and roll back without data loss.
- Fail build on unresolved imports, missing assets, missing DLL/driver, omitted licenses, non-matching hashes or smoke-test failure. Include a machine-readable manifest with Python/package/driver versions, lockfile hash and bundled file hashes.
- Rebuild from pinned hashed dependencies in a clean Windows workdir, with licenses/SBOM/integrity metadata, no secrets or cached dist. Test offline upgrade N -> N+1 and rollback with real profiles, history and interrupted runs, preserving external data or restoring pre-migration backup.

### Separation and workflow

1. Script A can be run independently to produce the thin Windows web launcher for a normal deployment.
2. Script B orchestrates a clean app freeze, **invokes or incorporates Script A**, assembles the complete runtime and local assets, verifies its manifest and creates the transfer archive; operators use the same launcher UX in both deployment styles.
3. CI on Windows tests Script A startup/re-use and Script B extraction/launch. Release artifacts are attached to tagged GitHub releases instead of committing binaries into the source repository.
4. App startup is never coupled to a browser session: closing the launcher/browser leaves profile execution controlled by the server/service policy. Restarting the launcher attaches to the existing server; conflicting owners are rejected.
5. The offline runtime may communicate with the physical chamber over a private network, but **never requires general internet connectivity**. Tests must block internet egress to prove this.

### Windows packaging acceptance criteria

- Launcher executable starts a local installed server, waits for readiness, opens browser and reports missing/occupied-port failures; second invocation does not launch a second server.
- A running profile continues after the browser is closed and reopened; logs/CSV continue to be written.
- Offline archive extracted on a clean internet-disconnected Windows 10/11 x64 VM starts from the bundled launcher, renders dashboard and profile editor, executes a fake-device profile, saves CSV, and performs CSV import/export with **no runtime downloads**.
- Package runs without Python/pip/uv/Node/npm or admin privileges, assuming only the documented supported OS/browser; all assets load locally.
- Repeated launches, graceful app/server shutdown and update/rollback keep durable settings/history/profile data intact; executable and ZIP checksum manifests match expected hashes.

## 9. Review-gated development sequence and acceptance

**Authoritative implementation plan:** [DEVELOPMENT_SEQUENCE.md](DEVELOPMENT_SEQUENCE.md). Its phase IDs refer to work items, not existing GitHub PR numbers. Each phase gets a separate focused PR, independently reviewed with test evidence and blocker/high issues corrected before merge.

| Phase | Scope and gate |
|---|---|
| P00 | Resolve and sign off safety matrix, gradient capability and timing/data/ownership/lifecycle contracts; record pending site decisions |
| D01 (driver repo) | Harden finite TCP connect/send/response, numeric safety and mocked failure tests; pin tested driver before live integration |
| G01–G03 | Backend interface, typed `chamber_id`, one-device manager/configuration schema and guard, Fake/Vötsch/second-vendor stub sequential tests, single-chamber NiceGUI and versioned data |
| W01 (early, parallel) | Both Windows launcher and offline-build script feasibility with frozen fake-driver server |
| G04–G06 | ONE active generic `ChamberController(chamber_id)`, scoped STOP/leases, manual control and profile runner; reject second physical chamber and invalid ID |
| G07–G08 | Crash-safe recording, history/performance, multiuser roles/auth and supervised lifecycle |
| H01 | Site-approved real VT4011/LabEvent HIL incl. gradient verification, faults and STOP readback |
| W02 | Clean air-gapped Windows x64 launcher/offline ZIP, upgrade/rollback and data preservation |
| R01 | Formal release signoff and legacy-desktop retirement only after H01 and W02 |

Developer must follow dependency prerequisites and full acceptance checklist in the linked sequence. Simulated tests alone do not certify hardware safety. Driver modifications remain in the separate driver repository.
### Minimum automated tests (fake transport + browser)
- Network connect succeeds/fails/timeouts; disconnect calls driver and clears session; recovery does not pretend chamber is stopped.
- Temperature setpoint boundaries, non-finite input, unsupported gradients, unauthorized actions.
- Start/Stop request/readback conflicts; two tabs/users race to start; concurrent polling never interleaves TCP transactions; no setpoint executes after STOP intent.
- Profile rows reorder/edit/duplicate/disable, CSV import/export/roundtrip, malicious CSV values and formula strings, profile revision conflict.
- Stable-time reset after excursion; dwell pauses on excursion; missing measurement cannot satisfy tolerance; reach/stabilization/absolute step timeout; pause/resume and repeat.
- Browser refresh/disconnect retains active profile; server restart marks run interrupted, never auto-resumes; recovery shows physical hardware readback.
- CSV flushed before chamber command, complete sample and event fields, disk-full behavior, ZIP protection and retention.
- High-volume chart test at >=100k samples, tablet layout and keyboard workflow; chart DOM remains bounded and controls usable.
- HIL: VT4011 control exclusively through `VotschBackend` and existing Vötsch driver, gradient units/readback, limits, STOP under faults and network loss; separate Fake and second-vendor-stub conformance and generic UI/runner tests.
- Windows launcher: port conflict and readiness timeout, duplicate starts, browser close/reopen during a running profile, troubleshooting logs, path with spaces/non-ASCII.
- Windows offline: clean VM with internet disabled, no developer runtimes, complete static asset load, profile CSV round-trip, sample CSV recording, offline updates/rollback, file integrity, and zero external network fetches.

### Release gates
1. Test manual VT4011 workflow through generic backend and separately run the same UI/runner with a second-vendor stub. Reject simultaneous second physical device configuration; no generic manufacturer branching; wrong/stale `chamber_id` must fail before sending commands.
2. A 4-step cold/hot/ambient table profile successfully runs and produces correctly timed data/events, including pause, resume and controlled stop.
3. Importing then exporting valid CSV steps reproduces all step values, including optional gradients; failed import never changes current profile or chamber state.
4. At least two clients concurrently view one live run without competing hardware ownership; operator closes browser and server-side run continues.
5. Fault tests demonstrate bounded stopping, no unsafe queued setpoints, clear UNKNOWN/FAULT state after communication loss, correct handling of interrupted runs.
6. Full run sample CSV is readable while run is active and final downloads include no silently lost or invented samples; meaningful timestamps and units.
7. Web application runs headless with start-on-boot and documented backup/restore. Desktop artifacts are removed only after sign-off.
8. Both `scripts/build_windows_launcher.ps1` and `scripts/build_windows_offline.ps1` exist and pass Windows CI/release tests. Their generated launcher EXE and self-contained offline ZIP are attached to a versioned release.
9. Offline ZIP is transferred to a clean, internet-disconnected Windows machine; it runs without Python or developer tools, renders all pages/assets, runs an offline simulated profile, preserves results/CSV and does not access public internet endpoints.

## 10. Decisions to confirm before enabling physical control

- Supported initial VT4011 models and certified temperature/gradient ranges, and a generic vendor-neutral backend specification that allows future models/drivers without core GUI code edits. New vendors require adapters, site capability certification and HIL before live activation.
- Approved **current** Visteon logo and design tokens; usage rights in a public MIT repository.
- Whether required profile semantics are software-driven only (recommended v1), or native chamber PROGRAM uploads are also needed later.
- In a failure or user STOP, what should the chamber do: power OFF (proposed default), maintain current setpoint, or return to safe ambient? This must follow site/hardware safety policy.
- Preferred run storage period/quota, operators/authentication method and network boundary (single local PC vs LAN-wide lab server).
- Supported offline Windows OS/CPU baseline, availability of built-in Edge or requirement to bundle a browser, and whether an additional installer/code signing is expected.
- Clarify whether 'pre-save CSV' means profile CSV export, measurement autosave, or both; **this plan provides both**.

Additional normative review-closure artifacts: [P00_DECISION_CONTRACTS.md](P00_DECISION_CONTRACTS.md) and [READINESS_FINDINGS.md](READINESS_FINDINGS.md). These are engineering contracts, **not site acceptance**; unsigned equipment decisions remain blocked.

## 11. Readiness

- **GO now:** P00, driver hardening D01, NiceGUI UI/fake driver foundation G01–G03, early offline build feasibility W01 and simulated controller work.
- **CONDITIONAL GO for hardware:** only after D01 is reviewed/pinned; site safety STOP matrix signed; verified device envelope/identity; command fencing and exclusive owner enforced.
- **NO-GO for gradients:** until model-specific gradient units/ranges and readback/slope are HIL-certified.
- **NO-GO for release / desktop retirement:** until all four blockers, signed real-device HIL (H01), full air-gapped Windows test (W02) and R01 release approval pass.

Each development phase, PR checklist, test matrix and traceability to the independent review is in [DEVELOPMENT_SEQUENCE.md](DEVELOPMENT_SEQUENCE.md).
