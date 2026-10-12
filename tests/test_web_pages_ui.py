"""G02-B NiceGUI page/browser smoke tests (FakeBackend only)."""
from typing import Callable

from nicegui.testing import User


async def test_read_only_routes_and_repeat_browsers(create_user: Callable[[], User]) -> None:
    user = create_user()
    for url, heading in (
        ("/history", "Run History"),
        ("/logs", "Persistent Event Logs"),
        ("/settings", "Server Configuration (read-only)"),
        ("/profiles", "Persistent Profiles / Revisions"),
    ):
        await user.open(url)
        await user.should_see(heading)
        await user.should_see("SIMULATION")
    await user.open("/history")
    await user.should_see("G07 run recording/history service is not installed.")
    other = create_user()
    await other.open("/logs")
    await other.should_see("G07 persistent event/audit log service is not installed.")
    await user.open("/settings")
    await user.should_see("Control availability")
    await user.should_see("Physical controls disabled")
