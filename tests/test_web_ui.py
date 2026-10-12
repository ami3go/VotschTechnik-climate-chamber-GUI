"""Read-only G02-A NiceGUI smoke test; no physical chamber ever connected."""
from typing import Callable

from nicegui.testing import User


async def test_dashboard_builds(create_user: Callable[[], User]) -> None:
    user = create_user()
    await user.open("/")
    await user.should_see("Climate Chamber")
    await user.should_see("SIMULATION")
    await user.should_see("Chamber Control")
    await user.should_see("Profile Editor")
    await user.should_see("Temperature Graph (Simulation)")
    await user.should_see("Import CSV")
    await user.should_see("Export CSV")
    await user.should_see("Backend: fake · demo-chamber")
    await user.should_see("G04/G08-min")

    # Different browser sessions obtain the same process-owned telemetry.
    other = create_user()
    await other.open("/")
    await other.should_see("Backend: fake · demo-chamber")
    # Navigation/reload creates a new page, not a new chamber controller.
    await user.open("/")
    await user.should_see("Backend: fake · demo-chamber")
