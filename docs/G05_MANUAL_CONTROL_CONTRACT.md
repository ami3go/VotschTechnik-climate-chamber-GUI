# G05 — manual chamber control (simulated-only)

Status: **G08-min PR #25 merged; G05 simulated software candidate, final-head CI and review gating merge**.
This document is a server-side interface contract, **not a VT4011
qualification or physical-use authorization**. References:
[architecture](CHAMBER_ABSTRACTION_CONTRACT.md),
[G04 fencing](G04_A_CONTROLLER_CONTRACT.md),
[G08-min](G08_MIN_SECURITY.md),
[P00](P00_DECISION_CONTRACTS.md), and
[development sequence](DEVELOPMENT_SEQUENCE.md).

## Ownership boundaries

- One configured `chamber_id`, one server-owned `ChamberManager`, and one G04
  `ChamberController` per process. Device I/O occurs exclusively on the G04
  worker. `ManualControlService` is independent of NiceGUI and all manufacturers.
- The composition root `create_demo_control_services()` unconditionally
  instantiates a `fake` chamber with no device address. G04 independently
  requires the adapter's pre-connect `simulation_only` marker and an
  `is_simulation` identity. No HTTP form, browser configuration, environment
  variable, manufacturer driver import or development override can enable a
  physical connection in G05. Physical writes remain **DISABLED**.
- Manual events always use `AuthorizedChamber` from G08-min. Session and CSRF
  are revalidated on each mutation; G08-min persists INTENT/DENIED/SUCCESS/FAILED
  audit records. VIEWER is read-only, anonymous/expired/forged requests are
  rejected, and ADMIN/OPERATOR are authorized for manual control and STOP.
  G04 operator tokens stay in server memory: they are never sent to NiceGUI.
- `claim` requires fresh GOOD simulated status; only one actor at a time may
  hold the operator lease. `release`, `set_temperature`, and `start` must
  revalidate the authenticated actor against the same lease. A second browser
  session belonging to the *same user* shares ownership. Session revocation
  removes write rights immediately but does **not** silently release ownership.
- Explicit `handover` is an audited **ADMIN-only takeover to the signed-in
  administrator**, using G04 release/claim and the G04 queued-command ownership
  generation fence. An operator cannot take over someone else's lease. If the
  second half of handover fails, control is unclaimed; no automatic recovery.
  Ownership handover does not imply a safe chamber state.
- STOP bypasses the operator lease. It is a G08-authorized command for
  ADMIN/OPERATOR even if telemetry is stale, another user owns the lease,
  or a target update is queued. G04 latches intent, advances the durable
  generation and prioritizes STOP. A blocked synchronous backend **cannot**
  be preempted; an expired STOP is UNKNOWN, never assumed safe. STOP is **not**
  a local emergency-stop system.
- After STOP, a latched controller denies START/target writes. Only explicit
  ADMIN `reconcile` can clear the latch, requiring fresh authoritative STOPPED
  status. On process restart, G04's persistent lease may require reconciliation.
  G05 does not reconnect, auto-clear STOP, or execute profiles.

## Readbacks, operations and UI

`ManualControlService.view(session, chamber_id)` supplies passive cached
DashboardView, health/generation/latch state, owner label and a shared last
`CommandOutcome`; passive reads do not extend G08 session lifetime.
`command(session, csrf, chamber_id, action, target_c=...)` is an explicit
allowlist. Supported actions: `claim`, `release`, `handover`, `set_temperature`,
`start`, `stop`, and `reconcile`. There is no generic command router,
unvalidated ramp/gradient API, mode selector, preset execution, profile runner,
or browser-direct manager/adapter access.

Target values must be finite numeric, non-boolean, within the
adapter-advertised range. A fresh, identity-verified G04 status, valid
capabilities, GOOD reading quality, timezone-aware timestamp and clear STOP
latch are prerequisites before START/setpoint. START further requires
`supports_start_stop`, `supports_running_readback`, a present/readable target,
and `supports_setpoint_readback`. G04 performs post-write verification and
fences older commands. G05 performs a second fresh G04 read before reporting
CONFIRMED. A readback mismatch, stale/disconnected state, timing failure,
FAULT or uncertain write must not be presented as success.

Server-shared outcome states are `IDLE`, `PENDING`, `STOP_REQUESTED`,
`CONFIRMED`, `REJECTED`, `UNKNOWN`, and `FAULT`. The most recently begun
operation wins the display ordering, preventing completion of an older
target write from overwriting STOP_REQUESTED/STOP outcomes. Outcomes are
*ephemeral operational status*, not a G07 durable event journal.
The Dashboard retains the G02-B visual shell and exposes capability-driven
START/target/claim/release/admin handover/reconcile controls. Unsupported Hold,
gradients/ramps and operating modes remain visibly unavailable. Values
0, 23 and 40 °C are **suggested in-range UI field-fill values only**,
not manufacturer presets or automatically executed commands. The operator
must explicitly apply any target. No signed site-approved limits exist.

## Review and test matrix

- `tests/test_manual_control.py`: separate sequential FakeBackend,
  AlternateStubBackend and injected Vötsch mock (never physical) with target,
  START, STOP, reconcile and release; concurrent operator claims; ADMIN
  handover; viewer, anonymous, missing/forged CSRF, revoked session, wrong ID;
  invalid finite/range/type cases and unsupported ramps; mismatch/UNKNOWN,
  stale telemetry, STOP priority, browser-equivalent multi-session identity,
  and durable restart reconciliation.
- `tests/test_manual_ui.py`: NiceGUI two-session smoke with actual local
  G08-min authorization and a simulated STOP; full cross-process/device
  browser testing and Windows frozen-app multi-client tests remain gates.
