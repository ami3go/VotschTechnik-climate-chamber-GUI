"""In-process NiceGUI page smoke tests (no physical chamber needed)."""
from nicegui.testing import User


async def test_dashboard_builds(user: User) -> None:
    await user.open("/")
    await user.should_see("Climate Chamber")
    await user.should_see("DEMO MODE")
    await user.should_see("Chamber Control")
    await user.should_see("Profile Editor")
    await user.should_see("Temperature Graph (Simulation)")
    await user.should_see("Import CSV")
    await user.should_see("Export CSV")
    await user.should_see("SIMULATION · DISCONNECTED")
