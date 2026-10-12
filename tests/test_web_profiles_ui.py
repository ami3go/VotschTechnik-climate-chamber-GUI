"""G03-C NiceGUI smoke tests: independent sessions and durable library route."""
from typing import Callable

from nicegui.testing import User


async def test_profiles_page_renders_persistent_ag_grid(create_user: Callable[[], User]) -> None:
    user = create_user()
    await user.open("/profiles")
    await user.should_see("Persistent Profiles / Revisions")
    await user.should_see("Profile Library")
    await user.should_see("Profile Editor")
    await user.should_see("New Temperature Profile")
    await user.should_see("Immutable Revision History")
    await user.should_see("Spreadsheet-safe CSV")
    await user.should_see("SIMULATION")
    await user.should_see("No execution controls")

    second = create_user()
    await second.open("/profiles")
    await second.should_see("Profile Library")
    await second.should_see("New Temperature Profile")

    # Reopening creates a new page-local draft, not another chamber service.
    await user.open("/profiles")
    await user.should_see("Persistent Profiles / Revisions")
