# G02-B — NiceGUI pages and read-only UI contract

## Delivered (mock-only; never physical control)

- Dashboard retains G02-A service telemetry/chart and a non-executable profile preview; G03-C owns all persistent editing on /profiles.
- /history is searchable and bounded to 50 server records through the HistoryReader interface. The composition root now projects the owned G07 journal; an unavailable journal returns unavailable, not fabricated runs.
- /logs uses the EventReader contract for severity, search and bounded recent rows, independently of browser draft events. The G07 journal adapter applies conservative presentation severity; G08 audit integration remains separate.
- /settings displays one chamber's read-only identity, GOOD/STALE/ERROR timestamp, supported/unsupported capabilities and active safety/authorization lock.
- G02-B initially exposed a /profiles integration placeholder; G03-C now replaces it with its own persistent editor, while sharing this navigation/layout. Dashboard retains only a non-executable profile preview.
- Shared sidebar, title, branded colors, accessibility focus, reduced motion and narrow-screen responsiveness work on each route.
- Pure projections in chamber_web/ui_state.py fail closed on UNKNOWN/FAULT/stale/error, sanitize provider exceptions and show UTC timestamps. Per-browser refresh does not own polling.
- Server-only NavigationContext hook defaults to unauthenticated read-only; it never grants permissions or accepts browser-supplied roles.
- G02-B makes no physical commands or driver calls; Start, Stop, Hold and setpoint remain disabled even for a capable backend.

## Dashboard chamber identity card (2026-10-19)

The **Dashboard → Chamber Control** card displays three prominent,
independently labeled read-only fields: **Chamber**, **IP address** and
**Serial number**. It does not require opening Settings or interpreting
the small backend status header.

- **Physical HIL:** Chamber shows the configured chamber ID and the
  driver-verified manufacturer/model when identity readback is available.
  IP is the server's selected, validated launch-time HIL address. The
  serial number is the server's expected serial pin. A separate status
  explicitly distinguishes **Live identity verified**, **Identity last
  seen — live status unverified**, and **Configured identity — not yet
  verified**. The panel never claims a connected device solely from saved
  settings, stale data, a failed read, or an untrusted discovery response.
- **Simulation:** Chamber reads `Simulator · demo-chamber` (or the actual
  active simulated chamber ID). IP and serial both say
  `Not applicable (simulation)`. Nothing implies a real chamber is
  connected.
- **Startup and refresh:** Identifiers appear before the first telemetry
  poll; read-only updates use the existing server-owned DashboardView.
  The installed backend/driver path and all HIL safety gates are unchanged.
- **Layout:** Three cells on larger screens; a vertically stacked layout
  on narrow mobile screens. Labels, values and verification state do not
  rely on color alone.

Test evidence: `tests/test_web_views.py` checks correct simulated and
physical projections, stale/error readback, serial mismatch and identity
misassociation; `tests/test_web_ui.py` checks the authenticated NiceGUI
Dashboard card. Physical hardware is not contacted by these tests.

## G07 provider integration

`RunStoreReader` implements `HistoryReader.list_runs(chamber_id, search, limit)` and `EventReader.list_events(chamber_id, severity, search, limit)` against the single composition-owned G07 journal. Reads remain per-chamber, bounded, off the NiceGUI event loop, and fail closed on journal or row-integrity errors. G08-min [PR #25](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/25) supplies the server-derived authenticated principal and every page/callback rechecks authentication. This integration does not add evidence downloads, G08 audit events, retention/backup operations, physical HIL approval or release acceptance.

## Review / verification checklist

- Static: no vendor driver, sockets, backend-selection input, chamber selector or controller mutation from NiceGUI handlers.
- Fail-closed: UNKNOWN/FAULT/STALE/ERROR must never show a verified temperature, live state or unlock an operation; sample timestamps are UTC.
- Persistence: do not turn chart cache or browser events into G07 history/logs.
- Authentication: role label is informational only, no role escalation through client fields, all controls unavailable.
- Portability: Fake, Vötsch injected mock and alternate adapter are exercised sequentially through the DashboardService projection.
- Browser: separate sessions, route reload, empty/unavailable G07 state, journal-backed rows, settings, profiles and responsive CSS.
- No mocked result is approval for live-device HIL or site safety.

## Unresolved dependencies

G03-C persistence/editing, G05 manual controls, G06 execution, G07 recording and authenticated history/log projection are integrated as simulation-tested software. Authorized evidence exports, G08 audit-event integration, retention/backup/recovery operations, signed site limits and physical HIL acceptance remain open.

## Second-pass implementation review

- HIGH, fixed: unverified backend identity must never be called SIMULATION; UNKNOWN/FAULT and unsupported running readbacks cannot leave a verified operation.
- HIGH, fixed: unsupported setpoint readback never displays a verified setpoint.
- HIGH, fixed: banner mode must derive from current telemetry; capability envelopes are clearly labeled adapter-reported and not site-certified.
- MEDIUM, fixed: fixed navigation items have accessible names, and G08 may supply session-verified allowed routes through install_navigation_resolver; client menus alone are not permission checks.
- CI verification and release/site approval are separate from this review.
