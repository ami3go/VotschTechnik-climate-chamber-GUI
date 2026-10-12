"""Read-only G02-A NiceGUI smoke test; no physical chamber ever connected."""
from nicegui.testing import User


async def test_dashboard_builds(user: User) -> None:
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
