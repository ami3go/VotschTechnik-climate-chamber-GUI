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
        if self.backend_id not in {"fake", "votsch", "alternate_stub"}:
            raise ChamberSafetyError("Unknown or unapproved backend ID")
        if self.backend_id == "votsch" and not self.address:
            raise ChamberSafetyError("Vötsch endpoint required")
        if self.backend_id != "votsch" and self.address:
            raise ChamberSafetyError("Unexpected endpoint for simulation backend")
