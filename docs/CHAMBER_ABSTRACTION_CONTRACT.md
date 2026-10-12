# Chamber abstraction contract — vendor-neutral GUI and profile engine

Status: **normative implementation requirement** for the NiceGUI migration. Implementation is planned, not delivered by this documentation PR. Read alongside [WEB_GUI_MIGRATION_PLAN.md](WEB_GUI_MIGRATION_PLAN.md) and [DEVELOPMENT_SEQUENCE.md](DEVELOPMENT_SEQUENCE.md).

## Objective and architectural boundary

The entire NiceGUI application must be independent of any specific manufacturer, chamber model, protocol, network transport or driver API. The dashboard, profile editor, execution engine, recording, history, permissions and configuration services depend **only** on stable application-domain DTOs and a typed `ChamberBackend` interface. Model-specific behavior belongs behind an adapter.

    NiceGUI pages / visual components
                 |
    Application services, profile runner, persistence
                 |
    ChamberController (per-chamber I/O queue, lease, fencing, safety)
                 |
    ChamberBackend Protocol (vendor-neutral domain interface)
                 |
    BackendRegistry / allowlisted factory
          +------+-----------------------+
          |                              |
    VotschBackend                   FakeBackend
          |                         (simulation/test)
    external Python driver
    VotschTechnikClimateChamber
          |
    VT4011 / supported Vötsch controllers

    Future: NewVendorBackend -> its own maintained vendor driver -> other chamber

**Hard rule:** no NiceGUI page, profile/CSV code, chamber controller or domain service imports `VotschTechnikClimateChamber`, sends chamber protocol commands, creates device sockets, or branches on manufacturer/model names. ONLY `chamber_web/adapters/votsch.py` may import the existing Vötsch driver. A future adapter may use a separately maintained driver for its manufacturer; device communications must still not be implemented in generic GUI code. Vendor-specific faults/capabilities are normalized at the boundary, without hiding critical information.

The initial release includes **one real** supported backend (Vötsch) and an unmistakably labeled fake backend. Supporting additional real vendors is a later release, but the extension seam, types and integration tests are mandatory in the first foundation PR.

## Required root-level module separation (no src/)

    chamber_web/
      domain/
        chamber.py          # ChamberBackend Protocol, DTOs, enums, units and errors
        profile.py          # vendor-neutral profile input and validation
      adapters/
        registry.py         # explicit allowed backend IDs/factories
        votsch.py           # ONLY place importing VotschTechnikClimateChamber
        fake.py             # deterministic simulator; prominent simulated status
      services/
        chamber_controller.py  # per-chamber queue/lock/STOP/ownership
        chamber_manager.py     # configured chamber identities and controller lifecycle
      execution/            # profile runner imports ONLY domain/services
      pages/                # NiceGUI UI imports ONLY services/domain
      persistence/          # generic records, profiles, events, logs
      tests/                # protocol conformance and second-adapter contract tests

## Typed contract (illustrative API; names can evolve only with tests/docs)

The backend interface is an application-level *port*, not a raw mapping of driver command names. An implementation may expose synchronous calls, but the ChamberController must run blocking adapter calls outside the NiceGUI event loop, serialize them and enforce deadlines/STOP fencing.

```python
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol

class OperationState(Enum):
    STOPPED = "STOPPED"
    RUNNING = "RUNNING"
    UNKNOWN = "UNKNOWN"
    FAULT = "FAULT"

class ReadingQuality(Enum):
    GOOD = "GOOD"
    STALE = "STALE"
    ERROR = "ERROR"

@dataclass(frozen=True)
class ChamberIdentity:
    chamber_id: str        # configured stable instance ID (not only device IP)
    backend_id: str        # e.g. "votsch", "fake"
    manufacturer: str
    model: str
    serial_number: str | None

@dataclass(frozen=True)
class ChamberCapabilities:
    temperature_min_c: float
    temperature_max_c: float
    supports_start_stop: bool
    supports_running_readback: bool
    supports_setpoint_readback: bool
    supports_ramp_up: bool = False
    supports_ramp_down: bool = False
    ramp_up_range_c_per_min: tuple[float, float] | None = None
    ramp_down_range_c_per_min: tuple[float, float] | None = None
    # Unsupported or not HIL-certified features must remain False.

@dataclass(frozen=True)
class ChamberSnapshot:
    identity: ChamberIdentity
    measured_temperature_c: float | None
    setpoint_temperature_c: float | None
    operation_state: OperationState
    quality: ReadingQuality
    sampled_at_utc: datetime | None
    # Controller attaches freshness/age, driver/backend version and errors.

class ChamberBackend(Protocol):
    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def identify(self) -> ChamberIdentity: ...
    def capabilities(self) -> ChamberCapabilities: ...
    def read_status(self) -> ChamberSnapshot: ...
    def set_temperature(self, target_c: float) -> None: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def set_ramp_up(self, rate_c_per_min: float) -> None: ...
    def set_ramp_down(self, rate_c_per_min: float) -> None: ...
```

These are *candidate signatures* for review before code is merged, not claims about existing driver methods. Optional behaviors such as ramp adjustment MUST explicitly raise `UnsupportedCapability` if unavailable, rather than silently doing nothing. Manufacturer-specific data or moisture/humidity features may later use separate typed, versioned capability interfaces and optional data channels; do not add generic unvalidated command pass-through.

## Backend and controller semantics

