# Arduino Leonardo R3 + W5500 chamber emulator

**Status: engineering firmware variant, hardware NOT tested.** Tracked in the
GUI repository, stacked on ESP-EMU-01 / PR #84. This is NOT the UPS HID sketch.
It uses the **same physical board and shield** as
[USB-UPS-Simulator](https://github.com/ami3go/USB-UPS-Simulator), but emits
S!MPAC / SimServ frames on **TCP/2049** for the separate
[Vötsch Python driver](https://github.com/ami3go/VotschTechnik-climate-chamber-Python).
Nothing in NiceGUI bypasses the normal external driver or physical-HIL gate.

## 1. Hardware wiring and resource constraints

| Function | Leonardo / shield | Notes |
| --- | --- | --- |
| MCU | Arduino Leonardo R3 / ATmega32U4 | 16 MHz, 32 KB flash (28,672 usable with bootloader), 2,560 bytes SRAM |
| Ethernet | W5500 Shield V2.0 | The UNO-form shield MUST carry working 2×3 ICSP SPI socket |
| SPI MOSI/MISO/SCK | Leonardo **ICSP header** | UNO D11/D12/D13-only shields incompatible |
| W5500 Ethernet CS | **D10** | Reserved |
| microSD CS | **D4**, OUTPUT HIGH | Do not use SD during first tests |
| Administration | Native USB CDC `Serial` 115200 | Leonardo's USB can disconnect/re-enumerate on reset |
| Optional admin | D0 RX / D1 TX `Serial1` 115200 | Logic-level-compatible 5 V UART, TX/RX crossed; common GND |
| LED | LED_BUILTIN | Main-loop heartbeat, no additional shield GPIO use |
| Input power | Leonardo USB 5 V | Verify clone USB/shield current budget, no separate voltage injection |

Before stacking, **power down**. Confirm W5500 board marking, populated ICSP
socket mating, pin alignment, 5 V power/logic compatibility, RJ45 and SD-CS.
Original UPS project used a locally administered MAC **02:55:50:53:00:01**.
This variant uses **02:56:4F:54:43:01**, configurable last byte via USB/UART
`net mac N`. Do not connect simultaneous emulators with duplicate MAC/IP.

The ATmega32U4's small RAM makes the ESP32 `std::string` /
`std::vector` protocol engine inappropriate. Leonardo uses a separate
strict fixed-buffer command implementation with matching driver wire behavior,
a single TCP client, 80-byte maximum request and 64-byte maximum reply.
Strings/JSON/heap allocation are not used in the command hot path.
CLI/EEPROM configuration is separate from the chamber TCP protocol.

## 2. Firmware compilation and flashing

Toolchain pinned in
`firmware/esp32_eth01_chamber_emulator/platformio.ini`:

- PlatformIO Core **6.1.18** (install with `pip`);
- `atmelavr@5.1.0`, board `leonardo`, Arduino AVR framework;
- Arduino `Ethernet@2.0.2` using the W5500.

From repository root on Linux or Windows:

```sh
python -m pip install platformio==6.1.18
pio run -d firmware/esp32_eth01_chamber_emulator -e leonardo-w5500
pio run -d firmware/esp32_eth01_chamber_emulator -e leonardo-w5500 -t upload --upload-port <PORT>
pio device monitor --baud 115200 --port <PORT>
```

On Linux, `<PORT>` is usually `/dev/ttyACM0`; Windows uses a COM port.
The Caterina bootloader briefly changes its USB port when uploading or
resetting. If upload fails, press Leonardo RESET, redetect the bootloader
port, close the serial monitor and retry. PlatformIO does not erase the
EEPROM by default; `eeprom reset` on the console resets configuration.
`firmware.hex` and its SHA-256 are emitted by CI when build passes. Do not
guess the checksum from a source commit without building it.

## 3. Network startup and persistence

Ethernet is the **only** network interface. Default: DHCP attempt (10 s
overall, 2 s response bound). On failure, the chamber fallback is
**192.168.42.42/24** with no gateway or DNS; attach the isolated test
computer to the same subnet and use the driver's normal TCP discovery.
This deliberately differs from the UPS simulator's **169.254.42.42/16**:
the current Vötsch Python discovery rejects link-local addresses and
accepts only RFC1918 IPv4.

The local console can persist a unique alphanumeric serial (max 16 chars),
MAC final byte, and static IPv4/subnet/gateway/DNS in EEPROM with an
integrity check. Invalid/corrupt EEPROM uses factory defaults; valid static
settings are applied after reboot. In DHCP mode, lease maintenance occurs
only while STOPPED to avoid blocking an active simulated ramp. Link
reconnection is handled by W5500 link detection and server reinitialization,
but physical reconnect reliability remains unverified.

## 4. USB Serial / Serial1 local administration

```text
status
help
speed 1
speed 10
fault sticky_stop
fault drop_stop
fault timeout
fault partial
fault invalid_sensor
fault freeze
fault alarm
fault runaway_heat
fault runaway_cool
fault reset
fault delay 500
fault clear
identity serial SIMLEO0002
net dhcp
net static 192.168.1.204 255.255.255.0 192.168.1.1 192.168.1.1
net mac 2
eeprom reset
```

Only UART/USB has fault-management commands. Do not expose Serial1 to an
untrusted remote serial server. Factory reset erases the emulator's
configured identity/network settings but does NOT authorize any real
chamber connection.

## 5. S!MPAC behavior

Same byte grammar as the ESP32 and Python driver:

```text
GET SERIAL  99997 B6 1 B6 3 0D
REPLY       1 B6 SIMLEO0001 0D
START       14001 B6 1 B6 1 B6 1 0D -> 1 0D
STOP        14001 B6 1 B6 1 B6 0 0D -> 1 0D
STOP STATE  14003 B6 1 B6 1 0D -> 1 B6 0 0D
```

`B6` is **one literal byte 0xB6**, NOT the UTF-8 `C2 B6`.
Success is `1\r` or `1\xB6<value>\r`; error is `0\xB6<error>\r`.
Command coverage mirrors the ESP32 prototype: chamber info/status,
temperature setpoint/actual, control-variable metadata/limits,
digital output 1/7/8 read/write, gradients and repeated Start/Stop.
Unsupported or malformed commands fail explicitly. Chamber status
`10012` is **provisional** (unverified against physical controller).
No vendor program-management commands are implemented.

Temperatures/rates are represented as integer centidegrees (0.01 °C
resolution), printed with three decimals; Basic deterministic rate-limited
thermal behavior is default (23 °C ambient, heating/cooling 2 °C/min),
`speed 10` accelerates only the thermal model. **No Realistic
inertia/noise** on this memory-limited AVR variant. GUI dwell
and watchdog remain real wall-clock durations.

STOP is positively verified by the existing driver's digital output 1
readback. A lost STOP acknowledgement remains UNKNOWN even if a simulated
state transition occurred, as on the ESP32 prototype. Reboot starts STOPPED.
8 s AVR main-loop watchdog protects against a stalled loop; actual
network/WDT fault recovery is not yet hardware qualified.

## 6. Physical-board verification (opt-in only)

Use the maintained Python driver, `pyserial==3.5`, the actual Leonardo
USB CDC serial port, and an independently isolated Ethernet test subnet.
This checks live **USB-CDC identity before TCP**, not merely a self-reported
network serial. Example for Linux, from repository root:

```sh
export LEONARDO_EMULATOR_HARDWARE_OPT_IN=1
python scripts/h02_watchdog_command.py \
  --timeout-s 180 --idle-timeout-s 40 \
  --log-dir test-evidence/leonardo/hardware-watchdog -- \
  python firmware/esp32_eth01_chamber_emulator/test/hardware/verify_leonardo.py \
    --ip 192.168.42.42 --usb-port /dev/ttyACM0 --serial SIMLEO0001 \
    --ack-isolated-test-lan --ack-physical-usb
```

On Windows set the environment variable in PowerShell and use a `COM` port.
The script is read-only unless `--allow-writes` is explicitly supplied.
With that flag it performs only three verified Start/Stop cycles on the
operator-confirmed isolated emulator. A lost STOP acknowledgement produces
UNKNOWN and the test fails. All tests have watchdog, socket, and UART
deadlines. Do **not** run it against a real Vötsch chamber. It is not an
independently authenticated GUI enrollment mechanism.

## 7. Automated verification

The AVR and the host share the exact `leonardo_core.cpp` command engine.
Run native host golden tests and driver TCP interoperability with H02
watchdog bounds; CI also cross-compiles Leonardo and produces a firmware
`firmware.hex` artifact and checksum. Native TCP uses the unmodified
Python driver and a Linux reference server; it is **not** a hardware test.

The GPIO/IP, SRAM/flash build report, real W5500 connectivity, DHCP renewal,
repeated STOP, link recovery, watchdog reboot and NiceGUI browser behavior
must be verified on a purchased board. The HIL/release gate remains unchanged.

See [Leonardo acceptance](LEONARDO_W5500_CHAMBER_ACCEPTANCE.md).
