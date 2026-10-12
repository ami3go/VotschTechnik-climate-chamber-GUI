# Future multiple-chamber architecture — design now, implement much later

Status: **architecture contract only**. This document deliberately does NOT authorize implementation of concurrent multi-chamber operation in the first NiceGUI release. It extends [the chamber abstraction contract](CHAMBER_ABSTRACTION_CONTRACT.md), [the migration plan](WEB_GUI_MIGRATION_PLAN.md) and [the development sequence](DEVELOPMENT_SEQUENCE.md).

## Explicit release boundary

| Dimension | Required in first release (v1) | Deferred to a separately approved far-future phase (MC01–MC05) |
|---|---|---|
| Physical chambers per application deployment | **Exactly zero or one** active/configured physical chamber; reject any attempt to configure or start a second | Two or more independently configured physical chambers in one service |
| Backends | Generic `ChamberBackend`; Vötsch real backend, Fake simulation and alternate-vendor stub for *substitution tests* | Several mixed vendors concurrently connected |
| GUI | One fixed active chamber context; all actions use its explicit `chamber_id`, even though a chamber selector is not needed | Chamber list/selector, dashboard overview, group views and cross-chamber operations |
| Run engine | One run at a time, single controller/recorder; no group orchestration | Independent concurrent runs, schedules, resource throttles and optional coordinated workflows |
| Authorization | Existing application VIEWER/OPERATOR/ADMIN roles; one-device lease | Per-chamber access grants, owner-transfer rules and fleet administration |
| Persistence | `chamber_id` keyed metadata/records, immutable identity/backend/capabilities per run, per-chamber storage path | Multi-device retention, aggregate queries, alerts and reporting |
| Testing | Reject second physical device; verify ID isolation by alternating two *test doubles* in **separate** single-device test instances | Simultaneous multi-device end-to-end/HIL tests, fleet stress/load and resource fault isolation |

**One chamber per deployment** is a hard v1 guardrail: there must be no supported multi-chamber UI, no runtime fleet loop, no several live controller objects, no orchestration of parallel profiles, and no second real chamber connected under one process. Running independent deployments on separate hosts is outside the multi-chamber feature and remains subject to each deployment's safety/process lock. Do not imply multiple chambers are supported merely because identifiers appear in models.

## Architectural decisions to implement in v1

1. **Stable identity key.** Allocate an immutable configured `chamber_id` (UUID or validated slug), distinct from IP address, vendor, physical serial and user-facing label. Use it for service commands, control lease, run rows, CSV/events, audits and storage; store discovered physical identity separately. Device address can change without changing the history key; binding a different physical unit to the same ID requires an explicit audited re-registration policy.
2. **Generic backend boundary.** UI, runner, SQLite, CSV and services call the vendor-neutral `ChamberBackend` abstraction. Manufacturer-specific I/O remains in a dedicated adapter and externally maintained driver. A new backend does not imply multiple chambers must be active at once.
3. **Controller factory/manager seam.** Define `ChamberManager` or an equivalent interface for `get(chamber_id)`, `connect`, `disconnect` and `status`; implement it with a single validated configured chamber and a maximum physical-chamber count of **one**. No eager fleet map or per-chamber background tasks needed in v1. Keep `ChamberController` otherwise unaware of global application singleton assumptions.
4. **Explicit command routing.** Pass the requested `chamber_id` from an authorized server context to every hardware mutation (start, stop, setpoint, profile start/abort); validate against the configured ID before any device access. No implicit global `current_device` or client-supplied unchecked target. Events/timers must re-check the bound identity and fencing generation.
5. **Future-safe database and files.** Give each record an indexed `chamber_id` where relevant (run, event, telemetry manifest, ownership record, configuration and audit). Run IDs are globally unique; paths are server-generated and scoped under e.g. `data/chambers/<chamber_id>/runs/<run_uuid>/`. CSV samples and events include `chamber_id` or an immutable run manifest reference as specified, and metadata retains the backend/driver version and capability fingerprint. Avoid hard-coded database row IDs, singleton filenames and unversioned schema assumptions.
6. **Ownership key and stop scope.** Store lease, hardware process lock and command generation as per-`chamber_id` constructs, even if the v1 implementation has only one. STOP/FAULT/UNKNOWN apply only to the bound physical unit. An all-chambers STOP, shared STOP queue, automatic failover between devices or multi-device emergency-stop semantics are NOT part of v1.
7. **Configuration layout.** Use a versioned schema that contains a list/map of device configurations but enforces cardinality <=1 in v1. Validate duplicate IDs, duplicate endpoints and unsafe changes; prevent changing model/backend/device binding while any run is active or physical status is uncertain. Preserve schema migration paths; changing the v1 cardinality gate later must require new tests/release.
8. **No hidden shared state.** Profiles are reusable, chamber-independent templates. A run snapshot binds the chosen revision and device identity/capabilities at launch. Avoid mutable global temperature limits, connection flags, singleton poll caches, one shared run file and hard-coded UI labels implying one vendor.
9. **Bounded resource interfaces.** Define per-instance poll/event buffer/recording configuration and clean shutdown hooks for later scaling; implement normal single-chamber behavior only. Do not prebuild multi-device schedulers or assume unlimited parallel TCP polling in v1.
10. **Security.** Authenticate users first, authorize device operations server-side against the configured `chamber_id`. One-device application roles are adequate in v1; design audit fields and interfaces so future per-chamber ACLs can be added without changing profile/record formats.

