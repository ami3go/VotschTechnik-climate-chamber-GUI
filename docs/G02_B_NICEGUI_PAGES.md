# G02-B — NiceGUI pages and read-only UI contract

## Delivered (mock-only; never physical control)

- Dashboard retains G02-A service telemetry/chart and the pre-existing unpersisted CSV draft. The future persisted editor belongs solely to G03-C.
- /history is searchable and bounded to 50 server records through the HistoryReader interface; the absent G07 provider returns unavailable, not fabricated runs.
- /logs uses the EventReader contract for severity, search and bounded rows, independently of browser draft events. With no G07 provider, it clearly reports unavailable.
- /settings displays one chamber's read-only identity, GOOD/STALE/ERROR timestamp, supported/unsupported capabilities and active safety/authorization lock.
- /profiles is a G03-C integration placeholder; its editor is not implemented by G02-B. The existing G02-A draft remains on Dashboard until migration.
- Shared sidebar, title, branded colors, accessibility focus, reduced motion and narrow-screen responsiveness work on each route.
- Pure projections in chamber_web/ui_state.py fail closed on UNKNOWN/FAULT/stale/error, sanitize provider exceptions and show UTC timestamps. Per-browser refresh does not own polling.
- Server-only NavigationContext hook defaults to unauthenticated read-only; it never grants permissions or accepts browser-supplied roles.
- G02-B makes no physical commands or driver calls; Start, Stop, Hold and setpoint remain disabled even for a capable backend.

## Future provider seams

G07 must provide HistoryReader.list_runs(chamber_id, search, limit) and EventReader.list_events(chamber_id, severity, search, limit), respecting server authorization, per-chamber filtering, retention and bounded pagination. G08-min must bind a server-derived authenticated principal and enforce all mutations at controller/API boundaries. Neither capability exists as a completed gate in this PR.

## Review / verification checklist

- Static: no vendor driver, sockets, backend-selection input, chamber selector or controller mutation from NiceGUI handlers.
- Fail-closed: UNKNOWN/FAULT/STALE/ERROR must never show a verified temperature, live state or unlock an operation; sample timestamps are UTC.
- Persistence: do not turn chart cache or browser events into G07 history/logs.
- Authentication: role label is informational only, no role escalation through client fields, all controls unavailable.
- Portability: Fake, Vötsch injected mock and alternate adapter are exercised sequentially through the DashboardService projection.
- Browser: separate sessions, route reload, unavailable G07 state, settings, profiles placeholder and responsive CSS.
- No mocked result is approval for live-device HIL or site safety.

## Unresolved dependencies

G03-C persisted Profiles editor; G07 durable run/event read endpoints; G08-min session/role/audit enforcement; G05 manual controls; G06 runner; signed P00 safety limits and HIL. All remain open outside this PR.
