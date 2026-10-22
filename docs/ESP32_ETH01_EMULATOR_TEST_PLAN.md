# ESP-EMU-01 test, fault and gating plan

## Levels and strict evidence labels

A. **HOST**: native g++ and golden frames from same ESP firmware command
engine; Linux TCP reference endpoint (not a Python transport mock).
B. **DRIVER**: pinned external driver makes actual TCP connects, reads,
setpoint changes, repeated start/stop, reconnect and private network discovery.
C. **BUILD**: pinned PlatformIO compiles firmware; archive `.bin` and SHA256.
D. **FLASHED**: operator records verified board marking, UART reset log,
programming and electrical measurements.
E. **DEVICE**: direct IP discovery, subnet scan, dynamic/static network,
Ethernet cable recovery, concurrent sessions, STOP reply ambiguity and WDT
reset; repeat at least 20 start/stop cycles; record packet capture.
F. **BROWSER**: only after independent simulator enrollment/attestation and
authorization review. Settings discovery, dashboard identity, profile/dwell,
G07 recording, browser refresh, stop/restart, failure visibility.

Levels D/E/F are **NOT RUN**, not PASS, until performed on an authorized bench.

## Fault matrix (local UART physical operator only)

| Command | Expected driver/controller effect |
| --- | --- |
| fault sticky_stop | STOP ACK but 14003 remains RUNNING -> StopNotVerified |
| fault drop_stop | STOP changes state but reply lost -> UNKNOWN (no retry) |
| fault timeout | Suppress replies -> bounded transport timeout |
| fault partial | Missing CR -> transport fails/connection closed |
| fault invalid_sensor | Query 11004 error -> invalid telemetry |
| fault freeze | RUNNING ramp does not approach target |
| fault alarm | Simulated 10012 alarm; 10012 not yet certified |
| fault reset | Reset on next command -> STOPPED on reboot |
| fault delay N | Delay response for N ms (0..2000) |
| Ethernet unplug | Link lost, TCP closed; reconnect without restoring RUNNING |
| fault clear | Restore healthy model behavior without firmware reboot |

For `fault drop_stop`, a lost acknowledgment is deliberately **not** evidence
that physical STOP was confirmed. The driver must throw StopNotVerified.

## Watchdogs

- ESP task watchdog: 8-second loop-task heartbeat only, no separate
  unchecked feeder. Reset reason is emitted at boot. Does not certify
  physical shutdown; this is a simulated chamber.
- Host: all CI build/test subcommands run under
  `scripts/h02_watchdog_command.py` with finite execution and inactivity
  deadlines, process-group teardown, JSON timeline and captured stdout/stderr.
  GitHub job-level timeouts provide another bound.
- API exchanges: existing driver has a monotonic timeout, never retries a
  possibly executed write. Reference TCP server only used on test hosts.

Suggested physical opt-in runner must reject execution unless explicit
`ESP_EMULATOR_HARDWARE_OPT_IN=1`, isolated subnet, verified device identity,
recorded UART logs and operator present. **No physical test runner is
automatically invoked in CI.**

## Acceptance must not reinterpret test evidence

Any missing board/CI artifact is NOT RUN; a failing CI check is FAIL;
no emulator proof can close a site HIL safety gate.
