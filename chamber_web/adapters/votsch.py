"""ONLY GUI module permitted to import the externally maintained Vötsch driver.

The real hardware factory is intentionally disabled during G01. Mock-only
instances exercise protocol mapping without opening chamber connections.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from chamber_web.domain.chamber import (
    ChamberCapabilities, ChamberIdentity, ChamberSnapshot, ChamberSafetyError,
    OperationState, ReadingQuality, UnsupportedCapability, finite_temperature,
)


class VotschBackend:
    def __init__(self, chamber_id: str, ip: str, *, mock_driver_factory: Callable | None = None):
        self._chamber_id = chamber_id
        self._ip = ip
        self._factory = mock_driver_factory
        self._driver = None

    @property
    def simulation_only(self) -> bool:
        # Only an explicitly injected mock factory may execute in G04-A.
        return self._factory is not None

    def connect(self) -> None:
        if self._factory is None:
            # Hardware enablement MUST wait for G04, G08-min, P00 site approval and HIL.
            raise ChamberSafetyError("Physical Vötsch I/O DISABLED in the G01 foundation")
        self._driver = self._factory()

    def disconnect(self) -> None:
        if self._driver is not None:
            try:
                self._driver.disconnect()
            finally:
                self._driver = None

    def _require(self):
        if self._driver is None:
            raise ChamberSafetyError("Vötsch backend not connected / not approved")
        return self._driver

    def identify(self) -> ChamberIdentity:
        driver = self._require()
        return ChamberIdentity(self._chamber_id, "votsch", "Vötsch",
                               str(driver.test_system_type), str(driver.serial_number),
                               is_simulation=self._factory is not None)

    def capabilities(self) -> ChamberCapabilities:
        # Mock limits are for contract tests ONLY, not a physical certification.
        if self._factory is None:
            return ChamberCapabilities(0, 1, False, False, False)
        return ChamberCapabilities(-20, 80, True, True, True)

    def read_status(self) -> ChamberSnapshot:
        driver = self._require()
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
