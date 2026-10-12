"""Explicit backend registry/factory; never import arbitrary modules from UI input."""
from __future__ import annotations

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


def make_backend(config: ChamberConfig, *, allow_test_backend: bool = False):
    # Localized imports keep services/domain independent of manufacturer modules.
    if config.backend_id == "fake":
        from .fake import FakeBackend
        return FakeBackend(config.chamber_id)
    if config.backend_id == "votsch":
        from .votsch import VotschBackend
        return VotschBackend(config.chamber_id, config.address or "")
    if config.backend_id == "alternate_stub" and allow_test_backend:
        from .alternate_stub import AlternateStubBackend
        return AlternateStubBackend(config.chamber_id)
    raise ChamberSafetyError("Test-only backend cannot be configured for production")
