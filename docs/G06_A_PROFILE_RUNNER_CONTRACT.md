> **HISTORICAL CONTRACT — H02 EXTENSION ARCHIVED (2026-10-26).** The H02 permit/watchdog extension is archived under `../archive/h02/`. Physical profiles now require isolated lab mode and the G06/G07/G04/G08 controls.

# G06-A — Server-side profile runner contract (simulation only)

Status: **G06-A simulation-only software merged in PR #24** (`28377a4eb0c7f651063c87ad5789810b036380fe`; final-head Windows 3.10/3.12 run [38289290272](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38289290272)); **not hardware-certified**. This file specifies software semantics, not an approval for physical chamber operation. Normative sources: [P00_DECISION_CONTRACTS.md](P00_DECISION_CONTRACTS.md), [G04_A_CONTROLLER_CONTRACT.md](G04_A_CONTROLLER_CONTRACT.md), [CHAMBER_ABSTRACTION_CONTRACT.md](CHAMBER_ABSTRACTION_CONTRACT.md).

## Ownership, boundaries, and entrypoints

- `chamber_web.execution.profile_runner.ProfileRunner(manager, store, authorize=..., sink=..., clock=...)` is the only profile scheduler. It imports *only* domain DTOs, G03 `ProfileStore`, G04 `ChamberManager`, and standard Python libraries. It cannot call the driver, vendor adapters, or NiceGUI.
- `start(chamber_id, profile_id, revision=N, parameters=RunParameters(...))` **prepares only**, returning an immutable `ExecutionSnapshot`; `advance()` dispatches/observes one deterministic stage; `run_until_terminal()` and `advance_async()` offload blocking G04 calls via `asyncio.to_thread`. `pause`, `resume`, and `cancel` are server-side mutations; `start_async`, `pause_async`, `resume_async`, and `cancel_async` are event-loop-safe wrappers. Synchronous methods must not run on the event-loop thread.
- The runner is instantiated once, held in the server composition root, and tied to the manager's one configured `chamber_id`. Concurrent starts on that runner are denied; G04's operator claim and one-controller process/OS lease additionally block independent concurrent ownership. No fleet scheduler, driver I/O, UI, profile editor, or G07 datastore is introduced.
- Mandatory `authorize(action: str, chamber_id: str) -> authenticated_principal_id`: *server-supplied*, not request-supplied. No configured authorizer means **deny**, even for the local simulator. G08-min must supply a session-bound ADMIN/OPERATOR policy, audit permitted/denied mutations, enforce Origin/CSRF/WS protections, and decide that STOP is independently authorized regardless of operator lease. Pause/resume also require the same authenticated principal that claimed the run; an independently authorized STOP/cancel remains permitted for a different operator. The test authorizer is **only** a test fixture, never wired to an app/page. A G04 operator token is not an authentication credential.
- Controller requires a simulated `identity.is_simulation` and safe, reconciled STOPPED readback; no production/hardware path or test-mode override exists. All setpoint/START/STOP calls use G04. No automatic `reconcile_stop`, no ambient restore/retry or physical controller fallback.

Per-step v2 output directives remain inside that simulation-only boundary. The runner
durably records `OUTPUT_INTENT` and `RUN_STATE_INTENT` before dispatch, verifies each
advertised numbered-output readback, and can dwell with simulated chamber run ON or OFF.
Older v1 profiles retain their historical implicit run-ON behavior. Auxiliary outputs
default to `UNCHANGED`; terminal STOP does not invent a dryer/compressed-air shutdown
policy, so profiles must request explicit OFF values where the test procedure requires
them. Physical output execution remains disabled pending a signed shutdown policy and HIL.

## Immutable execution snapshot (schema version 1)

`ExecutionSnapshot` freezes run UUID, `chamber_id`, `ChamberIdentity` (backend ID, manufacturer, model, serial, simulation flag), `ChamberCapabilities`, immutable `ProfileRevision` profile ID/revision/ZIP SHA-256/source/saved UTC, enabled step DTOs, repeat count, STOP completion action, operator principal ID, preparation UTC, G04 generation and `RunParameters`. The revision is fetched and checksum-verified using the G03 store; later edits cannot alter this run. The initial status, identity, capabilities and connected/stop-latched G04 health are verified before operator claim. All enabled targets must be finite and in inclusive backend limits.

