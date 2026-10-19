"""NiceGUI chamber scan smoke: discovery does not connect or save hardware."""
from __future__ import annotations

import asyncio

from dataclasses import dataclass
from typing import Callable

import pytest
from nicegui.testing import User


@pytest.fixture(autouse=True)
def _loopback(monkeypatch):
    original = User.open
    async def open_local(self, path, *, clear_forward_history=True):
        self.http_client.base_url = "http://127.0.0.1:8080"
        return await original(self, path, clear_forward_history=clear_forward_history)
    monkeypatch.setattr(User, "open", open_local)


@dataclass(frozen=True)
class Candidate:
    address: str
    model: str
    serial_number: str


async def test_admin_can_scan_and_select_without_saving(
        create_user: Callable[[], User], monkeypatch, tmp_path):
    from chamber_web import main as application
    from chamber_web.security import nicegui as security_ui
    from chamber_web.security.auth import SecurityStore

    store = SecurityStore(tmp_path / "security")
    store.provision_factory_admin()
    monkeypatch.setattr(security_ui, "_store", store)
    monkeypatch.setattr(application._manual_service, "_security", store)
    monkeypatch.setattr(application._manual_service._authorized, "_security", store)
    scopes = []
    def fake_discovery(network):
        scopes.append(network)
        return [Candidate("192.168.10.20", "LabEvent T", "ABC123")]
    monkeypatch.setattr(application, "discover_votsch_chambers", fake_discovery)
    monkeypatch.setenv("CHAMBER_SECURITY_DIR", str(tmp_path / "storage"))

    user = create_user()
    await user.open("/login")
    user.find("Username").type("admin")
    user.find("Password").type("admin")
    user.find("Sign in").click()
    await user.should_see("Signed in: admin (ADMIN)", retries=30)
    await user.open("/settings")
    await user.should_see("Auto-detect chambers", retries=30)
    user.find("Chamber IP or private subnet").type("192.168.10.0/24")
    user.find("Auto-detect chambers").click()
    await user.should_see("ABC123", retries=30)
    user.find("Select").click()
    await user.should_see("Expected serial number", retries=30)
    assert scopes == ["192.168.10.0/24"]
    # Selection is an unsaved draft; no HIL authorization or physical I/O.
    assert not (tmp_path / "storage" / "chamber_settings.json").exists()


async def test_verify_configured_ip_and_scan_local_override(
        create_user: Callable[[], User], monkeypatch, tmp_path):
    from chamber_web import main as application
    from chamber_web.pages import chamber_config
    from chamber_web.hil.chamber_settings import ChamberSettings
    from chamber_web.security import nicegui as security_ui
    from chamber_web.security.auth import SecurityStore

    # Show the physical connection form in this simulation-only UI test.
    monkeypatch.setattr(chamber_config, "load_settings",
                        lambda: ChamberSettings(chamber_type="votsch"))
    store = SecurityStore(tmp_path / "security")
    store.provision_factory_admin()
    monkeypatch.setattr(security_ui, "_store", store)
    monkeypatch.setattr(application._manual_service, "_security", store)
    monkeypatch.setattr(application._manual_service._authorized, "_security", store)
    scopes = []

    def fake_discovery(scope):
        scopes.append(scope)
        return [Candidate("192.168.10.20", "LabEvent T", "ABC123")] if scope else []

    monkeypatch.setattr(application, "discover_votsch_chambers", fake_discovery)
    monkeypatch.setenv("CHAMBER_SECURITY_DIR", str(tmp_path / "storage"))
    user = create_user()
    await user.open("/login")
    user.find("Username").type("admin")
    user.find("Password").type("admin")
    user.find("Sign in").click()
    await user.should_see("Signed in: admin (ADMIN)", retries=30)
    await user.open("/settings")
    # The original IP configuration field now works as an explicit probe input.
    user.find("IP address (private IPv4)").type("192.168.10.20")
    user.find("Verify this IP").click()
    await user.should_see("ABC123", retries=30)
    assert scopes == ["192.168.10.20"]
    assert not (tmp_path / "storage" / "chamber_settings.json").exists()


