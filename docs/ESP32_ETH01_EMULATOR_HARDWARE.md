# ESP-EMU-01 Hardware and flashing guide

**Target:** original WT32-ETH01 / LAN8720 reference layout, NOT ETH01-EVO.
**Status:** reference schematic checked; *purchased board not inspected*.
Do not flash a different revision until silkscreen, oscillator topology, PHY
address, regulator, flash marking, supply voltage and GPIO header are verified.
PlatformIO documents a 4 MB flash target; confirm actual fitted flash.

Primary references:

- Manufacturer datasheet and schematic: https://wiki.wireless-tag.com/docs/en/WT32-ETH01/board_resources.html
- PlatformIO target: https://docs.platformio.org/en/stable/boards/espressif32/wt32-eth01.html
- Pin/PHY investigation: https://github.com/egnor/wt32-eth01

## Reference signals (verify against physical module)

| Signal | ESP32 / board expectation | Rule |
| --- | --- | --- |
| RMII MDC | GPIO23 | PHY only |
| RMII MDIO | GPIO18 | PHY only |
| LAN8720 address | 1 | verify with schematic |
| External PHY 50 MHz oscillator input | GPIO0 | strapping pin; do not drive externally except boot mode |
| Oscillator enable | GPIO16 | reserved; not a freely available LED |
| Programming UART0 TX | GPIO1 / TX0 | 3.3 V logic |
| Programming UART0 RX | GPIO3 / RX0 | 3.3 V logic |
| ESP32 enable | EN | low pulse to reset; not a 5 V input |
| UART boot mode | GPIO0 held low at reset | release after entering bootloader |
| Supply | board-marked 5 V input **or** regulated 3.3 V input | never connect both at once; validate actual regulator |
| Ethernet | RJ45 / LAN8720 | isolation magnetics per board design |

Do not assign status LEDs/buttons to unverified GPIO, especially GPIO0/2/4/5/
12/15 strapping pins or GPIO6..11 flash signals. ESP32 output GPIOs are not
5 V tolerant. Avoid GPIOs consumed by RMII, PHY power and UART diagnostics.

## Functional wiring sketch (not a physical footprint drawing)

```text
 PC / USB-to-UART adapter (TTL 3.3 V)       WT32-ETH01 (verify labels)
 ───────────────────────────────────────────────────────────────
 TXD -------------------------------------> RX0 / ESP GPIO3
 RXD <------------------------------------- TX0 / ESP GPIO1
 GND -------------------------------------- GND
                                           EN ---- reset pushbutton ---- GND
                                           GPIO0 - BOOT pushbutton ----- GND

 Independent regulated power supply        Board's selected power INPUT
 +5V (ONLY if board input marked 5 V) ----> 5V
 GND -------------------------------------- GND
      [OR: board-verified regulated 3.3 V to its 3V3 input, not both]

 Ethernet switch / direct test LAN  <------ RJ45
 ```

BOM: one verified original WT32-ETH01 LAN8720 board; one reputable USB-UART
adapter with measured 3.3 V TX/RX logic (CP2102/FT232-class); one regulated
supply rated at least 500 mA peak **at the selected board supply voltage**;
two momentary switches for EN/GPIO0 (optional jumper equivalent); jumpers,
pin labels, insulated enclosure, Ethernet cable and an isolated test switch.
Do not assume the serial adapter's weak 3.3 V output can power the ESP32.
Do not assume the board has native USB, PoE or user LED.

Measure supply under link negotiation/transmit load, including brownout margin.
Inspect cable strain relief and prevent accidental shorting of exposed pins.
Use a separate, labeled isolated test VLAN/LAN for the emulator.

## Flash and recovery (Windows and Linux)

1. With power OFF cross TX/RX, connect GND and the verified regulated supply.
2. Pull GPIO0 to GND, pulse EN low and release EN; then release GPIO0.
3. Connect UART adapter; identify COM port in Windows or `/dev/ttyUSB*` Linux.
   Linux may require dialout/udev privileges. Never use 5 V UART logic.
4. `python -m pip install platformio==6.1.18`.
5. From repository root `pio run -d firmware/esp32_eth01_chamber_emulator`.
6. Flash: `pio run -d firmware/esp32_eth01_chamber_emulator -t upload --upload-port <PORT>`.
7. Monitor: `pio device monitor -b 115200 --port <PORT>`.
8. Record firmware version, MAC/IP, flash marking, SHA256 and reset reason.
9. On failed flashing, disconnect high-risk circuitry, check power/ground,
   re-enter GPIO0/EN boot mode and reflash; full erase only when intended:
   `pio run -d firmware/esp32_eth01_chamber_emulator -t erase --upload-port <PORT>`.
   **Erase destroys NVS identity and static network settings.**
10. If static IP is inaccessible, use UART `net dhcp` or `nvs reset`.

NVS backup policy: record `status`, configured serial and `net static`
values in a controlled local note before erasure. No automatic extraction of
NVS, no credentials, no OTA. Firmware always boots STOPPED and fault-free.

The board pinout is a reference only; **physical marking/revision and exact
voltage/current checks are still NOT VERIFIED.**
