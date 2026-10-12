"""G08-min NiceGUI login gate: no anonymous access to the dashboard."""
from typing import Callable

from nicegui.testing import User


async def test_anonymous_dashboard_redirects_to_login(create_user: Callable[[], User]) -> None:
    user = create_user()
    await user.open("/")
    await user.should_see("Climate Chamber")
    await user.should_see("sign in")
    await user.should_see("Username")
    await user.should_see("Password")
