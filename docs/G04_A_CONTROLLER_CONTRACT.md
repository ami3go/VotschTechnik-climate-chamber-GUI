# G04-A — mock-only ChamberController API and safety contract

Status: **implementation PR; not HIL certified and NOT authorized for physical I/O**.
Normative upstream: [P00_DECISION_CONTRACTS.md](P00_DECISION_CONTRACTS.md),
[CHAMBER_ABSTRACTION_CONTRACT.md](CHAMBER_ABSTRACTION_CONTRACT.md),
[DEVELOPMENT_SEQUENCE.md](DEVELOPMENT_SEQUENCE.md). This addendum documents an
implementation seam. It does **not** change pending site STOP/fault decisions.

## Public service boundary and coordination

`ChamberManager([ChamberConfig(chamber_id, backend_id)], backend_factory=...)`
still enforces exactly one configured device **before any backend factory call**.
`get(chamber_id)` remains a guarded service facade, not the raw backend.
`connect`, `disconnect`, `status`, `start`, `set_temperature`,
`stop` and `reconcile_stop` require explicit configured `chamber_id`.
Additional server-only methods:

| Method | Contract |
|---|---|
| `health(chamber_id)` | Immutable `ControllerHealth(chamber_id, state, generation, connected, stop_latched, reason)`; STOP_REQUESTED, VERIFIED_STOPPED, UNKNOWN and FAULT are controller states distinct from backend operation-state readbacks. |
| `claim_operator(chamber_id, owner) -> token` | Refuses a second owner; token is an opaque in-memory command-ownership token **not** a login credential. |
| `release_operator(chamber_id, token)` | Only current owner can release. |
| `start(chamber_id, operator_token=...)` and `set_temperature(..., operator_token=...)` | Require token when an operator ownership claim exists. Trusted server-side no-token calls remain only for G01 compatibility; G08-min must require authentication/authorization before exposing ANY mutation to clients. |
| `stop(chamber_id)` | Independently authorized by future OPERATOR/ADMIN auth gate; never blocked by a foreign operator token. No successful return until fresh GOOD STOPPED readback. |
| `reconcile_stop(chamber_id)` | Requires a fresh GOOD STOPPED readback; clears the persistent uncertainty latch only following explicit server-side reconciliation. G08-min must assign permission/audit policy to this action. A newer\n  STOP/FAULT generation invalidates even an already-running reconciliation read;\n  old readback may never clear a newer STOP latch. |
| `start_polling(chamber_id, interval_s=2.0)` | Optional bounded queued server-side periodic reads; `status` is also a serialized poll. No polling is started by the current demo page. |

A manager wraps one `ChamberController` per deployment. It also preserves\nG02-A's ID-guarded `capabilities(chamber_id)` snapshot projection and\nbootstrap-owned demo dashboard teardown; separately injected dashboard managers\nremain caller-owned. Controller owns
`ChamberBackend` and does not import vendor adapters or protocol packages;
only registry/adapter code resolves a backend. For Vötsch, the maintained
external driver remains the exclusive eventual hardware communication layer.

## Safety and I/O semantics

1. **Mock-only hard gate:** controller connect rejects physical Vötsch configuration
   with `Physical hardware I/O DISABLED` *before any adapter call*. The
   controller checks the adapter-owned `simulation_only is True` marker, not a
   vendor name; Fake and alternate-stub report True, whereas Vötsch reports
   True **only** when constructed with an injected mock driver factory.
   A simulated identity is independently verified after connect.
   This adapter marker is a trusted **test** contract, not a production safety permission.
   A site-approved physical gate and G08-min are not implemented.
2. **One process owner:** an OS advisory file lock, plus a per-process registry,
   excludes a second controller for the same `chamber_id`. The OS lock is held
   across the entire connected lifetime. A per-ID SQLite row stores process
   owner UUID, monotone fencing generation and uncertainty; acquisition and
   generation updates use `BEGIN IMMEDIATE`. Old-owner/crash state requires
   explicit reconciliation after restart. Configure a shared local lease
   directory per deployment; the default is
   `~/.chamber_web/ownership`. A failed blocking worker is deliberately not
   detached to silently transfer device ownership.
