# LEO-HIL-RUNBOOK-01 — full chamber-software test campaign with Arduino Leonardo + W5500

**Applies to:** Arduino Leonardo R3 / ATmega32U4 plus an ICSP-connected W5500 Ethernet Shield V2.0, emulating a Vötsch VT 4011 over S!MPAC TCP/2049.

**Source:** GUI repository `ami3go/VotschTechnik-climate-chamber-GUI`, stacked emulator [PR #88](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/88) on [PR #84](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/84). Authoritative communications library: [Vötsch Python driver](https://github.com/ami3go/VotschTechnik-climate-chamber-Python), pinned by `requirements-hardware.txt` to `d22dc05687cac4c5cdef440fb52b05965ed3d146`.

**Initial evidence status:** firmware/native driver CI passed on the previous stacked PR head; actual Leonardo+W5500 board, DHCP, USB and fault injection **have not been tested by the author of this runbook**. Every checklist result below starts `NOT RUN`.

## 0. Scope, conditions and stop rule

The Leonardo is a **network hardware emulator**, not a climate chamber and not an authenticated substitute for one. Separate the following results:

- **B — physical-board evidence:** genuine USB-CDC, EEPROM, W5500 Ethernet, driver TCP/2049, read/write, fault and reset tests; these can be run now on an isolated bench with explicit opt-in.
- **S — software-only simulation:** G04/G05/G06/G07/G08, NiceGUI browser and security regression on the in-process simulator. These do **not** communicate with Leonardo.
- **D — driver discovery in NiceGUI:** the Settings Auto-detect function may perform **read-only** driver-owned probes of the Leonardo while the GUI remains in ordinary simulation mode. Selecting an unsaved result never authorizes a physical connection.
- **G — GUI-to-Leonardo control:** signed bench-emulator enrollment is implemented in [EMULATOR_ENROLLMENT.md](EMULATOR_ENROLLMENT.md), but remains **BLOCKED for qualification** until that implementation is independently reviewed/merged and the live board passes the stability/profile gates. A string such as `SIMLEO0001` or matching USB and Ethernet serials is useful bench evidence, **not** cryptographic attestation. Do not turn off G04, G08, profile admission or temperature limits to make this test run. The signed emulator path requires no HIL PIN; a real-chamber physical path still does.
- **R — real-chamber HIL, W02 signed release and R01 site certification:** **NOT established** by any emulator test. Retain these gates unchanged.

**Immediate ABORT / NO-GO:** unexpected Ethernet address or serial, another chamber on the segment, RUN not returning to 0, TCP identity inconsistent with local USB status, 8-second WDT loop, wrong firmware/AVR resource budget, unexpected external relay movement, unverified STOP, or loss of isolation. Never run these commands against an actual Vötsch device.

A watchdog bounds each long **software** task and the physical-emulator verifier. For a real energized chamber use its internal STOP/readback/cancellation procedure; a killed host process does not stop the chamber. A watchdog termination during a board test is an **ABORT** until USB proves `RUN=0` or the emulator is power-cycled and rechecked.

## 1. Equipment, topology and preparation (LEO-00)

| Equipment | Required | Check |
|---|---|---|
| Arduino Leonardo R3, ATmega32U4, 16 MHz | Yes | USB CDC enumerates; bootloader intact |
| W5500 Ethernet shield with mating 2×3 ICSP socket | Yes | SPI comes from **ICSP**, not UNO D11–13 alone |
| W5500 CS D10; optional SD CS D4 | Yes | D4 is driven OUTPUT HIGH; no SD card needed |
| USB data cable + isolated 5 V USB supply | Yes | No duplicate board power feeds |
| Ethernet cable and isolated switch/direct laptop NIC | Yes | **No corporate/site/real-chamber Ethernet connection** |
| Linux laptop (recommended) or Windows host | Yes | Python 3.12, USB/serial permission, firmware build tools |
| Serial terminal at 115200 8N1 | Yes | Only one process owns the USB COM/tty device at a time |
| Optional oscilloscope, USB power meter, serial capture | Recommended | Record WDT/reset and power/intermittent failures |

Suggested default (only when no DHCP server is available):

```text
          USB power + console (115200)
Linux/Windows test PC ─────────────────── Leonardo R3
      |                                    + W5500 (D10 CS, ICSP SPI)
      +── isolated Ethernet / switch ───── RJ45 TCP/2049

PC Ethernet: 192.168.42.10/24   (no gateway)
Leonardo:    192.168.42.42/24   (no gateway, DHCP fallback)
Serial:      SIMLEO0001        (EEPROM factory default)
MAC:         02:56:4F:54:43:01
```

Disconnect VPNs/other lab test instruments from the isolated interface. Photograph the board and ICSP connection; record board/shield revisions, USB/host OS, operator, date/time (UTC), NIC IP, MAC and a signed-off statement that the RJ45 segment cannot reach a real chamber.

Create one evidence folder per test campaign **inside the GUI repository after cloning it in section 2**; never overwrite prior data. On Windows use PowerShell `New-Item -ItemType Directory -Force test-evidence/leonardo/campaign-01` and `(Get-Date).ToUniversalTime().ToString('o')`.

**Pass:** no real hardware other than the Leonardo is reachable on test Ethernet; device is physically identifiable and initial RUN is zero.

## 2. Source, environment, and no-hardware regression (LEO-01)

Do not run firmware from an unreviewed source or substitute a newer unpinned driver. Fetch the actual stacked branch, record its immutable SHA and verify that it includes the ESP32 base:

```bash
git clone --branch feat/leonardo-w5500-chamber-emulator \
  https://github.com/ami3go/VotschTechnik-climate-chamber-GUI.git
cd VotschTechnik-climate-chamber-GUI
mkdir -p test-evidence/leonardo/campaign-01
date -u --iso-8601=seconds > test-evidence/leonardo/campaign-01/start-utc.txt
git status --short
git rev-parse HEAD | tee test-evidence/leonardo/campaign-01/gui-commit.txt

python3 -m venv .venv
. .venv/bin/activate
python -m pip install platformio==6.1.18 pyserial==3.5 colorama==0.4.6
python -m pip install -r requirements-hardware.txt

git clone https://github.com/ami3go/VotschTechnik-climate-chamber-Python.git external-driver
git -C external-driver checkout d22dc05687cac4c5cdef440fb52b05965ed3d146
git -C external-driver rev-parse HEAD | tee test-evidence/leonardo/campaign-01/driver-commit.txt
```

If the cloned `external-driver/` directory already exists, **verify its revision rather than silently overwriting it**. PlatformIO first-time package download requires internet; the actual emulator test network must remain isolated. Do not print PINs/tokens in environment captures.

Linux/native codec + unmodified vendor driver over a local reference TCP server (no board, no chamber):

```bash
D=firmware/esp32_eth01_chamber_emulator
mkdir -p "$D/build"
g++ -std=c++11 -Wall -Wextra -Werror -I"$D/include" \
  "$D/src/leonardo_core.cpp" "$D/test/host/test_leonardo.cpp" \
  -o "$D/build/test_leonardo"
g++ -std=c++11 -Wall -Wextra -Werror -I"$D/include" \
  "$D/src/leonardo_core.cpp" "$D/test/host/leonardo_tcp_reference.cpp" \
  -o "$D/build/leonardo_tcp_reference"

python scripts/h02_watchdog_command.py --timeout-s 120 --idle-timeout-s 60 \
  --log-dir test-evidence/leonardo/campaign-01/native-golden -- \
  "$D/build/test_leonardo"

python scripts/h02_watchdog_command.py --timeout-s 240 --idle-timeout-s 90 \
  --log-dir test-evidence/leonardo/campaign-01/native-driver -- \
  python -m unittest discover -v -s "$D/test/integration" \
    -p test_leonardo_driver.py
```

**Pass:** C++ golden tests, strict B6 framing, values/ranges, Start/Stop, bad frames, read-only direct-IP/subnet discovery where a RFC1918 NIC exists, and driver TCP integration. A discovery test that skips because there is no RFC1918 interface is **SKIP**, not PASS. Run native tests on Linux as per CI; do not assume the Linux reference server compiles unchanged on Windows.

## 3. Build, AVR budget, flash and verification (LEO-02)

```bash
D=firmware/esp32_eth01_chamber_emulator
python scripts/h02_watchdog_command.py --timeout-s 1200 --idle-timeout-s 300 \
  --log-dir test-evidence/leonardo/campaign-01/build -- \
  pio run -d "$D" -e leonardo-w5500

sha256sum "$D/.pio/build/leonardo-w5500/firmware.hex" \
  | tee test-evidence/leonardo/campaign-01/firmware-sha256.txt

pio device list
python scripts/h02_watchdog_command.py --timeout-s 180 --idle-timeout-s 60 \
  --log-dir test-evidence/leonardo/campaign-01/flash -- \
  pio run -d "$D" -e leonardo-w5500 -t upload --upload-port /dev/ttyACM0

pio device monitor --baud 115200 --port /dev/ttyACM0
```

Replace `/dev/ttyACM0` with the detected port; on Windows use `COM5` or the actual observed port. Leonardo Caterina briefly changes USB enumeration during bootloader upload; close the serial monitor before uploading, press RESET to reenumerate if necessary. Never assume that successful compilation means successful flashing.

**Mandatory size gate:** ATmega32U4 firmware must use no more than **28,160 / 28,672 bytes flash** (at least 512 free) and **1,792 / 2,560 bytes static SRAM** (at least 768 free). Save full compiler memory report and the hash of **the exact built firmware**. Historic SHA/size reports from another commit are not substitute evidence. Near-limit stack/high-water evidence must be reviewed independently.

**Pass:** upload completes, USB CDC reenumerates, console reads `LEO-EMU 0.1.0`, no continuous boot loop, LED heartbeat toggles, firmware checksum recorded.

## 4. Network and out-of-band USB identity (LEO-03/04)

On a disconnected Linux NIC, set the test host IPv4 (replace `enp3s0` with the actual isolated NIC):

```bash
sudo ip address add 192.168.42.10/24 dev enp3s0
sudo ip link set enp3s0 up
ip -4 address show dev enp3s0
```

Windows administrative PowerShell equivalent, substituting your isolated adapter:

```powershell
New-NetIPAddress -InterfaceAlias "Ethernet" -IPAddress 192.168.42.10 -PrefixLength 24
Test-NetConnection 192.168.42.42 -Port 2049
```

After approximately 10 seconds without DHCP, type `status` in the USB serial console. Expected form:

```text
LEO-EMU 0.1.0 link=1 IP=192.168.42.42 SN=SIMLEO0001 RUN=0 target_centi=2300 actual_centi=2300
```

Actual target/actual temperature may differ after manual tests. `link=1` and the **observed, not assumed** IP and serial must match the subsequent Python test. Verify TCP/2049 using `nc -vz -w 2 192.168.42.42 2049` or Windows `Test-NetConnection`. Ping success is optional; a TCP/2049 test is the authoritative connectivity check.

**No raw GUI protocol implementation:** all production GUI discovery/control must remain in the installed Python driver. A packet capture or raw-frame probe for *emulator protocol debugging only* must not be copied into GUI code.

## 5. Existing physical-board verification: read-only first (LEO-05)

Close `pio device monitor` so `pyserial` can open the USB port. Start with **no writes**. This script independently checks live USB-CDC status, then the maintained external driver's direct-IP discovery, exact serial/model, measured and target temperatures and gradients.

```bash
export LEONARDO_EMULATOR_HARDWARE_OPT_IN=1
python scripts/h02_watchdog_command.py --timeout-s 180 --idle-timeout-s 40 \
  --log-dir test-evidence/leonardo/campaign-01/board-readonly-watchdog -- \
  python firmware/esp32_eth01_chamber_emulator/test/hardware/verify_leonardo.py \
    --ip 192.168.42.42 --usb-port /dev/ttyACM0 --serial SIMLEO0001 \
    --ack-isolated-test-lan --ack-physical-usb \
    --evidence test-evidence/leonardo/campaign-01/board-readonly.json
```

Windows PowerShell: use `$env:LEONARDO_EMULATOR_HARDWARE_OPT_IN="1"` and `--usb-port COM5` with the same Python command. Do not declare a board present from CI alone. A FAIL must include the reason, USB evidence and live Ethernet observations.

**Pass:** process exit 0; JSON `status=PASS`, exact USB and TCP identities equal and no control writes or START took place.

## 6. Controlled physical-emulator Start/Stop cycles (LEO-06)

Only after LEO-05 passes, operator is at the board and local `status` confirms `RUN=0`. **Never** supply `--allow-writes` to a real chamber address. The test performs three START/STOP cycles through the **unmodified driver** and independently reads output 1 after each transition.

```bash
python scripts/h02_watchdog_command.py --timeout-s 180 --idle-timeout-s 40 \
  --log-dir test-evidence/leonardo/campaign-01/board-control-watchdog -- \
  python firmware/esp32_eth01_chamber_emulator/test/hardware/verify_leonardo.py \
    --ip 192.168.42.42 --usb-port /dev/ttyACM0 --serial SIMLEO0001 \
    --ack-isolated-test-lan --ack-physical-usb --allow-writes \
    --evidence test-evidence/leonardo/campaign-01/board-control.json
```

**Pass:** 3/3 cycle readbacks, exit 0, JSON `status=PASS`, subsequent USB `status` shows `RUN=0`. If STOP has no authoritative acknowledgement or the watchdog fires, mark **UNKNOWN / NO-GO**, close host sockets, and independently inspect/reboot the **emulator**. Do not write PASS merely because power was removed.

## 7. Driver feature and validation matrix (LEO-07)

Run the following **serially** against only the verified emulator. Close unrelated discovery/client processes: the Leonardo firmware serves one TCP client at a time. Save before/after USB `status` and driver-read values. The existing host TCP suite covers expected command shapes; real-board verification of each feature must be logged separately.

| Check | Operator action through the maintained Python driver | Expected |
|---|---|---|
| ID and year | Read `test_system_type`, `serial_number`, `year_manufactured` | `VT4011-EMULATOR`, `SIMLEO0001`, `2026` |
| Direct/subnet discovery | `discover_chambers("192.168.42.42")` and isolated `discover_chambers("192.168.42.0/24")` | One matching identity, bounded scan; never a real chamber |
| Measured and target | Read `temperature_measured` and `temperature_set_point` | Finite numeric, default roughly 23 °C |
| Target write/readback | Set 24.0 then 27.25 °C (operator approved) | Readback matches 0.01 °C quantization; only on emulator |
| Temperature boundaries | Attempt invalid target below -40 or above 180, NaN, string | Refused; no state mutation |
| Gradient | `gradient_up=3.0` and `gradient_down=2.0` | Readback matches; 5.01/3.51 refused |
| Run state | Read `is_running` before and after verified START/STOP | Digital output 1 changes 0/1/0 |
| Outputs 7/8 | Read reported count/names, then set `compressed_air`/`dryer` ON/OFF | Each returned state matches; outputs are **simulated** |
| Unsupported output | Request unadvertised or malformed numbered output | Typed driver error, no unintended write |
| Restart persistence | Reboot by USB RESET after verified STOP | Serial/MAC/network persist; run state resets STOPPED |
| Unknown command | Use host golden test or isolated test-only frame probe | `0 + 0xB6 + error + CR`; no start |

For numerical and output **mutations**, use a reviewed/operator-approved test harness with the same initial STOP, verified STOP and evidence controls as LEO-06. The shipped physical verifier does **not** exercise the full matrix. Its presence is not proof that all these checks passed.

The S!MPAC separator is **one byte 0xB6**, not the two-byte UTF-8 sequence. Request maximum: **80 bytes**; response maximum: **64 bytes**. Observe test-only malformed-frame failures without sending any START or SET frame. Keep negative probes on the isolated network, and do not add raw sockets to `chamber_web`.

## 8. Thermal model and time-based tests (LEO-08)

Start each case from USB-confirmed STOPPED and restore temperature/gradients afterward:

1. At `speed 1`, request 25 °C from approximately 23 °C, START, sample measured/target at 1–5 s intervals, and record a temperature-vs-UTC CSV. Check direction, monotonicity within 0.01 °C, 2 °C/min nominal physical-time heating/cooling cap, then STOP.
2. Repeat after USB `speed 10`. The **thermal model** is faster; GUI dwell, telemetry deadlines and STOP verification remain on real wall-clock time.
3. Test heat then cool, boundary setpoint and gradients (up to 5.0 °C/min up, 3.5 °C/min down), finite values, and resumption only after a fresh verified STOP.
4. Check model freezing during STOP: leave 10–30 seconds stopped and ensure `actual_centi` does not advance.
5. Verify host-side timed profile validation rejects reach deadlines shorter than the advertised ramp time, even in accelerated thermal mode.
6. Check repeat phases and cancel behavior in host-based G06 regression. Live GUI profiles against Leonardo are **GATED** by section 12.

**Pass:** quantized temperature transitions as documented, wall-clock dwell unchanged, no motion while stopped, target/actual/source timestamps recorded. Leonardo has only its basic deterministic thermal model: no ESP32 inertia/noise parity claim.

## 9. Fault injection and independent recovery (LEO-09)

Fault injection is **USB `Serial` or local 5 V `Serial1` only**, never TCP; one active scenario at a time. Reopen the serial console, send the exact command, then **close it** before a Python driver check. Always send `fault clear` afterward; if the model is still RUNNING, ensure a *verified* STOP or reboot the emulator. Save USB console, driver exception and readback.

| USB command | Probe | Required observed result |
|---|---|---|
| `fault timeout` | Read-only serial/temperature driver request | Bounded timeout; no fake GOOD telemetry |
| `fault partial` | Read-only query | Invalid/incomplete frame rejected, no cached success |
| `fault invalid_sensor` | Temperature query | ERROR/UNKNOWN; cannot claim valid measured temperature |
| `fault delay 1500` | Read with driver timeout shorter than 1.5 s | Finite timeout; no hanging session |
| `fault alarm` | Provisional `10012` status test | `ALARM` response **only where status 10012 is actually consumed**; do not assume GUI already maps this |
| `fault freeze` | Controlled running thermal test | Measured temperature stops changing; G06 must fail by its reach/stale-progress deadline |
| `fault runaway_heat` / `fault runaway_cool` | Controlled short simulated run with approved envelope | Observable abnormal trend; controller should refuse/stop at configured envelope |
| `fault sticky_stop` | Controlled STOP while simulated RUNNING | Device does **not** stop despite ACK; readback must refuse success (NO-GO) |
| `fault drop_stop` | Controlled STOP while simulated RUNNING | Reply lost → driver reports STOP not verified, regardless of actual internal state (UNKNOWN) |
| `fault reset` | Single read-only TCP request | Deliberate watchdog reboot; USB returns with RUN=0 and matching persisted identity |
| `fault clear` | Clear transient fault | Normal driver read-only and clean verified STOP recover |

**Order:** exercise read-only faults first; destructive/ambiguous STOP faults last and **one at a time**. For sticky STOP or dropped STOP ACK, use an independently verified recovery path rather than retrying blindly. A controlled power cycle is safe for the Leonardo *emulator*, not a safe-shutdown proof for a real chamber.

**Important:** `fault reset` uses a deliberate 15 ms watchdog reboot path, **not** a demonstrated 8-second stalled-loop WDT recovery. The latter requires a separately reviewed hardware stall-injection method, stack/headroom measurement and reset-cause evidence; otherwise record **NOT RUN**.

## 10. Ethernet, multiple clients, DHCP, EEPROM and reboot (LEO-10)

1. **Link flap:** with device STOPPED, disconnect only the isolated RJ45 cable; capture `link=0` and TCP failure. Reattach; capture `link=1` and successful direct-IP discovery/reconnect. Neither lost link nor lost TCP reply may be labeled STOPPED without readback.
2. **Client replacement:** open one client, open another; confirm no phantom dual ownership and stale client closure. Check fresh identity on reconnect.
3. **No-DHCP fallback:** on the isolated no-DHCP segment, reboot and verify `192.168.42.42/24` on USB; re-run LEO-05.
4. **DHCP:** on a separate isolated test DHCP server (no real LAN), send `net dhcp`, reboot, record assigned RFC1918 address, gateway and lease renewal while STOPPED. Never silently reuse the fallback IP when DHCP succeeded.
5. **Static EEPROM:** after STOP, send `net static 192.168.42.42 255.255.255.0 0.0.0.0 0.0.0.0`; the board reboots. Verify USB/TCP, unplug/replug USB, repeat. Then test `identity serial SIMLEO0002` and `net mac 2`, recording the changed expected identity and last MAC byte. The existing read-only verifier with the **old** serial must fail; update expected values only after independent USB confirmation.
6. **Reset defaults:** `eeprom reset` after all persistence tests, then confirm `SIMLEO0001`, MAC final byte 1, DHCP mode/fallback and RUN=0. Re-run LEO-05. No forced EEPROM corruption or power cut during EEPROM writes without separate review.
7. **Recovery soak:** repeat 10–20 STOPPED link flaps and reboots (not rapid unsafe power cycling), checking USB `status`, driver discovery, no memory-related resets, and bounded response time. Record each attempt rather than an aggregate PASS.
8. **Resource pressure:** repeat 100+ read-only driver queries, disconnect and reconnect clients, and capture free SRAM/high-water mark if instrumented. Compiler-reported static SRAM free alone does **not** measure stack safety.

**Pass:** stable identity/network when saved, stale clients disconnected, TCP returns after link restoration, reboot starts STOPPED, no real network connected. A forced reboot while simulated RUNNING must cause host G04 to treat session as uncertain until re-verified.

## 11. GUI software-only regression and browser test (LEO-11)

This is the **safe** way to test the whole NiceGUI feature set before simulator enrollment. Do not set `CHAMBER_HIL_*` for this phase. Install GUI test dependencies separately:

```bash
python -m pip install -r requirements-web.txt \
  pytest==9.1.1 pytest-asyncio==1.4.0 playwright==1.58.0
# Playwright 1.58.0 Chromium is supported by the project's Ubuntu 24.04 CI.
python -m playwright install --with-deps chromium

python scripts/h02_watchdog_command.py --timeout-s 900 --idle-timeout-s 180 \
  --log-dir test-evidence/leonardo/campaign-01/gui-regression -- \
  python -m pytest -v tests/test_h01_simulation.py \
    tests/test_profile_runner.py tests/test_profile_execution_service.py \
    tests/test_run_recording.py tests/test_profile_security_integration.py

python scripts/h02_watchdog_command.py --timeout-s 900 --idle-timeout-s 180 \
  --log-dir test-evidence/leonardo/campaign-01/browser -- \
  python -m pytest -v -s tests/test_h01_browser_e2e.py
```

Interactive browser checklist (localhost simulation only): create/change admin credentials, test Operator/Viewer roles, dashboard and status cards, verify Start → STOP → Start workflow (only after verified STOP rearm), manual temperature limits, profile editor validation/import/save/versioning, draft vs approved states where available, profile Start/Pause/Resume/Cancel/STOP, disconnect/reconnect, G07 samples/events/export, session expiry/CSRF and recovery from simulated network faults. Record screenshots, browser version, console errors and matching server logs. Never infer emulator-specific coverage from a simulated GUI PASS.

If the Windows/Playwright browser job is unavailable on the host, use the project CI artifacts and mark manual browser coverage **NOT RUN**; do not substitute screenshots as proof of the full automated suite.

## 12. Live NiceGUI → Leonardo end-to-end test (LEO-12 — GATED)

**Current gate: BLOCKED / DO NOT ACTIVATE.** The network emulator has no cryptographic identity attestation or reviewed simulator-only enrollment. The production GUI currently classifies a network driver connection as **physical**, not as a trusted mock. Neither changing the serial to a `SIM` prefix nor setting `CHAMBER_LAB_MODE` makes it trusted simulation.

Allowed today: from a localhost-mode GUI in simulation, the administrator may use **Settings → Chamber configuration → Auto-detect chambers** for a **read-only driver-owned** probe of `192.168.42.42` or the isolated `192.168.42.0/24`. Observe model, serial, IP, timeout and failure diagnostics. **Do not save an active physical connection or begin control** on the strength of that discovery alone.

**Only after independent approval** of the simulator enrollment/isolation procedure and HIL admission contract, run the following in order using the normal NiceGUI → `VotschBackend` → pinned external driver path (never a second GUI TCP implementation):

1. Validate out-of-band USB identity, firmware SHA, no shared network route, verified RUN=0, and a finite narrow test envelope (for example 22–28 °C).
2. For a real-chamber physical path, obtain the locally operator-issued 24-hour HIL PIN using `bash scripts/hil_pin.sh setup` and the serialized `bash scripts/hil_pin.sh run --` entrypoint. Existing H02 supervised production permits are **separate** and must not be bypassed. The signed Leonardo bench-emulator path uses `scripts/emulator_bench_check.py` and `scripts/emulator_profile_check.py` without a HIL PIN. Follow `docs/HIL_PIN_RUNBOOK.md` for real-chamber testing and [EMULATOR_ENROLLMENT.md](EMULATOR_ENROLLMENT.md) for the simulator.
3. Start the approved isolated test configuration under G04/G08 authentication, preserving strict expected serial, ownership, stop fence and driver-only communication. Record every configuration key except secrets.
4. Browser **Settings:** read-only discovery, explicit selection, verify serial/IP and save; require a restart if the configuration path specifies it.
5. Browser **Dashboard/Manual:** show model/IP/serial and GOOD telemetry; claim the lease; set 24 °C; START, monitor, STOP; verify STOPPED; rearm and START again. Test another user's lease conflict and stale session.
6. Browser **Profiles:** create/save exact revision of a 24→26→23 °C profile, set realistic ramp/reach/dwell windows; run, stop, cancel during reaching, retry only after fresh STOP; reject out-of-envelope setpoints/gradients/unsupported outputs.
7. Browser **G07:** capture immutable revision, intended target, measured temperature, source timestamp, run ID, events, samples, reason/terminal state; export and verify files/checksums and graph extrema. Verify no unauthorized history or cross-chamber access.
8. Browser **fault/recovery:** inject each fault using **USB**, not browser; check UNKNOWN/FAULT fencing, no automatic restart, audit trail, manual operator reauthorization after readback, and no loss of evidence. Never falsely PASS dropped STOP acknowledgements.
9. **Acceptance runner** (only if separately approved): start with `--plan-only`, use the approved PIN/bench lock and exact isolated lab configuration. Prefer narrow targets, short dwell and finite internal deadlines; first test `identity,guards`, then add `manual,cancel,profile,gradient,web` separately. Restore original setpoint/gradients and verify RUN=0 independently.

The existing `scripts/hil_lab_acceptance.py` runner is **not** a shortcut around simulator enrollment. It targets a physical authorization and requires `CHAMBER_HIL_*`, `CHAMBER_LAB_MODE=ISOLATED-LAB-UNATTENDED` and the HIL PIN; it does not establish device attestation. Do not execute it on Leonardo before the gate above is approved.

**Pass only if:** the enrollment gate is documented, every selected test result and artifact matches the physical USB-verified emulator, G04/G08/G06 safety policies remain unchanged, and no real chamber is involved.

## 13. W02, security, cross-platform and release separation (LEO-13)

- **G08:** verify admin/operator/viewer permissions, login/session revocation, CSRF on every mutation, protected settings, audit integrity, lost-password recovery, backup/restore and read-only discovery authorization. Use existing security automated suites on Windows/Linux; physical Leonardo is only needed for approved network tests.
- **W02:** build the reviewed Windows wheelhouse/installer from committed lock and SHA-256 manifest, run self-test on a disconnected clean Windows system, check restart persistence and no external downloads. Verify the final artifact, **not** merely `pio firmware.hex`.
- **Emulator firmware:** source, board/SD/ICSP inspection, AVR memory headroom, final firmware hash, USB/EEPROM/TCP and watchdog evidence.
- **Release:** real-device H01/H02, independent safety/security review, signed publisher artifact/site approval, and R01 are outside the Leonardo emulator's authority.

## 14. Evidence tree, result notation, acceptance sign-off

```text
test-evidence/leonardo/campaign-01/
  start-utc.txt
  gui-commit.txt                 driver-commit.txt
  firmware-sha256.txt            build/   flash/
  wiring/                        network/
  native-golden/                 native-driver/
  board-readonly.json            board-readonly-watchdog/
  board-control.json             board-control-watchdog/
  usb-serial.log                 tcp-pcap.pcapng
  thermal.csv                    fault-cases/
  link-flaps.csv                 eeprom-reboot.csv
  gui-regression/                browser/
  screenshots/                   run-journal/
  test-matrix.csv                summary.md
```

Create `test-matrix.csv` with columns `case_id,status,start_utc,finish_utc,firmware_sha,gui_sha,driver_sha,expected,observed,evidence_path,reviewer,notes`. Valid statuses: **PASS, FAIL, SKIP (reason), NOT RUN, BLOCKED**. An automated CI PASS is **not** a physical-board PASS. Keep all raw logs and timestamps. Redact PINs, admin passwords, tokens, network secrets, and private keys.

| Gate | Evidence required for PASS | Initial status |
|---|---|---|
| LEO-00–02 | Isolation, wiring, original source, native golden + driver TCP, exact AVR hex/hash, flash/stack headroom, actual USB flash | NOT RUN on board |
| LEO-03–06 | USB/TCP identity, discovery, read-only and 3 Start/Stop cycles, final STOPPED | NOT RUN |
| LEO-07–08 | Device control/limits/gradients/outputs and measured thermal CSV + wall-clock time | NOT RUN |
| LEO-09 | Per-fault refusal, UNKNOWN/FAULT semantics, independently checked recovery | NOT RUN |
| LEO-10 | DHCP/fallback/static, EEPROM persistence, cable flaps, reconnect, long-running stability | NOT RUN |
| LEO-11 | In-process GUI/browser regression across roles, profiles and recording | NOT RUN in this campaign |
| LEO-12 | Approved secure simulator enrollment + real GUI/driver integration | BLOCKED |
| LEO-13 | W02, G08 independent/security/site release evidence | OPEN, separate |
| Real chamber H01/H02/R01 | Qualified physical chamber tests and site signatures | NOT COVERED BY EMULATOR |

Final operator checklist: **Leonardo RUN=0, no TCP client left, USB fault state cleared, test network detached, configuration returned to defaults or documented state, all evidence checksummed, zero real-chamber I/O, reviewer disposition recorded.**

**Stop rule:** any failed safety, STOP, identity or hardware recovery gate prevents merge or a claim of full HIL success. For an open issue, attach the exact file, line, firmware revision, reproduction steps and observed vs expected behavior; use short finite software watchdogs, and never mark an unrun physical gate PASS.

## 15. References and issue links

- [Leonardo firmware and wiring](LEONARDO_W5500_CHAMBER_EMULATOR.md)
- [Leonardo hardware acceptance ledger](LEONARDO_W5500_CHAMBER_ACCEPTANCE.md)
- [ESP32 emulator protocol](ESP32_ETH01_EMULATOR_PROTOCOL.md)
- [GUI automatic discovery](CHAMBER_DISCOVERY.md)
- [24-hour operator PIN / real HIL entrypoint](HIL_PIN_RUNBOOK.md)
- [Isolated lab application policy](../README_LAB.md)
- [Full chamber execution tracker](CHAMBER_EXECUTION_TRACKER.md)
- [Leonardo integration draft PR #88](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/88)
- [ESP32 prerequisite draft PR #84](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/84)
- [Open Leonardo acceptance issue #96](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/issues/96)