- Windows `web-gui-demo.yml` must pass on Python 3.10 and 3.12, including
  security/core tests, NiceGUI smoke, ruff and compileall; Windows packaging
  workflow must also pass for the final PR head.
- Review must inspect authorization races, intent logging failures, stale
  sessions, per-account takeover, in-flight command generation fencing,
  STOP starvation and uncertainty, wrong-device and alternative-backend
  capabilities. Fix every BLOCKER/HIGH issue before merging.

## Hard NO-GO gates for physical VT4011

1. G08-min PR #25 merged and G05 PR #28 retargeted to main without duplicated
   auth code; the final G05 software CI/review is still a merge gate. Subsequent full G08 protection for
   any LAN/general-use control, including TLS, OS ACL, audit recovery/retention,
   backup, revoke/connection handling and security assessment.
2. Exact equipment model/serial/firmware verified and signed at the site;
   approved temperature limits, tolerances, operation modes, gradients and
   maximum rate parameters. Adapter-advertised simulation bounds are **not**
   a site limit policy. No implied VT4011 preset equivalence.
3. Pinned externally maintained Vötsch Python driver independently validated
   for the exact hardware model/firmware, protocol/framing, timeouts, identity,
   setpoint/state readbacks, fault flags and safe disconnect.
4. Site-approved hardware STOP procedure, local physical emergency-stop
   arrangements and independent operator/operator-conflict safety policy.
   A web STOP cannot be relied upon as emergency or safety shutdown.
5. Approved guarded single-device HIL matrix: safe target, START, STOP,
   readback mismatch, stuck adapter, stale telemetry, reconnect, power loss,
   restart, conflicting operators, fault and manufacturer alarm handling.
6. G06 profile-execution interlock and G07 durable event recording integrated
   before operational release; no unchecked manual/profile concurrent writes.
   W02 offline Windows deployment, audit backup, documented rollback and
   R01 signoff remain outstanding.

**Release decision: NO-GO.** All manual workflows in this PR are simulation-only.


### Integrated H01/manual regression update (2026-10-14)

The actual H01 headless Chromium workflow now runs on G05 source changes, with claim/setpoint/START/STOP and VIEWER-denial checks in the real server browser. G05 also tests that manual ownership and G06 runner ownership are mutually exclusive using a shared G04 controller while separately authorized STOP remains available. A UI fallback now reauthenticates role before enabling STOP when passive status cannot be read; VIEWER/revoked controls stay disabled. These checks require fresh GitHub Actions verification and do not certify physical hardware, emergency STOP or G07 combined wiring. G07-A integration and independent human approval remain explicit merge gates.


## Verified normal STOP — retain operator control (2026-10-19)

A **Dashboard → Chamber Control → Stop** action must not permanently disable
Start after a routine STOP that the chamber confirms. G04 **always** fences
STOP synchronously, prioritizes it ahead of writes, and records a durable
STOP latch. This core STOP invariant is unchanged.

The G05/G08 server-owned manual workflow adds a strictly conditional,
audited **automatic rearm** of that latch:

1. An authenticated ADMIN/OPERATOR initiates STOP (STOP itself does **not**
   require a lease). Capture the G04 generation and, nonblocking, whether
   this same user already holds the G04 manual operator lease.
2. Dispatch STOP through the existing independent G08 STOP guard; require
   authoritative, matching-identity, GOOD, fresh STOPPED readback and
   controller `VERIFIED_STOPPED`.
3. If the originating user already held the lease, the owner/lease revision
   is unchanged, and the new STOP generation is **exactly** the expected
   increment, perform a separate server-side G08-audited automatic rearm.
   G04 `reconcile_stop` independently reads the chamber again and checks
   `STOPPED`, freshness, the same generation and durability before clearing
   the latch. Retain the operator lease throughout.
4. With successful rearm, Start and Set Target become available again when
   dashboard telemetry is GOOD; the next Start still performs all fresh
   command admission and device readback checks. The GUI never starts the
   chamber automatically.

An authorized non-owner STOP, ambiguous STOP outcome, STOP/readback timeout,
UNKNOWN/FAULT, overlapping STOP, lease handover/reclaim, changed generation,
expired/revoked session or audit failure **must never be treated as a normal
rearmed STOP**. The latch remains, or automatic rearm is unconfirmed; Admin
STOP reconciliation remains available. STOP priority and STOP access by any
authorized operator remain unchanged. G06 cancellation and H02 watchdog STOP
paths do **not** use this G05 auto-rearm mechanism.

Tests: `tests/test_manual_control.py` covers repeated Start–Stop–Start,
lease persistence, outsider STOP, concurrent STOP generation, revoked
session and failed STOP. `tests/test_manual_ui.py` exercises two consecutive
cycles through authenticated NiceGUI controls. All run simulation-only.

### Live Chromium UI button state correction — 2026-10-14

A real Playwright/Chromium test exposed a G05 presentation defect that an in-process NiceGUI click test did not detect: initializing buttons using raw Quasar `props(... disable)` does not update NiceGUI's tracked `enabled` state. Subsequent `button.enable()` could leave the raw `disable` prop in place. G05 now constructs every conditionally enabled manual command button using `.disable()` and relies on `.enable()` / `.disable()` only after an authenticated service view. STOP initially renders disabled to avoid displaying an unauthorized transient control; G08 authorization remains mandatory on every STOP callback even if UI state is manipulated. The permanently unsupported Hold action remains disabled. This requires exact-commit H01 real browser validation before accepting the change. No testing-only bypass or physical I/O enablement was added.