G04 currently has no verified gradient **readback/set/restore-baseline** API. Therefore any non-null `ramp_up_c_per_min` or `ramp_down_c_per_min` is rejected at preparation (even if an adapter claims generic ramp support); a null ramp causes **zero** hardware gradient writes. This deliberately implements a safe **unsupported** policy rather than silently disregarding requested ramps. Implementing P00's full baseline-capture, directed ramp changes and restoration requires a later controller contract change, safety and HIL review. Profiles with only null ramp fields continue to run on simulator/alternate-adapter fixtures.

## Formal state machine

| State | Meaning | Legal outward transitions |
|---|---|---|
| PREPARING | Snapshot fixed and operator lease granted; **no commands yet** | REACHING after verified setpoint, outputs and requested simulated run state; STOP_REQUESTED on cancellation/fault |
| REACHING | Simulator verified in the step's requested RUNNING/STOPPED state; await first fresh, eligible in-band observation | STABILIZING, DWELLING, STOP_REQUESTED |
| STABILIZING | Eligible first sample recorded; require second distinct sample and continuous in-band window | DWELLING, REACHING (excursion), STOP_REQUESTED |
| DWELLING | Credit only consecutive eligible observation brackets | TRANSITIONING, REACHING (excursion or gap), STOP_REQUESTED |
| TRANSITIONING | Previous step qualified; pending next setpoint | REACHING, STOP_REQUESTED |
| PAUSED | **Logical observation pause only**; simulator retains the step's commanded RUNNING/STOPPED state and setpoint | REACHING (resume), STOP_REQUESTED |
| STOP_REQUESTED | G04 STOP intent fenced; async serialized STOP + authoritative readback pending | COMPLETED, CANCELLED, FAULT (only when STOP verified), UNKNOWN |
| COMPLETED/CANCELLED/FAULT | Terminal only after fresh G04 VERIFIED_STOPPED; controller STOP latch **remains set** | none; later start requires separate explicit reconciliation |
| UNKNOWN | STOP, controller generation/identity/quality, recording or operator lease cannot be verified | none; local/operator reconciliation mandatory |

`FAULT` is used for deterministic elapsed-time watchdog failure where STOP was verified. Uncertain controller I/O, stale/invalid telemetry, disconnected backend, readback mismatch and unverified STOP lead to `UNKNOWN`. An external G04 STOP or generation advance invalidates the runner's controller binding. All active failures request STOP once and fail closed; a verified STOP is **not** an emergency-stop certification.

## Timing, sample qualification, deadlines

- Defaults: 2 s nominal observation interval, up to 5 s observation continuity gap, 5 s UTC sample freshness, 15 s bounded extra step margin. Configured values are finite, strictly positive and cannot relax P00 5 s bounds. The G04 controller also verifies each sample's identity, quality, timestamp, finite measurement and authoritative readback.
- Monotonic `Clock` drives every stage and deadline. `VirtualClock` is injected in tests; it cannot move backwards. No wall-clock time difference counts toward dwell/stabilization (UTC dates only provide metadata and source sample freshness).
- Reach begins **after verified setpoint dispatch** (and initial verified START). The first in-band sample may pass at equality to the reach deadline, not after it. Stabilization zero means that first sample is sufficient; otherwise at least two distinct, good observations spanning `stabilize_s`, with no gap over 5 s or intervening excursions, are required. Inclusive target ± tolerance is applied.
- Dwell zero transitions immediately on stabilization qualification. Positive dwell credits only positive elapsed intervals bounded by eligible polls with interval ≤5 s. Duplicate timestamps, excursions, pauses and continuity gaps cannot increase dwell. Excursions reset dwell and re-enter REACHING; pauses reset stabilization and dwell.
- **Absolute** per-step and whole-run watchdogs do not pause. Step budget = reach timeout + stabilization + dwell + bounded margin; run budget = sum of enabled step budgets × repeat count + 30 s, or stricter explicit `max_run_s`; capped at 14 days. A tick after deadline faults before progressing; at exact equality a qualifying sample may complete. Caller G04 I/O timeout remains separately finite and does not preempt a stuck adapter.
- Logical PAUSE never stops/chills/holds physical control; it only stops profile credit, continuing watchdog and telemetry surveillance. RESUME restarts stabilization/reach qualification within original absolute stage deadlines. No automatic reboot resume.

