"""Explicit backend registry/factory; never import arbitrary modules from UI input."""
from __future__ import annotations

from chamber_web.domain.chamber import ChamberSafetyError
from chamber_web.domain.config import ChamberConfig


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
