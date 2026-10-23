"""ONLY GUI module permitted to import the externally maintained Vötsch driver.

Physical I/O is disabled unless an explicit launch-time ``HilAuthorization``
is supplied (see ``chamber_web.hil.physical``). Mock-factory instances exercise
protocol mapping without opening chamber connections.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Callable

from chamber_web.domain.chamber import (
    ChamberCapabilities, ChamberIdentity, ChamberIdentityMismatch, ChamberSnapshot,
    ChamberSafetyError, OperationState, ReadingQuality, UnsupportedCapability,
    finite_temperature,
)


class VotschBackend:
    def __init__(self, chamber_id: str, ip: str, *, mock_driver_factory: Callable | None = None,
                 hil=None, hil_driver_factory: Callable | None = None):
        if mock_driver_factory is not None and hil is not None:
            raise ChamberSafetyError("A backend is either simulated or physical HIL, never both")
        if hil is not None and (hil.chamber_id != chamber_id or hil.address != ip):
            raise ChamberSafetyError("HIL authorization does not match this chamber/endpoint")
        if hil is None and hil_driver_factory is not None:
            raise ChamberSafetyError("HIL driver factory requires a HIL authorization")
        self._chamber_id = chamber_id
        self._ip = ip
        self._factory = mock_driver_factory
        self._hil = hil
        self._hil_factory = hil_driver_factory
        self._driver = None
        self._identity: ChamberIdentity | None = None
        self._ramp: tuple[float, float] | None = None
        self._digital_outputs: tuple[tuple[int, str], ...] = ()

    @property
    def simulation_only(self) -> bool:
        # Only an explicitly injected mock factory is a simulation.
        return self._factory is not None

    @property
    def physical_authorized(self) -> bool:
        # Only an explicit launch-time HIL authorization enables physical I/O.
        return self._hil is not None

    def connect(self) -> None:
        if self._factory is not None:
            self._driver = self._factory()
            return
        if self._hil is None:
            # Hardware requires an explicit supervised HIL authorization.
            raise ChamberSafetyError("Physical Vötsch I/O DISABLED without HIL authorization")
        factory = self._hil_factory or self._default_hil_driver
        driver = factory()
        try:
            serial = str(driver.serial_number).strip()
            if serial != self._hil.expected_serial:
                raise ChamberIdentityMismatch(
                    "Connected chamber serial does not match CHAMBER_HIL_EXPECTED_SERIAL")
            self._identity = ChamberIdentity(
                self._chamber_id, "votsch", "Vötsch", str(driver.test_system_type).strip(),
                serial, is_simulation=False)
            # Read-only: the 11002 setpoint readback follows these device ramps.
            ramp = (float(driver.gradient_up), float(driver.gradient_down))
            if not all(math.isfinite(rate) and 0 < rate <= 60 for rate in ramp):
                raise ChamberSafetyError("Chamber setpoint gradients unavailable or invalid")
            self._ramp = ramp
            try:
                self._digital_outputs = self._enumerate_digital_outputs(driver)
            except ChamberSafetyError:
                raise
            except Exception as exc:
                raise ChamberSafetyError(
                    "Chamber digital outputs unavailable or invalid") from exc
        except BaseException:
            driver.disconnect()
            raise
        self._driver = driver

    @staticmethod
    def _enumerate_digital_outputs(driver) -> tuple[tuple[int, str], ...]:
        """Advertise only outputs the device reports; never assume a count."""
        count = driver.number_of_digital_outputs
        if type(count) is not int or not 1 <= count <= 64:
            raise ChamberSafetyError("Chamber digital output count unavailable or invalid")
        outputs = []
        for number in range(1, count + 1):
            name = driver.digital_output_name(number)
            if not isinstance(name, str) or not name.strip():
                raise ChamberSafetyError("Chamber digital output name unavailable or invalid")
            outputs.append((number, name.strip()))
        return tuple(outputs)

    def _default_hil_driver(self):
        from VotschTechnikClimateChamber import ClimateChamber
        # Driver-level limits are a second, independent guard on the envelope.
        return ClimateChamber(self._ip, self._hil.temperature_min_c,
                              self._hil.temperature_max_c, timeout=2)

    def disconnect(self) -> None:
        if self._driver is not None:
            try:
                self._driver.disconnect()
            finally:
                self._driver = None
                self._identity = None
                self._digital_outputs = ()

    def _require(self):
        if self._driver is None:
            raise ChamberSafetyError("Vötsch backend not connected / not approved")
        return self._driver

    def identify(self) -> ChamberIdentity:
        driver = self._require()
        if self._hil is not None:
            return self._identity
        return ChamberIdentity(self._chamber_id, "votsch", "Vötsch",
                               str(driver.test_system_type), str(driver.serial_number),
                               is_simulation=self._factory is not None)

    def capabilities(self) -> ChamberCapabilities:
        # Mock limits are for contract tests ONLY, not a physical certification.
        if self._hil is not None:
            # Software envelope from the HIL authorization; NOT a chamber certification.
            return ChamberCapabilities(self._hil.temperature_min_c,
                                       self._hil.temperature_max_c, True, True, True,
                                       setpoint_readback_ramp_c_per_min=self._ramp,
                                       digital_outputs=self._digital_outputs)
        if self._factory is None:
            return ChamberCapabilities(0, 1, False, False, False)
        return ChamberCapabilities(-20, 80, True, True, True)

    def read_status(self) -> ChamberSnapshot:
        driver = self._require()
        if self._hil is not None and str(driver.serial_number).strip() != self._identity.serial_number:
            # Re-verified on every read: an endpoint swap must never be controlled.
            raise ChamberIdentityMismatch("Chamber serial changed during the HIL session")
        return ChamberSnapshot(
            self.identify(), float(driver.temperature_measured),
            float(driver.temperature_set_point),
            OperationState.RUNNING if driver.is_running else OperationState.STOPPED,
            ReadingQuality.GOOD, datetime.now(timezone.utc),
        )

    def set_temperature(self, target_c: float) -> None:
        caps = self.capabilities()
        self._require().temperature_set_point = finite_temperature(
            target_c, caps.temperature_min_c, caps.temperature_max_c
        )

    def start(self) -> None:
        self._require().start()

    def stop(self) -> None:
        self._require().stop()

    def read_digital_output(self, number: int) -> bool:
        if type(number) is not int or not 1 <= number <= 64:
            raise UnsupportedCapability("Digital output number must be 1..64")
        driver = self._require()
        self._require_verified_output(number)
        value = driver.read_digital_output(number)
        if type(value) is not bool:
            raise ChamberSafetyError("Digital output readback was not boolean")
        return value

    def set_digital_output(self, number: int, state: bool) -> None:
        if type(number) is not int or not 1 <= number <= 64 or type(state) is not bool:
            raise UnsupportedCapability("Digital output number/state invalid")
        driver = self._require()
        self._require_verified_output(number)
        driver.set_digital_output(number, state)

    def _require_verified_output(self, number: int) -> None:
        if self._hil is None:
            return
        if number not in {item[0] for item in self._digital_outputs}:
            raise UnsupportedCapability(
                "Digital output is not verified on this physical chamber")

    def set_ramp_up(self, rate_c_per_min: float) -> None:
        raise UnsupportedCapability("Ramp units and support are not HIL certified")

    def set_ramp_down(self, rate_c_per_min: float) -> None:
        raise UnsupportedCapability("Ramp units and support are not HIL certified")


def verify_bundled_driver_import() -> str:
    """Packaging-only check: import the external driver without connecting hardware."""
    from VotschTechnikClimateChamber import ClimateChamber
    from VotschTechnikClimateChamber import __version__ as driver_version

    if not callable(ClimateChamber):
        raise RuntimeError("Frozen Vötsch driver entry point is not callable")
    return str(driver_version)