## STOP, cancellation, failure and crash boundaries

`cancel(chamber_id)` authorizes STOP independently of the current G04 operator owner. It sets cancellation intent without waiting for a possibly blocked `advance()` lock, emits a STOP_INTENT, and schedules G04 STOP on an independent server thread. G04 synchronously persists the fence when its STOP call starts, then schedules prioritized device I/O. Cancellation is *requested*, not instantly complete; `CANCELLED` requires verified STOPPED. Repeated cancellation does not submit more STOP operations.

If an adapter's synchronous I/O was already admitted, G04 cannot preempt it. STOP may wait, fail, or time out; the runner must report UNKNOWN and **not** assert stopped, replay writes, release the physical lock, or auto-restart. Software timeout does not imply a physical condition. Fresh stopped readback and explicit authorized G04 reconciliation are required to clear the controller STOP latch. Run recovery across process restart is **not** implemented; G07 must classify an unfinalized started run as INTERRUPTED/UNKNOWN, never resume it automatically.

## G07-A integration contract (no persistence implementation here)

`EventSink.prepare(ExecutionSnapshot)` must synchronously commit immutable PREPARED metadata before any command. `EventSink.emit(RunEvent)` is the version-one append-only event handoff. Each event includes immutable run ID/chamber ID, monotonically increasing event sequence per run, `kind`, execution `state`, `monotonic_elapsed_s`, timezone-aware UTC `observed_at_utc`, step index, detail, optional measured °C and reading quality. Each `SAMPLE` additionally carries a per-run monotonically increasing `sample_index` and source hardware/simulator `source_sampled_at_utc` timestamp; duplicate source timestamps never earn dwell/stabilization credit. Expected ordered event types: `PREPARED`, `START_INTENT`, `SETPOINT_INTENT`, optional `OUTPUT_INTENT` / `RUN_STATE_INTENT`, `STATE`, `SAMPLE`, `STEP_COMPLETED`, `STOP_INTENT`, `TERMINAL`. The START_INTENT precedes the **first setpoint** as well as simulated run/output dispatch; the sink must durably commit each intent before its command dispatch and must not silently swallow errors. In particular, G07 must implement durable PREPARED snapshot, START_INTENT command-intent transaction, timestamped samples and crash reconciliation per P00 (including SQLite/filesystem fsync/rename boundaries). This module retains only the most recent 1024 events in an ephemeral diagnostic ring buffer (separate monotonic sequence counter) and does **not** implement a SQLite run recorder. Until that persistence interface is installed, no durable run/history guarantee or physical rollout is claimed.

G07 must store `ExecutionSnapshot` inside `prepare()` with PREPARED, bind events to the run UUID and `chamber_id`, keep sequence idempotent, and mark recovered partially executed runs INTERRUPTED/UNKNOWN pending site-authorized verification. EventSink errors are never silently treated as success; the runner requests STOP and reports UNKNOWN if durable event recording fails.


## Dashboard Run Profile readiness and handoff (2026-10-19)

An authenticated ADMIN/OPERATOR may select a saved immutable revision on
**Dashboard → Chamber Control → Saved profile** and click **Run Profile**.
The runner is server-owned, shared with the Profiles page and G07 recorder.

- **Manual-control handoff:** when the current operator has a G05 manual
  lease and the chamber is freshly verified STOPPED, the profile request
  safely releases that operator's manual lease using the existing G08 audit
  and permission guard, allowing G06 to claim its own lease. Another
  operator's lease, RUNNING manual operation or a G06 owner is never stolen.
  No browser receives a lease token or bypasses the G04 controller.
