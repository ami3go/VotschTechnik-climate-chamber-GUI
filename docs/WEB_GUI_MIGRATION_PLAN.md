# NiceGUI web migration and profile execution plan

Status: REVISED PROPOSAL — documentation only; hardware release remains NO-GO until production blockers, signed safety policy, HIL and offline gates pass. Authoritative phased backlog: [DEVELOPMENT_SEQUENCE.md](DEVELOPMENT_SEQUENCE.md).
Repositories reviewed: [GUI](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI) main and [Python driver](https://github.com/ami3go/VotschTechnik-climate-chamber-Python) main (2026-10-12).
Owner decision: The NiceGUI web application replaces Tkinter. Desktop GUI support will be discontinued after web acceptance.

## 1. Goals, boundaries, and non-goals

1. Provide a responsive, browser-based operator interface on a chamber-connected Windows/Linux/Raspberry Pi host.
2. Preserve ALL existing functional desktop workflows: connect/disconnect and chamber identity; current/target temperature; preset and custom setpoint; start/stop; limits; chart; logs.
3. Add operator-authored multi-step temperature profiles through an editable table, CSV import/export, profiles saved between sessions, and server-side execution with progress, pause/resume, abort, history and recovery.
4. Save sampled measurements incrementally to CSV during runs, not only after completion. Permit retrieval of profiles, measurement logs and event logs as CSV.
5. Apply Visteon-approved identity/logo to a clean and accessible UI.
6. ALL GUI screens, profile editor/runner, persistence and shared services MUST depend on a generic `ChamberBackend` abstraction, never directly on a manufacturer driver. Only `VotschBackend` uses the separately maintained `VotschTechnikClimateChamber` driver for Vötsch hardware communication. Future manufacturers use their own adapters/external drivers. The GUI package never reimplements physical chamber protocol. See [CHAMBER_ABSTRACTION_CONTRACT.md](CHAMBER_ABSTRACTION_CONTRACT.md).
7. The web server remains responsible for ongoing runs when browser windows close or disconnect.

Non-goals for initial release: browser-to-chamber protocol communications; chamber firmware programming; native PROGRAM upload; unsupported humidity; cloud dependency; preserving old exe; implementing a second real vendor driver in v1. **Mandatory in v1:** vendor-neutral typed interface, capability-driven screens/profile execution, Vötsch and Fake implementations, and a second simulated manufacturer stub for contract testing.

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
                                external Vötsch                                      Python driver         + future vendor adapter
                                       |                  + its own external driver
                                     VT4011

    Durable layer: SQLite for metadata, profiles/revisions, runs, events and operator lease;
                   per-run append-only CSV files for high-rate samples and exported events.
    Runtime layer: bounded command executor; poller; cancellable profile state machine;
                   immutable run snapshot; shared status event stream.

**Normative contract:** [CHAMBER_ABSTRACTION_CONTRACT.md](CHAMBER_ABSTRACTION_CONTRACT.md) specifies the typed vendor-neutral interface, identity/telemetry/capability DTOs, normalized units/errors, explicit backend registry, per-chamber controller ownership, driver isolation, configuration, testing and extension policy. Generic services must never import vendor adapters or manufacturer drivers.

Critical invariants:
- Browser events never directly call blocking backend methods. A per-chamber controller serializes adapter I/O, owns STOP/leases and produces normalized immutable status snapshots; dashboard, runner, logs, exports and shared services must use only this generic domain/controller API.
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
      services/chamber_manager.py # chamber_id -> isolated controller
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
- Compact chamber selector (initial release may support just one physical device, but stable `chamber_id`, per-device controllers and registry support later expansion), Connect/Disconnect, vendor-neutral identity/model/serial, last-successful reading age and connection status. Render action availability from `ChamberCapabilities`.
- 3 large KPI cards: measured temperature °C, effective setpoint °C, equipment status (OFF/RUNNING/UNKNOWN). Small secondary metrics: active step, remaining/elapsed time and acquisition status.
- Left: preset temperature chips and custom numeric entry/slider, apply/confirmation; start/stop manual operation. Block manual changes while a profile owns the chamber; manual takeover requires audited abort/finish, confirmed safe release of the owner lease and an explicit new action.
- Center: live measured + requested setpoint plot with chart legend, time selection, zoom, pause chart and download. Plot is for visualization only; raw CSV preserves every acquired measurement.
- Right: active profile card (profile name/version, step N of M, target, tolerance, stabilization/dwell clock, progress) and active alarms/latest events.
- Show a prominent SIMULATION banner for any fake-driver mode. No silently simulated measured values when disconnected.

### Profiles: operator table editor
- Browse/new/clone/rename/delete with confirm, revision, author and update time; import CSV; export CSV; save draft; validate; show estimate; run from validated immutable revision.
- Editable `ui.aggrid` or NiceGUI table with explicit save/validation events. Row add/remove/duplicate/reorder; enable/disable per step; bulk edit; keyboard navigation, copy/paste and undo where feasible.
- Columns: `step` (positive sequence), `enabled` (bool), `target_temperature_c` (float), `ramp_up_c_per_min` (nullable), `ramp_down_c_per_min` (nullable), `tolerance_c` (positive float), `stabilize_s` (>=0), `dwell_s` (>=0), `reach_timeout_s` (>0), `notes` (text). Profile-level: `name`, `description`, `repeat_count` (>=1), `completion_action` ('STOP' by default; optional explicit HOLD_SETPOINT).
- For ramp fields, null means hardware/default behavior and NO gradient write, not zero. Disable hardware gradient editing/execution until model-specific units/ranges/readback are HIL-certified; any unverified non-null ramp fails run validation.
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
- Settings: allowlisted adapter/backend choice and validated adapter-specific configuration (IP when relevant), certified capabilities and temperature limits, sample interval, defaults, data paths/quotas, roles and signed stop policy. Never expose generic protocol commands. Disallow backend changes during a live/uncertain run.
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
3. Stabilization requires a monotonic period of consecutive *observed* GOOD, fresh in-band readings (inclusive tolerance), with at least two distinct observations spanning positive stabilize_s. Any gap, stale/error sample or excursion resets stabilization. Samples do not prove physical continuity between observations.
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
- Import accepts UTF-8 BOM and normal quoted CSV newlines, validates delimiter without silently changing decimal meaning, duplicate headers, finite types, row/size limits and schema version; ZIP imports validate entry names, expansion, checksums and metadata. Unknown columns error by default; null gradients are empty. Failed import never changes saved profile or chamber.
- Canonical machine CSV uses comma delimiter, decimal dot, reversible numeric/text values, deterministic quoting/order and no precision loss; formula-like text is preserved but is NOT spreadsheet-safe. Provide a separate explicitly labeled spreadsheet-safe export with a documented potentially non-lossless neutralization policy.

### Run samples CSV v1 (one per run)
Header:
`sample_index,timestamp_utc,elapsed_s,run_id,chamber_id,step_index,phase,measured_temperature_c,target_temperature_c,chamber_running,sample_quality`.
- UTC RFC3339 timestamps with milliseconds; `elapsed_s` from monotonic clock; empty measured cell when acquisition fails; `sample_quality` indicates GOOD/STALE/ERROR. Do not record synthetic temperatures as valid readings.
- A companion events CSV uses `timestamp_utc,elapsed_s,run_id,step_index,severity,event_code,message,operator`.
- Before any START/setpoint, commit an immutable run/settings/profile snapshot and recording-ready state, create run folder/CSV headers/atomic manifest, then stream samples with monotonically increasing sample_index (proposed 2 s polling). Flush within the defined exposure window (target <=5 s), fsync critical transitions, checksum/finalize after close. Detect incomplete fragments/SQLite mismatch on restart; recorder failures trigger signed FAULT/stop policy and never fabricated samples.
- SQLite stores the run index and events for browsing; avoid storing millions of raw samples in SQLite unless necessary. Retain raw data, and downsample only in chart query response (e.g. <=2,000 rendered points preserving extrema).
- Keep files on server-owned directories with safe generated run IDs; sanitize filenames, guard against CSV injection, limit import size/rows, enforce disk space quota/retention and block user-controlled path traversal.
- Provide download links for profile CSV, run sample CSV, event CSV and an optional ZIP with manifest/checksums. Show data integrity warnings for recovered/incomplete runs.

## 7. Concurrency, security and operability

- Device access: one per-chamber serialized bounded queue, generation-fenced writes, poller and OS process lock. STOP intent is latched before queue scheduling, cancels/fences stale writes and is never equated with physical confirmation. Handle uncertain TCP acknowledgements without blindly repeating non-idempotent commands.
- Roles: VIEWER (monitor/download), OPERATOR (manual, profile CRUD/run/STOP), ADMIN (config/users). Audit mutations/denials. Transactional SQLite exclusive lease with generation and expiry plus OS process lock; check ownership token immediately before dispatch. STOP needs authorization, not the owner's lease; expiration does not clear physical faults.
- Browser authentication requires offline local first-run admin enrollment, credential recovery, secure cookies, session expiry and HTTP/WebSocket CSRF/origin checks; loopback by default, explicit HTTPS/protected proxy when LAN-enabled, no unauthenticated mutations or internet exposure.
- Validate and restrict device target addresses to configured allowlist/LAN ranges to avoid use of connection form as arbitrary-network access.
- Support independently supervised Windows service/systemd lifecycle and an explicitly limited portable per-user mode; closing a browser/launcher cannot stop an active service run, while user logoff MAY stop portable mode and must be documented/guarded. Distinguish process liveness, application readiness, driver connectivity and verified physical equipment state. Never auto-start chamber on server boot.
- Pin NiceGUI, contract version, registered backend versions and tested external driver dependencies. Vötsch transport stays in its separately maintained driver; supporting another vendor adds a dedicated adapter and its separately maintained driver, not GUI command logic.
- Enforce exactly one authoritative server process/chamber OS lock plus transactional lease and command generation; a second server cannot control the same physical IP. Multi-worker device processes remain out of scope.
- Run count, sample/data retention, audit retention and recovery policy are administrator-configured; default to conservative safe choices.
- On over-temperature per certified safety envelope, communication failure, invalid identity, stale data, out-of-band safety alarm, disk full or unverified STOP: prevent profile advancement, apply signed fault matrix and surface operator recovery guidance. Freeze target IP, safety limits, poll policy and recording path for each active run.

## 7A. Mandatory review-closure contracts

All of the following are required before a physical-control release and are expanded into specific PR tasks/tests in [DEVELOPMENT_SEQUENCE.md](DEVELOPMENT_SEQUENCE.md). Unknown decisions remain PENDING SITE SIGNOFF, not automatically approved defaults.

1. **Signed physical failure matrix:** specify requested device action, verification evidence, UNKNOWN/FAULT, operator alarm/intervention and HIL test for completion, STOP, communication error, readback mismatch, over-limit temperature, logging outage, service crash/logoff, power cycle and hardware alarm. Web STOP is not an emergency stop; do not assume ambient ramp is inherently safe.
2. **Verified device capability registry:** `ChamberBackend` reports actual manufacturer/model/serial and site-certified safe temperature limits, supported start/stop/readback, gradients, units/ranges and polling behavior. UI/profile engine automatically reject unsupported actions. Require conformance testing and safe capability snapshots; see [abstraction contract](CHAMBER_ABSTRACTION_CONTRACT.md).
3. **Driver and adapter boundary:** `VotschBackend` alone imports `VotschTechnikClimateChamber`, and real Vötsch I/O passes exclusively through that hardened external driver. Future vendor adapters must use independent dedicated drivers. Generic GUI/controller/runner must not import vendor drivers, implement protocols or silently fall back to simulation.
4. **Control ownership and fencing:** independent `ChamberController(chamber_id)`, OS process/device lock, SQLite transactional lease/generation and STOP fencing. Driver/backend swaps while running or in UNKNOWN state are forbidden. No old command replay or auto-resume. Chamber A STOP/controls must never reach chamber B.
5. **Observational profile semantics:** monotonic time, fresh GOOD samples only, inclusive tolerance, gap resets stabilization, dwell credit only for eligible observed intervals, explicit PAUSE/deadline behavior and finite per-stage/per-run watchdogs. Deterministic virtual-clock tests required.
6. **Lossless persistence:** canonical versioned ZIP with profile.csv + profile.json; plain CSV is step-only. Reversible machine CSV and separately spreadsheet-safe export; sample_index, atomic run manifest, crash reconciliation, durable event recording, quota/ENOSPC response and incomplete-file warnings.
7. **Offline operational/security lifecycle:** local admin first-run enrollment, role permissions, LAN TLS/proxy, browser-independent supervised server, documented portable logoff limits, separate liveness/readiness/device status, migration backups, rollback compatibility, verified offline assets and Visteon licensing.
8. **Quality evidence:** architecture import-boundary CI, conformance suite for Vötsch/Fake/second-manufacturer stub, dashboard/runner behavior using only capabilities without edits to generic modules, synthetic plot benchmarks, Windows air-gap tests and independent site HIL. Addition of a vendor must not require modifying base GUI/profile/CSV/controller for existing functions.
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
| G01–G03 | Vendor-neutral typed `ChamberBackend` interface + registry, Vötsch/Fake/second-vendor stub conformance, NiceGUI shell, capability-driven screens, profile data/schema/CSV/SQLite |
| W01 (early, parallel) | Both Windows launcher and offline-build script feasibility with frozen fake-driver server |
| G04–G06 | Generic per-chamber controller, command fencing, ownership, manual controls and profile runner via `ChamberBackend` (no direct Vötsch dependency) |
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
1. Manual workflows demonstrated with VT4011 through `ChamberBackend`, and a second-vendor test adapter runs the same generic dashboard/profile workflows without modifying generic source. CI enforces no direct Vötsch imports outside its adapter; unsupported features disabled.
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

## 11. Readiness

- **GO now:** P00, driver hardening D01, NiceGUI UI/fake driver foundation G01–G03, early offline build feasibility W01 and simulated controller work.
- **CONDITIONAL GO for hardware:** only after D01 is reviewed/pinned; site safety STOP matrix signed; verified device envelope/identity; command fencing and exclusive owner enforced.
- **NO-GO for gradients:** until model-specific gradient units/ranges and readback/slope are HIL-certified.
- **NO-GO for release / desktop retirement:** until all four blockers, signed real-device HIL (H01), full air-gapped Windows test (W02) and R01 release approval pass.

Each development phase, PR checklist, test matrix and traceability to the independent review is in [DEVELOPMENT_SEQUENCE.md](DEVELOPMENT_SEQUENCE.md).
