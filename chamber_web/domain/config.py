"""Typed backend-neutral single-chamber configuration for v1."""
from dataclasses import dataclass

from chamber_web.domain.chamber import ChamberSafetyError, validate_chamber_id


@dataclass(frozen=True)
class ChamberConfig:
    chamber_id: str
    backend_id: str
    address: str | None = None

    def __post_init__(self) -> None:
        validate_chamber_id(self.chamber_id)
        if not isinstance(self.backend_id, str) or not self.backend_id:
            raise ChamberSafetyError("backend_id must be a nonempty registry key")
        if self.address is not None and (
            not isinstance(self.address, str) or len(self.address) > 255
        ):
            raise ChamberSafetyError("Endpoint format invalid")