3. **Single worker:** blocking backend calls occur only on one server-side
   daemon thread. Queued writes each bind `chamber_id` and the fencing
   generation and revalidate both just before dispatch; validation, capability
   and finite temperature checks occur before queueing. Each mutation
   performs a fresh readback (setpoint ±0.1 °C; start RUNNING; stop STOPPED).
   A stale/mismatched/ERROR readback, timeout, adapter exception or
   ambiguous acknowledgement latches UNKNOWN or FAULT and prevents
   subsequent START/setpoint dispatch.
4. **STOP priority:** STOP synchronously persists an incremented generation and
   sets `STOP_REQUESTED`, invalidating queued old-generation commands before
   waiting on a backend. STOP work is placed ahead of ordinary writes and
   polls; repeated STOPs are allowed even when latched. STOP never blindly
   retries a failed backend command and never asserts physical safety on a
   deadline alone. Another caller's ownership token cannot veto STOP.
5. **No preemption claim:** a synchronous backend call already admitted by the
   worker may finish *after* STOP intent. If it hangs, STOP cannot reach the
   backend within its deadline. Report UNKNOWN/FAULT, keep the process lock
   while that worker is alive, require local intervention. The future D01
   driver and HIL gate must determine finite real-device I/O bounds.
6. **Recovery:** no auto-resume, auto-start, setpoint replay, default reset to
   ambient, gradient mutation, or simulator fallback occurs. Recovery after
   fault/STOP is an explicit, fresh, identity-bound readback followed by
   `reconcile_stop`. Controller-created STOP latches stay set after a
   verified STOP until that explicit action.
7. **Shutdown:** disconnect does not issue an unapproved physical STOP, does not
   claim the chamber stopped and does not release the process lock while an
   unfinished worker is still executing. SQLite uncertainty survives
   unverified shutdown. Process crash/power-loss and SQLite/file-lock
   behavior on network filesystems still require deployment/HIL validation.

## Explicit limitations/gates

- **NO physical writes or live HIL.** Neither these mock tests nor Windows CI
  constitute approval of a site response policy. Physical STOP remains a
  manufacturer/local safety function; web STOP is command intent.
- This G04 API is **not** a security/authentication API, nor a durable run
  journal. G08-min must enforce OPERATOR/ADMIN roles, CSRF/origin checks,
  audited commands, and deny VIEWER/unauthenticated writes including on loopback.
  G06/G07 must implement run lifecycle and crash recovery independently.
- Controller timeouts bound caller waiting, not the execution duration of an
  arbitrary blocking third-party driver. Real I/O requires documented driver
  deadlines and on-site STOP latency evidence.
- A single controller/lease is implemented. Multi-device operation, fleet
  arbitration and distributed-host lease consensus remain explicitly out of
  scope. OS locks require a reliable **local** filesystem and one deployment
  sharing the same ownership path.
- The adapter `simulation_only` marker and injected driver factories are
  strictly test-only. Production factories cannot activate physical hardware
  via this controller, and neither marker nor injection knobs may be exposed
  on the NiceGUI web page.
- P00 signed safety envelope, gradient baseline, model/firmware identity,
  certified STOP behavior and G08-min are all pending and block G05/HIL.

## Acceptance verification

`python -m unittest discover -s tests -p "test_chamber_*.py" -v`

`python -m ruff check chamber_web/domain chamber_web/adapters chamber_web/services chamber_web/persistence tests/test_chamber_backend.py tests/test_chamber_controller.py tests/test_profile_storage.py --select E4,E7,E9,F`

Windows CI runs both Python 3.10 and 3.12. Fault tests cover stale
readbacks, wrong IDs, locked ownership, persisted restart uncertainty,
parallel queued setpoint fencing, STOP race priority, setpoint echo mismatch,
unauthorized owner collision and stuck adapter deadlines. All use simulated
backends and must not be interpreted as real STOP latency evidence.