1. **Capabilities first:** after connecting, the adapter returns verified identity and a model/firmware-specific capabilities snapshot. Compare with a versioned site-approved safety envelope and persisted expected identity. Discovery failure or an unknown model is monitoring-only / fail-closed for active control. Capabilities must never be invented from GUI defaults.
2. **Physical requirements for profile execution:** start/stop, target setpoint command, measured temperature, and trustworthy running/readback status must be supported or the GUI must reject a run. If a model cannot verify stop, it cannot be certified for unattended profiles under the default policy. A read-only adapter can support dashboard monitoring but no Start/Profile buttons.
3. **Normalized units and domain state:** all application-facing temperature values are Celsius; gradient values are Celsius per minute *only after hardware verification and adapter-level conversion*. Backend owns manufacturer-dependent units, command ordering and status decoding. Never infer running from request success; unknown maps to UNKNOWN/FAULT.
4. **Stable error taxonomy:** adapter raises normalized errors: `ChamberConnectionError`, `ChamberTimeoutError`, `ChamberProtocolError`, `UnsupportedCapability`, `ChamberSafetyError` and `ChamberIdentityMismatch` (exact exception names to be frozen in G01). Preserve useful vendor details for audited diagnostic logs, not user-facing raw tracebacks. Error cannot be normalized to success.
5. **State ownership:** adapter must not schedule autonomous profiles or own operator leases. ChamberController is the only device I/O scheduler, command-fencing/STOP priority owner and state publisher. Operator lease, hardware process lock, cancellation, audit and profile timing are vendor-independent.
6. **Command ambiguity:** a timed-out write may have taken effect. Do not blindly retry potentially non-idempotent writes; controller must read back via adapter and enter UNKNOWN/FAULT when readback fails. Physical stop verification remains mandatory per signed site policy.
7. **Configuration/registry:** stable `backend_id` selects a reviewed, explicitly allowlisted adapter factory with validated per-backend settings (IP/address, model restrictions, driver version). No unrestricted import strings from browser input and no arbitrary user-installed Python code in the runtime. Freeze backend ID/configuration/identity during an active run; moving a controller to another backend requires an idle verified disconnect and a new instance.
8. **Multiple chambers later:** chamber_manager maps configured unique `chamber_id` to a distinct controller, physical lock, lease, queue, status stream and recorder namespace. v1 may allow only one configured physical chamber, but MUST not use hard-coded singleton UI names or global device settings. Identity and backend are recorded in each run; no cross-chamber write or shared STOP queue.
9. **Persistent audit compatibility:** profiles remain hardware-neutral, with execution-time compatibility checks against current capabilities; immutable run snapshot records chamber_id/backend_id, manufacturer/model/serial (when available), backend/driver versions, verified capabilities/envelope fingerprint and units. Unknown fields are versioned; do not bake VT4011 command numbers or sockets into CSV/database schemas.
10. **Simulation:** the fake adapter implements the **same contract**, publishes a visible SIMULATION identity/quality marker and never issues device commands. Real hardware cannot silently downgrade to fake upon a network failure. A simulated success cannot satisfy real-device HIL safety gates.
11. **Deprecation policy:** contract/interface schema is versioned. Compatible extensions are additive, optional via capabilities; breaking changes require migration tests and explicit adapter version increase. Vendor-specific new features must not require editing generic NiceGUI screens for existing supported operations.

## User interface behavior driven by capabilities

- Dashboard renders generic measured/setpoint/status fields using DTOs and displays model/vendor text as metadata, not as logic. Unsupported action controls are hidden/disabled with an explicit explanation. Failure/UNKNOWN states are prominent regardless of backend.
- Profile editor marks unsupported gradients and required hardware capabilities as validation issues, not hardware exceptions after launch. Profile preview is generic; actual reachable limits are validated by the controller at run start.
- Runs/history/CSV/settings use stable, backend-neutral schema and units; vendor-specific optional diagnostics are segregated and versioned, never implicitly treated as universal fields.
- Adapter configuration pages may present allowlisted backend-specific connection fields from typed schemas, but ordinary Dashboard/Profile components must not inspect backend_id or compare manufacturer names to choose logic.

## Acceptance tests and architectural enforcement (mandatory)

| Test | Pass condition |
|---|---|
| Static dependency boundary | CI scans/architecture-tests to fail if GUI pages, profile runner, persistence or controller import the Vötsch package or any vendor adapter, or import socket-based device protocol code; vendor-specific imports occur only inside dedicated adapter modules. |
| Contract conformance | Vötsch and Fake adapters plus a minimal **second manufacturer** stub pass the same backend conformance suite for identity/capabilities/status/errors/start/stop/cleanup without changes to generic GUI/services. |
| Alternate backend substitution | With Vötsch adapter replaced by a stub adapter using different temperature limits, unsupported gradients, different vendor identity and status vocabulary, all existing Dashboard/Profile/Runner tests pass without production edits outside adapter registry/config/docs. |
| Negative capabilities | A monitoring-only adapter has no Start/Profile action; unsupported gradients cannot be saved into a runnable snapshot, and NO low-level command is issued. |
| Safety isolation | Two configured chamber IDs have separate controllers/locks/leases/recorders/STOP fencing; STOP and settings for chamber A never act on chamber B. |
| Reconnect & migration | Changing backend while running or with uncertain physical STOP fails closed; persisted runs retain their original backend/driver metadata after upgrade. |
| Offline bundle | Frozen Windows distribution contains explicitly registered adapters and their required vendor drivers; fake works offline and no runtime plugin install/download is needed. |
| HIL | Vötsch driver remains sole protocol owner for Vötsch; actual VT4011 command/readback/stop/fault tests pass independent of alternate-backend stub tests. |

**Definition of done:** Adding another vendor's chamber requires only (a) its maintained communication driver, (b) a new adapter implementing this contract, (c) allowlisted registry/config and capability/site safety approval, and (d) conformance + hardware certification. It must NOT require changes to generic NiceGUI pages, profile engine, CSV/export, run history or base ChamberController for basic temperature profiles.
