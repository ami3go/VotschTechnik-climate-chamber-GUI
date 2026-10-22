# ESP-EMU-01 acceptance and independent review ledger

Status: **OPEN / ENGINEERING PROTOTYPE / GUI INTEGRATION BLOCKED**.
Date: 2026-10-22. Feature branch:
`feat/esp32-eth01-chamber-emulator`.

| Gate | Status | Justification |
| --- | --- | --- |
| Upstream driver wire format inspected | VERIFIED | Driver main b56cfbd; command numbering and CR/B6 confirmed |
| Core + TCP reference implementation | HOST PASS | Native C++ golden tests and TCP reference, [CI run 39765797547](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/39765797547) |
| Original WT32-ETH01 board revision inspected | NOT RUN | Purchased board not available for marking/schematic comparison |
| Firmware PlatformIO compile | BUILD PASS (reference target only) | Pinned PlatformIO build, [CI 39765797547](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/39765797547), SHA-256 `de09d42e2d4ebfdb743796785775b82ab07840b96931dae03866dc078b7da6bc` |
| Driver discovery, start/stop, gradients | DRIVER PASS (host TCP) | Maintained external driver b56cfbd; direct/private subnet discovery and repeated STOP, [CI 39765797547](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/39765797547) |
| LAN8720 link/DHCP/static, reset, NVS | NOT RUN ON BOARD | Requires fitted hardware and wired LAN |
| WDT trigger and recovery | NOT RUN ON BOARD | Code present; deliberate hang test not yet authorized |
| Realistic thermal inertia and noise | HOST PASS | Three thermal modes, deterministic lag/noise and runaway faults covered in host tests; not physically validated |
| Fault injection full matrix | PARTIAL | Console scenarios implemented; link disruption external |
| Secure emulator-only enrollment/attestation | BLOCKED | Serial/IP are spoofable; no trusted external-driver attestation |
| GUI network-emulator mode and profile recording | BLOCKED | Physical-HIL bypass risk; do not enable with self-reported identity |
| Site physical-HIL or release certification | UNCHANGED / NO-GO | Out of scope and no site approval |
| Independent human safety/code review | NOT OBTAINED | Requires independent reviewer on exact PR head |

Technical self-review areas before merge: concurrent Ethernet loss, Arduino
library portability, PHY marking vs schematic, TCP server accept semantics,
NVS validation (including masks/gateway), WDT enrollment, partial TCP writes,
fault-lifecycle auditing, uncertified auxiliary-output readback behavior, actual 10012
wire-capture and replay. Any of these that violates a required gate blocks merge.

The firmware currently cannot be presented as a finished dependable
instrument; it is a testable engineering foundation. A passing CI matrix
does not upgrade missing physical verification to PASS.

## Provenance and scope of PASS evidence

Cross-compiled source revision: `457403c5f2f69bfdfbf89fc7b3e127fe71f8c3dd`.
Firmware file: `firmware/esp32_eth01_chamber_emulator/.pio/build/wt32-eth01/firmware.bin`.
SHA-256: `de09d42e2d4ebfdb743796785775b82ab07840b96931dae03866dc078b7da6bc`.
CI: [native + PlatformIO watchdog run #39765797547](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/39765797547).
The acceptance/readiness/review-document commits following this source revision
have no firmware-source changes. Later CI runs are checked separately.
Independent engineering review gaps: [ESP32_ETH01_EMULATOR_REVIEW.md](ESP32_ETH01_EMULATOR_REVIEW.md).

**Critical:** Firmware compiled for a reference board manifest does NOT prove
that the purchased board has correct voltages, Ethernet PHY, oscillator,
power supply, boot strapping or safety constraints. These remain NOT RUN.
