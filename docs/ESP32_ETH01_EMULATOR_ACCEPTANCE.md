# ESP-EMU-01 acceptance and independent review ledger

Status: **OPEN / ENGINEERING PROTOTYPE / GUI INTEGRATION BLOCKED**.
Date: 2026-10-22. Feature branch:
`feat/esp32-eth01-chamber-emulator`.

| Gate | Status | Justification |
| --- | --- | --- |
| Upstream driver wire format inspected | VERIFIED | Driver main b56cfbd; command numbering and CR/B6 confirmed |
| Core + TCP reference implementation | IMPLEMENTED, PENDING CI | Portable production C++ core, host tests and TCP reference |
| Original WT32-ETH01 board revision inspected | NOT RUN | Purchased board not available for marking/schematic comparison |
| Firmware PlatformIO compile | PENDING CI | Cannot claim success without captured build artifact |
| Driver discovery, start/stop, gradients | PENDING CI | Real TCP integration suite under watchdog |
| LAN8720 link/DHCP/static, reset, NVS | NOT RUN ON BOARD | Requires fitted hardware and wired LAN |
| WDT trigger and recovery | NOT RUN ON BOARD | Code present; deliberate hang test not yet authorized |
| Realistic thermal inertia and noise | NOT IMPLEMENTED | Basic and accelerated only |
| Fault injection full matrix | PARTIAL | Console scenarios implemented; link disruption external |
| Secure emulator-only enrollment/attestation | BLOCKED | Serial/IP are spoofable; no trusted external-driver attestation |
| GUI network-emulator mode and profile recording | BLOCKED | Physical-HIL bypass risk; do not enable with self-reported identity |
| Site physical-HIL or release certification | UNCHANGED / NO-GO | Out of scope and no site approval |
| Independent human safety/code review | NOT OBTAINED | Requires independent reviewer on exact PR head |

Technical self-review areas before merge: concurrent Ethernet loss, Arduino
library portability, PHY marking vs schematic, TCP server accept semantics,
NVS validation (including masks/gateway), WDT enrollment, partial TCP writes,
fault-lifecycle auditing, unsupported auxiliary-output setters, actual 10012
wire-capture and replay. Any of these that violates a required gate blocks merge.

The firmware currently cannot be presented as a finished dependable
instrument; it is a testable engineering foundation. A passing CI matrix
does not upgrade missing physical verification to PASS.