async def test_discovery_failure_displays_specific_error(
        create_user: Callable[[], User], monkeypatch, tmp_path):
    from chamber_web import main as application
    from chamber_web.security import nicegui as security_ui
    from chamber_web.security.auth import SecurityStore

    store = SecurityStore(tmp_path / "security")
    store.provision_factory_admin()
    monkeypatch.setattr(security_ui, "_store", store)
    monkeypatch.setattr(application._manual_service, "_security", store)
    monkeypatch.setattr(application._manual_service._authorized, "_security", store)
    scopes = []

    def fake_discovery(scope):
        scopes.append(scope)
        raise RuntimeError("TCP 2049 connection refused; check S!MPAC service")

    monkeypatch.setattr(application, "discover_votsch_chambers", fake_discovery)
    monkeypatch.setenv("CHAMBER_SECURITY_DIR", str(tmp_path / "storage"))
    user = create_user()
    await user.open("/login")
    user.find("Username").type("admin")
    user.find("Password").type("admin")
    user.find("Sign in").click()
    await user.should_see("Signed in: admin (ADMIN)", retries=30)
    await user.open("/settings")
    user.find("Chamber IP or private subnet").type("192.168.1.42")
    user.find("Auto-detect chambers").click()
    await user.should_see("TCP 2049 connection refused", retries=30)
    assert scopes == ["192.168.1.42"]


async def test_scan_local_networks_ignores_configured_ip(
        create_user: Callable[[], User], monkeypatch, tmp_path):
    from chamber_web import main as application
    from chamber_web.pages import chamber_config
    from chamber_web.hil.chamber_settings import ChamberSettings
    from chamber_web.security import nicegui as security_ui
    from chamber_web.security.auth import SecurityStore

    monkeypatch.setattr(chamber_config, "load_settings", lambda: ChamberSettings(
        chamber_type="votsch", address="192.168.10.20"))
    store = SecurityStore(tmp_path / "security")
    store.provision_factory_admin()
    monkeypatch.setattr(security_ui, "_store", store)
    monkeypatch.setattr(application._manual_service, "_security", store)
    monkeypatch.setattr(application._manual_service._authorized, "_security", store)
    scopes = []

    def fake_discovery(scope):
        scopes.append(scope)
        return []

    monkeypatch.setattr(application, "discover_votsch_chambers", fake_discovery)
    monkeypatch.setenv("CHAMBER_SECURITY_DIR", str(tmp_path / "storage"))
    user = create_user()
    await user.open("/login")
    user.find("Username").type("admin")
    user.find("Password").type("admin")
    user.find("Sign in").click()
    await user.should_see("Signed in: admin (ADMIN)", retries=30)
    await user.open("/settings")
    user.find("Scan local networks").click()
    # Give NiceGUI's async click handler a deterministic scheduling opportunity.
    for _ in range(30):
        if scopes:
            break
        await asyncio.sleep(0.05)
    assert scopes == [None]
    await user.should_see("No compatible Vötsch/Weiss chambers", retries=30)

@pytest.mark.parametrize("changed_password", [False, True])
async def test_physical_chamber_settings_save_with_factory_pin_warning(
        create_user: Callable[[], User], monkeypatch, tmp_path, changed_password):
    """Browser save succeeds with factory PIN; no hardware connection or actuation."""
    from chamber_web import main as application
    from chamber_web.hil.chamber_settings import ChamberSettings, load_settings
    from chamber_web.pages import chamber_config
    from chamber_web.security import nicegui as security_ui
    from chamber_web.security.auth import SecurityStore

    store = SecurityStore(tmp_path / "security")
    store.provision_factory_admin()
    password = "admin"
    if changed_password:
        original = store.login("admin", "admin")
        store.change_password(original.session, original.csrf, "admin",
                              "ChangedPassword#123")
        store = SecurityStore(tmp_path / "security")  # simulate restart
        password = "ChangedPassword#123"
        assert store.factory_credentials_active() == (False, True)
    monkeypatch.setattr(security_ui, "_store", store)
    monkeypatch.setattr(application._manual_service, "_security", store)
    monkeypatch.setattr(application._manual_service._authorized, "_security", store)
    monkeypatch.setenv("CHAMBER_SECURITY_DIR", str(tmp_path / "storage"))
    mock_settings = ChamberSettings(
        chamber_type="votsch", chamber_id="lab-1", address="192.168.10.20",
        expected_serial="ABC123", temperature_min_c=15.0, temperature_max_c=35.0,
        person_present_acknowledged=True)
    monkeypatch.setattr(chamber_config, "load_settings", lambda: mock_settings)

    user = create_user()
    await user.open("/login")
    user.find("Username").type("admin")
    user.find("Password").type(password)
    user.find("Sign in").click()
    await user.should_see("Signed in: admin (ADMIN)", retries=30)
    await user.open("/settings")
    await user.should_see("Security advisory only", retries=30)
    user.find("Current administrator password (required to save)").type(password)
    user.find("Save chamber settings").click()
    await user.should_see("Saved (applies after restart): Vötsch", retries=30)
    target = tmp_path / "storage" / "chamber_settings.json"
    for _ in range(30):
        if target.exists():
            break
        await asyncio.sleep(0.05)
    assert target.exists()
    assert load_settings(target).address == "192.168.10.20"
    assert store.factory_credentials_active() == (
        (False, True) if changed_password else (True, True))
