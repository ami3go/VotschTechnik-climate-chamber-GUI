"""Explicit single-device demo composition root, never a hardware launcher."""
from __future__ import annotations

from chamber_web.adapters.registry import make_backend
from chamber_web.domain.config import ChamberConfig
from chamber_web.services.chamber_manager import ChamberManager
from chamber_web.services.dashboard import DashboardService


def create_demo_dashboard_service() -> DashboardService:
    # Deliberately hard-coded FakeBackend: no environment variable or web input
    # can select a physical endpoint before G04/G08-min/site HIL approval.
    config = ChamberConfig("demo-chamber", "fake")
    manager = ChamberManager([config], backend_factory=make_backend)
    manager.connect(config.chamber_id)  # connects in-memory FakeBackend only
    return DashboardService(manager, config.chamber_id)
