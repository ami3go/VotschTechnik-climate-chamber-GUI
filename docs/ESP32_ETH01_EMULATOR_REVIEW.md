# ESP-EMU-01 engineering code review — 2026-10-22

**Review nature:** implementation-author technical self-review, **NOT** an
independent human review or sign-off. Independent reviewer remains required
before draft PR #84 can merge. Reviewed branch:
`feat/esp32-eth01-chamber-emulator` and current S!MPAC Python driver
commit `d22dc05687cac4c5cdef440fb52b05965ed3d146`.

## Correctness evidence

- Exact five-digit command framing and literal 0xB6/CR with bounded 128-byte
  ingress. Host golden tests cover valid/invalid frames, setpoint, gradients,
  manual start/stop, auxiliary digital values, and temperature dynamics.
- Reference TCP endpoint compiles the exact same portable C++ command source
  as firmware; Python integration makes real socket calls through the
  maintained driver, including typed outputs 1..8, read-only discovery,
  repeated STOP readback, 1,000-query liveness, partial frames and fault replies.
- Compiler enforces C++17 and host warnings-as-errors. PlatformIO version,
  framework, PHY reference pin mapping and external driver SHA are pinned.
- Serial console controls faults without allowing unauthenticated test
  management commands over the chamber protocol port. No GUI/HIL bypass
  implemented. On reset the simulated chamber is initialized STOPPED.

## Open blocking findings

| ID | Severity | Finding | Exit condition |
| --- | --- | --- | --- |
| EMU-B01 | BLOCKER | Actual purchased board revision, regulator, PHY and GPIO0 oscillator uninspected | Photograph markings, compare manufacturer schematic, measure 3.3 V logic/5 V supply; revise mapping before flashing |
| EMU-B02 | BLOCKER | Simulator-only trust not established; IP/serial self-report spoofable | Independently review out-of-band enrollment and driver-maintained attestation; GUI remains disabled |
| EMU-B03 | BLOCKER | No physical Ethernet/DHCP/static/cable recovery or flash evidence | Authorized original WT32-ETH01 bench log and network packet captures |
| EMU-B04 | BLOCKER | Independent human safety/reliability review absent | Review exact final commit, close findings, approve separately |
| EMU-H01 | HIGH | 10012 chamber-status shape provisional, physical golden capture unavailable | Obtain manufacturer/real-controller trace and correct/disable as necessary |
| EMU-H02 | HIGH — SOFTWARE FIX, HIL OPEN | TCP response write now tracks an offset, retries short writes, and closes after a finite 1 s write deadline in `src/main.cpp` (`2b8ac3ac`). **Slow/backpressured real Ethernet client behavior remains NOT RUN.** | Verify partial-write and stale/slow client behavior on WT32-ETH01 hardware; preserve diagnostic UART evidence |
| EMU-H03 | HIGH | ESP watchdog enrolls application loop but cannot guarantee independent IP event/network task health | Stress test WDT and link stall, implement subsystem liveness bounds |
| EMU-H04 | HIGH — SOFTWARE FIX, NETWORK HIL OPEN | Static IPv4 inputs and saved NVS are now validated by a portable, host-tested contiguous-mask, usable-host, same-subnet-gateway and DNS policy (`emulator_protocol.cpp`, `src/main.cpp`); address collision is **not** software-proven | Verify collision/DHCP fallback/real Ethernet link behavior on WT32-ETH01; do not certify from native C++ tests |
| EMU-H05 | HIGH | Fault injection lacks complete physical validation and durable trace export | Capture UART log plus host/GUI recovery for every scenario |
| EMU-H06 | HIGH | Model approximates thermal behavior, not calibrated real chamber physics; basic model intentionally ideal | Characterize against recorded chamber dynamics only if needed for new claims |
| EMU-M01 | MEDIUM | No authenticated OTA (intentionally excluded); erase destroys NVS | Keep UART-only flashing and document backup/recovery policy |

Software logic correction for EMU-H02 is committed, not yet hardware qualified. All physical and trust findings remain OPEN until supported by actual evidence. The emulator
cannot substitute for H01/H02 signed physical chamber acceptance, W02
deployment certification or R01 release approval.

## Review disposition

**REQUEST CHANGES / KEEP DRAFT / DO NOT MERGE** until blocking findings close.
A green compiler and native driver conformance workflow is useful engineering
evidence, but not Ethernet PHY hardware verification or production authorization.