- **Repeat runs:** after a G06 STOP/CANCEL that is genuinely
  `VERIFIED_STOPPED`, a new explicit **Run Profile** rechecks STOPPED
  through the existing G04 authoritative readback and durable generation
  reconciliation, before any new profile execution starts. Merely loading a
  page, selecting a profile, or refreshing the Dashboard never clears a
  STOP fence or starts a chamber.
- **Faults and restart:** UNKNOWN/FAULT, stale or mismatched status,
  missing permissions, an active runner, disconnected chamber, unavailable
  G07 journal and uncertain restart remain fail-closed. G04 still fences
  concurrent STOPs and G06 separately revalidates the selected saved
  revision, capabilities, start/stop readback and temperature bounds.
- **Physical HIL:** the H02 server-side signed site permit, matching
  revision/serial/operator and independent live watchdog are still required.
  This fix **does not** make an unapproved physical profile runnable; no
  physical hardware has been tested or approved by these changes.

Regression evidence:
`tests/test_profile_execution_service.py` exercises verified STOP
recovery, owner-only handoff, active RUNNING refusal, invalid revision
before handoff, and physical missing-permit denial.
`tests/test_dashboard_profile_ui.py` exercises repeated profile runs.
Dedicated Windows/Linux CI uses a 20-minute watchdog and also runs H02
permit safety tests.

## Browser execution (simulation only)

`chamber_web.services.profile_execution.ProfileExecutionService` hosts one `ProfileRunner` per server and exposes it on `/profiles` ("Profile Run" panel). Behaviour:

- **Simulation only.** The composition root passes `simulation=True` only when no `CHAMBER_HIL_*` authorization is present; the service refuses `start` otherwise, and `ProfileRunner` independently rejects non-simulated chamber identities. In Physical HIL mode the panel is shown but disabled.
- **Authorization.** Every start/pause/resume/stop re-authenticates the session and CSRF token and requires `profile.run` (ADMIN, OPERATOR); viewers see state only. Any `profile.run` user may stop a run; pause/resume are reserved for the operator who started it. Passive refresh (`view`) never renews a session and never exposes lease tokens.
- **Exact revision.** "Run Loaded Revision" runs the saved revision currently loaded in the editor; unsaved drafts cannot run.
- **Server-owned lifecycle.** The run task belongs to the server: closing or reloading a browser does not stop it. On server shutdown a trusted STOP is issued before the dashboard disconnects the backend.
- **Simulated progress.** The production FakeBackend slews measured temperature at 0.25 °C/s while running (`simulated_slew_c_per_s`); tests keep the deterministic default of 0.
- **Not yet wired:** a durable G07 `RunRecorder` sink (the panel shows the in-memory diagnostic event ring only), run history pages, and startup reconciliation of interrupted runs.

## Validation matrix and release blockers

`tests/test_profile_runner.py` uses virtual time and isolated Fake/second-adapter instances for zero dwell, target boundary, multi-sample stabilization, gaps, excursions, logical pause/reset, absolute deadline, negative temperatures, readback mismatch, stale samples, invalid/fault telemetry, concurrent start, cancel during blocked I/O, STOP fencing, unauthorized start and explicit reconciliation. Windows CI for Python 3.10 and 3.12 also reruns G03/G04 regression suites. These are software-only tests and cannot establish real STOP latency.

**Release blockers:** G08-min real authenticated policy/audit/CSRF integration; G07 durable run journal and interruption reconciliation; approved physical safety envelope and signed STOP/fault policy; G04 gradient contract/HIL for gradients; driver/backend version capture; actual chamber-in-the-loop tests; final offline W02 certification. Real physical operations remain disabled by G04.


## H02 physical-profile admission extension — archived 2026-10-26

The H02 permit/watchdog extension is archived under `archive/h02/` and is not imported. Current physical-profile execution requires isolated lab mode, fresh G04 status and verified STOP, G08 role/CSRF/lease, a reconciled G07 journal and the G06 runtime checks. Null gradients, physical auxiliary outputs and chamber-state controls remain restricted until separate site approval.
