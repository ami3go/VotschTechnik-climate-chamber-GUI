# ESP-EMU-01 — WT32-ETH01 S!MPAC network chamber emulator

**Status: engineering prototype; no physical board was available for verification.** The
C++ command engine is shared verbatim between ESP32 firmware and a Linux TCP
reference process. Its normal TCP service is 2049; no Wi-Fi, OTA or web admin.

This test endpoint is NOT a physical chamber, is NOT HIL certification evidence,
and does NOT authorize network-emulator activation in NiceGUI. The application
remains unchanged until independent simulator attestation/enrollment is approved.

## Build / test

Install PlatformIO Core **6.1.18** and from this repository root run:

```shell
pio run -d firmware/esp32_eth01_chamber_emulator
sha256sum firmware/esp32_eth01_chamber_emulator/.pio/build/wt32-eth01/firmware.bin
```

A first build requires internet for pinned PlatformIO packages; the running
firmware does not. For local host testing, compile the exact same command engine:

```shell
d=firmware/esp32_eth01_chamber_emulator
mkdir -p "$d/build"
g++ -std=c++17 -Wall -Wextra -Werror -I"$d/include" "$d/src/emulator_protocol.cpp" "$d/test/host/test_emulator.cpp" -o "$d/build/test_emulator"
g++ -std=c++17 -Wall -Wextra -Werror -I"$d/include" "$d/src/emulator_protocol.cpp" "$d/test/host/tcp_reference.cpp" -o "$d/build/tcp_reference"
python scripts/h02_watchdog_command.py --timeout-s 120 --idle-timeout-s 60 --log-dir test-evidence/esp32-emulator -- "$d/build/test_emulator"
```

The driver integration suite requires an external driver checkout in
`external-driver/` at
`b56cfbd54570e66cddf83106505487d3b19d9677`.
It is tested against real TCP, not a monkeypatched driver transport.

## UART console

3.3 V TTL only, 115200 8N1, local physical access. Commands:

```text
help
status
speed 10
fault sticky_stop
fault drop_stop
fault timeout
fault partial
fault invalid_sensor
fault freeze
fault alarm
fault reset
fault delay 500
fault clear
identity serial SIMESP0002
net dhcp
net static 192.168.1.200 255.255.255.0 192.168.1.1 192.168.1.1
nvs reset
```

Fault injection is volatile and disabled on every reboot. Changing network mode
reboots STOPPED. Static settings and serial are persistent in NVS; thermal state,
profile state and fault flags are NOT. Admin UART must not be exposed remotely.

The basic temperature model advances against monotonic `millis()`; speed
changes only thermal progression, not GUI wall-clock dwell. Current firmware
implements basic and accelerated modes; realistic inertia/noise are future scope.
See documentation under `docs/ESP32_ETH01_EMULATOR_*.md`.

## Unimplemented and provisional

`GET CHAMBER STATUS` (10012) has a provisional RUNNING/STOPPED/ALARM
representation; physical golden capture is required before labeling it conformant.
Only commands listed in the protocol matrix are implemented. No program-mode
commands, full error-message model, UDP discovery, GPIO LED, web admin, OTA or
cryptographic emulator attestation. GUI activation remains prohibited.
