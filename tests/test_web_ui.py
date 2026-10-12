"""In-process NiceGUI service-bound page smoke tests; never physical I/O."""
import pytest
from nicegui.testing import User

from chamber_web.adapters.registry import make_backend
from chamber_web.adapters.votsch import VotschBackend
from chamber_web.domain.config import ChamberConfig
from chamber_web.services.chamber_manager import ChamberManager
from chamber_web.services.dashboard import DashboardService


class MockDriver:
    test_system_type = "VT4011-MOCK"
    serial_number = "TEST-ONLY"
    temperature_measured = 25.0
    temperature_set_point = 25.0
    is_running = False

    def disconnect(self):
        pass


async def test_dashboard_builds(user: User) -> None:
    await user.open("/")
    await user.should_see("Climate Chamber")
    await user.should_see("SIMULATION ONLY")
    await user.should_see("Chamber Control")
    await user.should_see("Profile Editor (draft only)")
    await user.should_see("Temperature Graph (backend observations)")
    await user.should_see("Import CSV")
    await user.should_see("Export CSV")
    await user.should_see("SIMULATION · SIMULATION Fake")
    await user.should_see("Chamber ID: demo-chamber")
    await user.should_see("Reading: GOOD")


@pytest.mark.parametrize("backend_id,expected_label", [
    ("fake", "SIMULATION · SIMULATION Fake"),
    ("alternate_stub", "SIMULATION · ExampleCo NoGradient-50"),
    ("votsch", "SIMULATION · Vötsch VT4011-MOCK"),
])
async def test_dashboard_substitutes_backend_without_page_changes(
    user: User, monkeypatch, backend_id: str, expected_label: str,
) -> None:
    config = ChamberConfig(
        f"ui-{backend_id}", backend_id,
        "mock.invalid" if backend_id == "votsch" else None,
    )

    def factory(config, *, allow_test_backend=False):
        if config.backend_id == "votsch":
            return VotschBackend(config.chamber_id, config.address or "",
                                 mock_driver_factory=MockDriver)
        return make_backend(config, allow_test_backend=allow_test_backend)

    manager = ChamberManager([config], backend_factory=factory, allow_test_backend=True)
    service = DashboardService(manager, config.chamber_id)
    service.connect()
    monkeypatch.setattr("chamber_web.main.get_dashboard_service", lambda: service)
    await user.open("/")
    await user.should_see(expected_label)
    await user.should_see(f"Chamber ID: {config.chamber_id}")
    await user.should_see("STOPPED")
    await user.should_see("Reading: GOOD")
    manager.disconnect(config.chamber_id)

async def test_page_reload_uses_existing_server_backend(user: User, monkeypatch) -> None:
    config = ChamberConfig("ui-refresh", "fake")
    manager = ChamberManager([config], backend_factory=make_backend)
    service = DashboardService(manager, config.chamber_id)
    service.connect()
    monkeypatch.setattr("chamber_web.main.get_dashboard_service", lambda: service)
    await user.open("/")
    await user.should_see("STOPPED")
    manager.start(config.chamber_id)  # external simulated state change
    await user.open("/")  # a fresh page, not a fresh backend
    await user.should_see("RUNNING")
    manager.disconnect(config.chamber_id)
