"""G02-A composition root: one FakeBackend per server, never physical hardware.

No config file, browser parameter or environment variable can select a physical
adapter here. Future hardware startup requires G04/G08-min/P00/HIL approval.
"""
from __future__ import annotations

from threading import Lock

from chamber_web.adapters.registry import make_backend
from chamber_web.domain.config import ChamberConfig
from chamber_web.services.chamber_manager import ChamberManager
from chamber_web.services.dashboard import DashboardService

_service: DashboardService | None = None
_service_lock = Lock()


def get_dashboard_service() -> DashboardService:
    global _service
    with _service_lock:
        if _service is None:
            config = ChamberConfig("demo-chamber", "fake")
            manager = ChamberManager([config], backend_factory=make_backend)
            service = DashboardService(manager, config.chamber_id)
            service.connect()
            _service = service
        return _service
