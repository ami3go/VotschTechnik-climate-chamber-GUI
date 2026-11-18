# LEO-EMU-01 — Arduino Leonardo / W5500 acceptance ledger

Status: **DRAFT IMPLEMENTATION / NOT HARDWARE VERIFIED**.
Dependency: ESP-EMU-01 [draft PR #84](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/84).
Protocol authority: Vötsch Python driver main
`d22dc05687cac4c5cdef440fb52b05965ed3d146`;
UPS hardware reference: `USB-UPS-Simulator` master
`114cff933d5adc7d079267d86e947347b5c98107`.

| Acceptance requirement | Evidence status | Reason |
| --- | --- | --- |
| Original UPS Leonardo/W5500 wiring audited | VERIFIED FROM REPO | ICSP SPI, W5500 D10, SD D4 HIGH, native USB and Serial1 |
| S!MPAC core and finite frame buffers | IMPLEMENTED | 80-byte ingress, 64-byte response, explicit error replies |
| Thermal model and start/stop semantics | IMPLEMENTED, CI PENDING | fixed-point Basic, 10x accelerated, STOP readback |
| Host C++ golden tests | CI PENDING | native source compiled with warnings as errors |
| External driver direct/subnet discovery and control | CI PENDING | real TCP reference; no Python transport mock |
| Leonardo flash/RAM budget and firmware.hex | CI PENDING | pinned PlatformIO and Ethernet lib |
| Real Leonardo+W5500 flash / UART log | NOT RUN | no physical board connected |
| Real TCP 2049, DHCP/static, link reconnection | NOT RUN | hardware integration required |
| WDT reset/STOPPED persistence and fault recovery | NOT RUN ON HARDWARE | code implementation alone not sufficient |
| GUI G04 controller/profile, G07 recording, web browser | BLOCKED | simulator-only secure enrollment not independently proven |
| Physical chamber HIL/release approval | UNCHANGED | emulator evidence cannot certify a real chamber |
| Independent review | NOT COMPLETED | review final test/board evidence separately |

## Explicit open technical risks

- AVR SRAM/flash must leave adequate stack/headroom; compiler-only PASS is
  insufficient for runtime memory safety.
- EEPROM integrity and static network validation need power-cut tests.
- W5500 Ethernet library socket behavior / DHCP lease changes must be checked
  under cable reconnect and malformed clients.
- Interrupt/stack behavior and 8-second watchdog reset cause must be tested
  with the actual board and serial logs.
- Normal TCP endpoint is not authenticated; deploy only on an isolated test
  network. An alphanumeric `SIM` serial is **not** proof of trusted
  emulator enrollment, so GUI activation remains blocked.
- No claim of identical thermal fidelity to ESP32 Realistic mode.
- Host-based tests do not imply the physical board has been flashed.

No PR merge or safety-gate removal until blocking review findings have
objective CI and board evidence.
