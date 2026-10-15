"""Explicit single-device composition root; hardware only via explicit HIL authorization."""
from __future__ import annotations

from chamber_web.adapters.registry import make_backend
from chamber_web.domain.chamber import ChamberSafetyError
from chamber_web.domain.config import ChamberConfig
from chamber_web.services.chamber_manager import ChamberManager
from chamber_web.services.dashboard import DashboardService


def create_demo_dashboard_service() -> DashboardService:
    # Deliberately hard-coded FakeBackend: no environment variable or web input
    # can select a physical endpoint before G04/G08-min/site HIL approval.
    config = ChamberConfig("demo-chamber", "fake")
    manager = ChamberManager([config], backend_factory=make_backend)
    manager.connect(config.chamber_id)  # connects in-memory FakeBackend only
    return DashboardService(manager, config.chamber_id, disconnect_on_close=True)


def create_demo_control_services(security, hil=None, *, hil_driver_factory=None):
    """Composition root for G05: one device and G08-min authority.

    Default is one FakeBackend. Only an explicit launch-time ``HilAuthorization``
    (validated from the server's own environment, never from a browser) selects
    the single supervised physical Vötsch chamber.
    """
    from chamber_web.security.guards import AuthorizedChamber
    from chamber_web.services.manual_control import ManualControlService

    if hil is None:
        config = ChamberConfig("demo-chamber", "fake")
        factory = make_backend
    else:
        from chamber_web.adapters.votsch import VotschBackend

        config = ChamberConfig(hil.chamber_id, "votsch", hil.address)

        def factory(cfg, allow_test_backend=False):
            if cfg != config:
                raise ChamberSafetyError("Unexpected chamber configuration for HIL")
            return VotschBackend(cfg.chamber_id, cfg.address, hil=hil,
                                 hil_driver_factory=hil_driver_factory)
    manager = ChamberManager([config], backend_factory=factory)
    manager.connect(config.chamber_id)
    dashboard = DashboardService(manager, config.chamber_id, disconnect_on_close=True)
    manual = ManualControlService(
        manager, dashboard, AuthorizedChamber(manager, security), security,
        config.chamber_id, physical_hil=hil)
    return dashboard, manual