### Suggested manager interface (architecture sketch, not implementation in this PR)

```python
class ChamberManager(Protocol):
    def get(self, chamber_id: str) -> ChamberController: ...
    def configured_ids(self) -> tuple[str, ...]: ...
```

A v1 implementation MUST return only its one configured instance, or an error for an unknown ID. The registry does not automatically instantiate multiple physical adapters. Protocol/function names can be refined in G01 after review, while preserving these guarantees.

## v1 acceptance criteria (architecture only; no multi-chamber feature tests)

- Configuration containing two distinct physical chambers is rejected **before any connection**, with an actionable "multiple chambers not supported in this release" message. Duplicate physical endpoint across configurations is rejected. No silent acceptance or attempt to connect both.
- Every server-side mutating operation takes/derives and validates `chamber_id`; a wrong or stale ID cannot modify hardware, even after browser refresh, backend reconfiguration or profile restart.
- Running the same conformance tests separately with Vötsch mock, Fake and second-manufacturer stub never requires editing generic UI or runner. These runs are separate one-device scenarios, **not proof of concurrent support**.
- Schema contains a device identity and backend/version/capabilities in the immutable run manifest and preserves it through CSV, crash recovery, import/export and migration; no implicit "chamber 1" hard-coded in code or data.
- Distinct single-device fixtures A and B have isolated storage namespaces and records when executed sequentially. Restart does not misattribute run A to configured device B. No concurrent real chamber support is claimed.
- STOP, profile start and setpoint operations are always routed to the bound configured chamber, and a stale generation/binding cannot cause a command to reach a reconfigured endpoint.
- First release test suite does **not** require starting 2 physical chambers simultaneously, independent fleet dashboards, synchronized profiles, multi-chamber auth or network stress across many devices.

## Deferred roadmap — far future, separate specification and PRs

| Future phase | Work | Mandatory entry/exit gate |
|---|---|---|
| MC01 — Requirement & safety design | Decide device count, operating topology, equipment-specific site STOP/fault policy, concurrency model, quotas and operator permissions | Independent multi-chamber threat/safety/requirements review and per-device hardware approval |
| MC02 — Manager & persistence scale-out | Lift one-device config gate intentionally; create independent controllers, locks, queues, pollers, bounded executors, recorders and per-device recovery | Fault-injection proves one device cannot starve, command or corrupt another |
| MC03 — UI & authorization | Build chamber list/selector/fleet overview, per-chamber roles, alerts and per-device controls; clear context/confirmation on all mutations | Two-user/two-device browser E2E; no stale-tab cross-control |
| MC04 — Concurrency and orchestration | Independently concurrent runs, optional coordinated profiles, resource ceilings, per-device/aggregate monitoring, shutdown semantics | Deterministic race/load tests, disk/backpressure isolation and failure reconciliation |
| MC05 — Fleet HIL and release | Mixed-vendor or multiple approved real chambers, cable loss, stop/fault isolation, stress/upgrade/rollback | Signoff for every supported model and the *multi-chamber system*; updated Windows offline gate |

**Explicit non-goal for the current migration:** MC01–MC05 are not required to implement, test on simultaneous physical devices or merge before v1 release. The v1 requirement is to keep the future extension point stable and to reject unsafe second-device configuration.

## Change management

Before enabling MC02, re-review the chamber contract and safety model, evolve schema/config versions deliberately, confirm multi-process versus single-process strategy and add tests for simultaneous devices. Future features must not silently activate merely because `chamber_id` fields or a factory interface already exist.
