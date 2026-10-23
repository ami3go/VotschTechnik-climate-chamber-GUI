"""VT 4011-like stand-in for ``VotschTechnikClimateChamber.ClimateChamber``.

Same attribute surface as the pinned driver, so it plugs into
``VotschBackend(hil_driver_factory=...)`` and exercises the real adapter, G04
controller, G05 manual control and G06 profile runner without a chamber:

* the 11002 setpoint readback ramps from its previous value to a new target
  at the chamber gradient (as observed on the VT 4011);
* gradient setters enforce the driver's 0.01..5 (up) / 0.01..3.5 (down) limits;
* measured air temperature follows the ramped setpoint with a first-order lag
  while running and drifts back toward ambient while stopped;
* ``offline = True`` makes every access raise like a lost TCP connection.

Not a physical model of any certified chamber; for script and CI validation.
"""
from __future__ import annotations

import math
import threading
import time


class SimulatedVT4011:
    def __init__(self, *, serial: str = "SIM4011", ambient_c: float = 23.0,
                 gradient_up: float = 5.0, gradient_down: float = 3.0,
                 tau_s: float = 120.0, ambient_tau_s: float = 900.0,
                 limits_c: tuple[float, float] = (-45.0, 135.0)):
        self.serial_number = serial
        self.test_system_type = "VT 4011 (simulated)"
        self._lock = threading.RLock()
        self._ambient = float(ambient_c)
        self._measured = float(ambient_c)
        self._gradients = [float(gradient_up), float(gradient_down)]
        self._tau = float(tau_s)
        self._ambient_tau = float(ambient_tau_s)
        self._limits = limits_c
        self._ramp_from = self._goal = float(ambient_c)
        self._ramp_t0 = self._t = time.monotonic()
        self._running = False
        self.offline = False
        self.calls: list[tuple] = []

    # -- physics -------------------------------------------------------------
    def _readback(self, now: float) -> float:
        delta = self._goal - self._ramp_from
        rate = self._gradients[0] if delta > 0 else self._gradients[1]
        moved = rate / 60.0 * (now - self._ramp_t0)
        return self._goal if abs(delta) <= moved else self._ramp_from + math.copysign(moved, delta)

    def _advance(self) -> None:
        now = time.monotonic()
        # Integrate in small steps so the lag follows the moving setpoint.
        while self._t < now:
            dt = min(0.5, now - self._t)
            self._t += dt
            goal, tau = ((self._readback(self._t), self._tau) if self._running
                         else (self._ambient, self._ambient_tau))
            self._measured += (goal - self._measured) * (1 - math.exp(-dt / tau))

    def _online(self) -> None:
        if self.offline:
            raise ConnectionError("Simulated chamber connection lost")

    # -- driver surface ------------------------------------------------------
    @property
    def temperature_measured(self) -> float:
        with self._lock:
            self._online()
            self._advance()
            return round(self._measured, 2)

    @property
    def temperature_set_point(self) -> float:
        with self._lock:
            self._online()
            return round(self._readback(time.monotonic()), 3)

    @temperature_set_point.setter
    def temperature_set_point(self, celsius: float) -> None:
        with self._lock:
            self._online()
            celsius = float(celsius)
            if not self._limits[0] <= celsius <= self._limits[1]:
                raise ValueError("Simulated chamber setpoint outside its limits")
            self._advance()
            now = time.monotonic()
            self._ramp_from, self._ramp_t0, self._goal = self._readback(now), now, celsius
            self.calls.append(("set", celsius))

    def _set_gradient(self, index: int, value: float, maximum: float) -> None:
        with self._lock:
            self._online()
            value = float(value)
            if not 0.01 <= value <= maximum:
                raise ValueError("Simulated gradient outside driver limits")
            self._advance()
            now = time.monotonic()
            # A new gradient applies to the remaining ramp from where it is now.
            self._ramp_from, self._ramp_t0 = self._readback(now), now
            self._gradients[index] = value
            self.calls.append(("gradient_up" if index == 0 else "gradient_down", value))

    @property
    def gradient_up(self) -> float:
        with self._lock:
            self._online()
            return self._gradients[0]

    @gradient_up.setter
    def gradient_up(self, value: float) -> None:
        self._set_gradient(0, value, 5.0)

    @property
    def gradient_down(self) -> float:
        with self._lock:
            self._online()
            return self._gradients[1]

    @gradient_down.setter
    def gradient_down(self, value: float) -> None:
        self._set_gradient(1, value, 3.5)

    @property
    def is_running(self) -> bool:
        with self._lock:
            self._online()
            return self._running

    def start(self) -> None:
        with self._lock:
            self._online()
            self._advance()
            self._running = True
            self.calls.append(("start",))

    def stop(self, verify_timeout: float = 3.0) -> None:
        with self._lock:
            self._online()
            self._advance()
            self._running = False
            self.calls.append(("stop",))

    def query(self, command: str, *args):
        with self._lock:
            self._online()
            if command == "GET DIGITAL_OUT VALUE" and args == (1,):
                return ["1" if self._running else "0"]
            raise RuntimeError("Command not simulated: " + command)

    def disconnect(self) -> None:
        # One shared simulated chamber outlives every "connection" to it.
        self.calls.append(("disconnect",))
