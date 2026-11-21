# LEO-EMU-01 — Arduino Leonardo / W5500 acceptance ledger

Status: **DRAFT IMPLEMENTATION / NOT HARDWARE VERIFIED**.
Operator test procedure: [LEO-HIL-RUNBOOK-01 — full Leonardo hardware/software runbook](LEONARDO_W5500_FULL_TEST_RUNBOOK.md). Its acceptance table starts NOT RUN/BLOCKED; the existence of a runbook is not test evidence.
Dependency: ESP-EMU-01 [draft PR #84](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/84).
Protocol authority: Vötsch Python driver main
`d22dc05687cac4c5cdef440fb52b05965ed3d146`;
UPS hardware reference: `USB-UPS-Simulator` master
`114cff933d5adc7d079267d86e947347b5c98107`.

| Acceptance requirement | Evidence status | Reason |
| --- | --- | --- |
| Original UPS Leonardo/W5500 wiring audited | VERIFIED FROM REPO | ICSP SPI, W5500 D10, SD D4 HIGH, native USB and Serial1 |
| S!MPAC core and finite frame buffers | IMPLEMENTED | 80-byte ingress, 64-byte response, explicit error replies |
| Thermal model and start/stop semantics | HOST PASS | fixed-point Basic, 10x accelerated, STOP readback in golden tests |
| Host C++ golden tests | REQUALIFICATION PENDING | Current stacked head adds full 1..8 output coverage and 100,000-frame liveness; exact-head CI required |
| External driver direct/subnet discovery and control | REQUALIFICATION PENDING | Current pinned driver d22dc05, typed outputs and negative TCP faults; exact-head CI required |
| Leonardo flash/RAM budget and firmware.hex | REQUALIFICATION PENDING | Prior build left only 556 flash / 989 static SRAM bytes; current exact-head resource gate must pass |
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

## Pinned build evidence (2026-11-18)

- Source revision: `bbe0d4cc1cc263e5683ef0c4dfed49aa760f6a94`.
- Build run: [GitHub Actions #44287212844](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/44287212844).
- Built artifact: `firmware/esp32_eth01_chamber_emulator/.pio/build/leonardo-w5500/firmware.hex`.
- SHA-256: `2f7ea247e7385cbf724249d56757746c210b836fd99bbe74f5a2a5cb1b287a50`.
- Usage: 28,116 / 28,672 bytes flash (98.1%), **556 bytes free**;
  1,571 / 2,560 bytes static RAM (61.4%), **989 bytes free**.
- New CI budget guard requires at least 512 bytes free flash and
  768 bytes static RAM. AVR feature scope should remain minimal.
- Later documentation/CI-guard changes require their own validation;
  never interpret this build as flashed or physically verified.

**Disposition: build + host interoperability confirmed; actual hardware and
GUI emulator activation remain blocked until separate opt-in bench tests
and trustworthy simulator-only enrollment have been reviewed.**
