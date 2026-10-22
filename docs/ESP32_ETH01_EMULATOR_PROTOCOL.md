# ESP-EMU-01 S!MPAC wire protocol matrix

Authoritative executable baseline: external Python driver
`VotschTechnikClimateChamber/ClimateChamber.py`,
`transport.py`, `discovery.py`, commit
`b56cfbd54570e66cddf83106505487d3b19d9677`.

Wire grammar: `ASCII 5-digit cmd` + `B6` + `1` + zero to four
`B6<argument>` fields + `0D`; **B6 is one literal byte, NOT UTF-8**
(`C2 B6`). Every response ends `0D`. Success response is either
`31 0D` (no value) or `31 B6 <ASCII value> 0D`. Error response is
`30 B6 <ASCII reason> 0D`; the driver raises on the leading `0`.
Error reasons in this emulator are test-level conventions, not claimed
vendor error codes.

| Code | Driver call | Args after chamber index | Success value / effect |
| --- | --- | --- | --- |
| 99997 | GET CHAMBER INFO | 1/2/3 | model / year / alphanumeric serial |
| 10012 | GET CHAMBER STATUS | none | **provisional**, not driver certification |
| 11018 | GET CONTROL_VARIABLE NUMBER_OF | none | 1 |
| 11026 | GET CONTROL_VARIABLE NAME | 1 | Temperature |
| 11023 | GET CONTROL_VARIABLE UNIT | 1 | C |
| 11007, 11009 | GET CONTROL_VARIABLE INPUT_LIMIT_MIN/MAX | 1 | -40/180 |
| 11002 | GET CONTROL_VARIABLE SET_POINT | 1 | target °C |
| 11004 | GET CONTROL_VARIABLE ACTUAL_VALUE | 1 | measured °C |
| 11001 | SET CONTROL_VARIABLE SET_POINT | 1, float | success; -40..180 finite only |
| 14007 | GET DIGITAL_OUT NUMBER_OF | none | 8 |
| 14010 | GET DIGITAL_OUT NAME | 1/7/8 | Running/Compressed air/Dryer |
| 14003 | GET DIGITAL_OUT VALUE | 1/7/8 | 0 or 1 |
| 14001 | START MANUAL_MODE | 1, 0 or 1 | stop/start, immediate readback |
| 11066, 11070 | GET GRADIENT_UP/DOWN VALUE | 1 | rates °C/min |
| 11068, 11072 | SET GRADIENT_UP/DOWN VALUE | 1, float | finite 0.01..5/3.5 °C/min |

Examples in **hex**:

```text
GET SERIAL: 39 39 39 39 37 B6 31 B6 33 0D
REPLY:      31 B6 53 49 4D 45 53 50 30 30 30 31 0D
START:      31 34 30 30 31 B6 31 B6 31 B6 31 0D
STOP:       31 34 30 30 31 B6 31 B6 31 B6 30 0D
STOP ACK:   31 0D
STOP STATE:  31 34 30 30 33 B6 31 B6 31 0D -> 31 B6 30 0D
```

The first index after the command is always chamber index 1. This is distinct
from command argument 1 denoting control variable or output 1. Parser rejects
more than four arguments, invalid separator/CR, empty arguments, non-ASCII,
oversized frames and invalid indices. Unsupported commands explicitly reject.

**Missing:** program commands, message/alarm lists, most ancillary I/O,
physical firmware captures, certified semantics for 10012. Driver method
`dryer` and `compressed_air` setters use 14001 indexes 8/7; this
initial emulator deliberately does NOT implement those writes because command
14001 could alias manual mode. Must resolve with real driver/capture before
enabling them rather than generating an unsafe success.
