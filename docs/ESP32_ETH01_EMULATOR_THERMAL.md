# ESP-EMU-01 thermal model specification

Implementation: `firmware/esp32_eth01_chamber_emulator/src/emulator_protocol.cpp`.
All temperatures are °C and rates °C/min. This engine uses an explicit
`advance(dt_seconds)` step, independent of wall-clock scheduling, so host
golden tests use fixed monotonic elapsed times without sleeps. Firmware calls
`advance` using wrap-safe elapsed `millis()` values. Invalid or extreme
steps (non-finite, <=0 or >3600 seconds) are rejected.

## Basic (default)

On reboot, STOPPED, actual = ambient = 23 °C, target = 23 °C, heating and
cooling = 2 °C/min; limits = -40..180 °C; simulation speed = 1.0.
When RUNNING choose the rate by the sign of (target - actual):

`movement = rate_c_per_min * dt_seconds * simulation_speed / 60`

Advance toward target by at most `movement`; clamp at target with no
overshoot. Setpoint and rate writes require finite values; min/max setpoint
and asymmetrical rate limits are enforced by command handler. STOP freezes
temperature by default; optional passive relaxation at 0.2 °C/min moves
toward ambient without changing RUNNING. This is *not* a physics model.

## Realistic

UART `mode realistic`. Rate responds to the commanded signed rate through
a first-order lag, with configurable `inertia_seconds` = 1..300 (default
20 seconds):

`alpha = 1 - exp(-dt_seconds / inertia_seconds)`

`v_next = v_old + alpha * (signed_command_rate - v_old)`

`movement = max(0, sign(target - actual) * v_next) * dt_seconds / 60`

The movement is clamped at target. This provides a bounded response delay
and asymmetrical heating/cooling rates without unstable overshoot. The
velocity state is reset upon STOP, mode switch or arrival at target.
Nonzero configurable UART `noise <amplitude>` (0..1 °C) applies bounded
deterministic xorshift pseudo-noise to **measured readback only**, leaving
the simulated thermal state unchanged. Default noise amplitude is 0.

The model is intentionally reduced-order; it does not claim to emulate
manufacturer thermal accuracy, fan behavior, load-dependent gradients, or
true sensor dynamics.

## Accelerated

UART `mode accelerated` sets thermal speed to 10x (adjustable 0.1..100x
using `speed N`). This modifies physical-state progression only; Python
controller/profile dwell and watchdog timing remain **real wall time** and
must never be silently shortened.

## Faults and boundaries

`fault freeze` holds actual temperature. `fault runaway_heat` and
`fault runaway_cool` drive the measured thermal state at +/-15 °C/min
while running, independent of the target, clamped to -60..200 °C;
these explicitly simulate an abnormal condition and intentionally permit
departure from target. `fault invalid_sensor` rejects the actual-value
query. Local UART `fault clear` restores healthy behavior. All faults and
mode settings revert to Basic/healthy at reboot.

No simulated temperature response is evidence of calibration, hardware
temperature capability, STOP physical effectiveness or site HIL approval.
