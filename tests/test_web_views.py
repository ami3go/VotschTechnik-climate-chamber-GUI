"""G02-B pure UI and G07 integration-contract security regressions."""
import unittest
from dataclasses import replace
from datetime import datetime, timezone

from chamber_web.adapters.alternate_stub import AlternateStubBackend
from chamber_web.adapters.fake import FakeBackend
from chamber_web.adapters.votsch import VotschBackend
from chamber_web.domain.chamber import OperationState, ReadingQuality
from chamber_web.domain.config import ChamberConfig
from chamber_web.services.chamber_manager import ChamberManager
from chamber_web.services.dashboard import DashboardService
from chamber_web.services.web_read_models import (
    RecordPage, UnavailableEventReader, UnavailableHistoryReader, bounded_search,
)
from chamber_web.ui_state import (project_capabilities, project_chamber_identity,
                                  project_telemetry, safe_view)


class MockVotsch:
    test_system_type = "Mock"
    serial_number = "SIM"
    temperature_measured = 24.5
    temperature_set_point = 25.0
    is_running = False
    def disconnect(self):
        pass


class WebViewsTests(unittest.IsolatedAsyncioTestCase):
    async def test_sequential_vendor_neutral_projection(self):
        variants = (
            ("fake", lambda cid: FakeBackend(cid)),
            ("alternate_stub", lambda cid: AlternateStubBackend(cid)),
            ("votsch", lambda cid: VotschBackend(cid, "mock.invalid",
                                                mock_driver_factory=MockVotsch)),
        )
        for key, factory in variants:
            with self.subTest(backend=key):
                manager = ChamberManager([ChamberConfig("single", key)],
                                         backend_factory=lambda cfg, **kw: factory(cfg.chamber_id),
                                         allow_test_backend=True)
                manager.connect("single")
                try:
                    service = DashboardService(manager, "single")
                    view = await service.poll_once()
                    display = project_telemetry(view)
                    self.assertEqual(display.quality, "GOOD")
                    self.assertIn(key, display.identity)
                    self.assertTrue(display.measured.endswith("°C"))
                    self.assertIn("disabled", project_capabilities(view).controls_locked_reason)
                finally:
                    manager.disconnect("single")

    async def test_disconnect_fails_closed_and_no_logs_are_fabricated(self):
        manager = ChamberManager([ChamberConfig("one", "fake")],
                                 backend_factory=lambda cfg, **kw: FakeBackend(cfg.chamber_id))
        manager.connect("one")
        try:
            service = DashboardService(manager, "one")
            good = await service.poll_once()
            self.assertEqual(project_telemetry(good).operation, "STOPPED")
            manager.disconnect("one")
            bad = await service.poll_once()
            self.assertEqual(project_telemetry(bad).operation, "UNKNOWN")
            self.assertEqual(project_telemetry(bad).measured, "— (unverified)")
        finally:
            manager.disconnect("one")
        self.assertFalse(UnavailableHistoryReader().list_runs("one").available)
        self.assertFalse(UnavailableEventReader().list_events("one").available)

    def test_unknown_fault_stale_hide_previous_verified_temperatures(self):
        from chamber_web.domain.chamber import ChamberCapabilities
        from chamber_web.services.dashboard import DashboardView
        now = datetime.now(timezone.utc)
        original = DashboardView("one", measured_temperature_c=33.0,
                                 setpoint_temperature_c=25.0,
                                 capabilities=ChamberCapabilities(-20, 80, True, True, True),
                                 quality=ReadingQuality.GOOD,
                                 sampled_at_utc=now,
                                 operation_state=OperationState.RUNNING)
        self.assertEqual(project_telemetry(original).measured, "33.0 °C")
        for state in (OperationState.FAULT, OperationState.UNKNOWN):
            value = project_telemetry(replace(original, operation_state=state))
            self.assertEqual(value.measured, "— (unverified)")
            self.assertEqual(value.operation, state.value)
        value = project_telemetry(replace(original, quality=ReadingQuality.STALE))
        self.assertEqual(value.operation, "UNKNOWN")
        self.assertEqual(value.setpoint, "— (unverified)")
        self.assertEqual(value.sampled_utc, "Unavailable")

    def test_no_identity_or_readback_never_claimed_verified(self):
        from chamber_web.domain.chamber import ChamberCapabilities
        from chamber_web.services.dashboard import DashboardView
        now = datetime.now(timezone.utc)
        view = DashboardView("one", measured_temperature_c=30.0,
                             setpoint_temperature_c=25.0,
                             sampled_at_utc=now, quality=ReadingQuality.GOOD,
                             operation_state=OperationState.RUNNING)
        self.assertEqual(project_telemetry(view).mode, "IDENTITY UNVERIFIED")
        self.assertEqual(project_telemetry(view).operation, "UNKNOWN")
        missing_readback = replace(view, capabilities=ChamberCapabilities(
            -20, 80, True, False, False))
        self.assertEqual(project_telemetry(missing_readback).operation, "UNKNOWN")
        self.assertEqual(project_telemetry(missing_readback).setpoint, "— (unverified)")
        self.assertEqual(project_telemetry(missing_readback).measured, "— (unverified)")

    def test_dashboard_identity_in_simulation_has_no_fictional_ip_or_serial(self):
        from chamber_web.services.dashboard import DashboardView
        from chamber_web.domain.chamber import ChamberIdentity
        view = DashboardView("demo-chamber", identity=ChamberIdentity(
            "demo-chamber", "fake", "SIMULATION", "Fake", None, True))
        shown = project_chamber_identity(view)
        self.assertEqual(shown.chamber, "Simulator · demo-chamber")
        self.assertIn("simulation", shown.ip_address)
        self.assertIn("simulation", shown.serial_number)
        self.assertIn("no physical chamber", shown.identity_status)

    def test_dashboard_identity_physical_uses_configured_endpoint_and_serial(self):
        from chamber_web.services.dashboard import DashboardView
        from chamber_web.domain.chamber import ChamberIdentity
        identity = ChamberIdentity(
            "lab-1", "votsch", "Vötsch", "VT4011", "ABC123", False)
        view = DashboardView(
            "lab-1", identity=identity, quality=ReadingQuality.GOOD,
            sampled_at_utc=datetime.now(timezone.utc),
        )
        shown = project_chamber_identity(
            view, configured_address="192.168.10.20", expected_serial="ABC123")
        self.assertEqual(shown.chamber, "Vötsch VT4011 · lab-1")
        self.assertEqual(shown.ip_address, "192.168.10.20")
        self.assertEqual(shown.serial_number, "ABC123")
        self.assertEqual(shown.identity_status, "Live identity verified")

    def test_dashboard_identity_unavailable_does_not_claim_live_identity(self):
        from chamber_web.services.dashboard import DashboardView
        from chamber_web.domain.chamber import ChamberIdentity
        identity = ChamberIdentity(
            "lab-1", "votsch", "Vötsch", "VT4011", "ABC123", False)
        missing = DashboardView("lab-1")
        initial = project_chamber_identity(
            missing, configured_address="192.168.10.20", expected_serial="ABC123")
        self.assertEqual(initial.chamber, "Vötsch chamber · lab-1")
        self.assertEqual(initial.ip_address, "192.168.10.20")
        self.assertEqual(initial.serial_number, "ABC123")
        self.assertIn("not yet verified", initial.identity_status)
        # GOOD without a valid fresh sample timestamp cannot imply
        # a verified live connection.
        missing_stamp = project_chamber_identity(
            replace(missing, identity=identity, quality=ReadingQuality.GOOD),
            configured_address="192.168.10.20", expected_serial="ABC123")
        self.assertNotEqual(missing_stamp.identity_status, "Live identity verified")
        for quality in (ReadingQuality.ERROR, ReadingQuality.STALE):
            with self.subTest(quality=quality):
                stale = project_chamber_identity(
                    replace(missing, identity=identity, quality=quality),
                    configured_address="192.168.10.20", expected_serial="ABC123")
                self.assertIn("last seen", stale.identity_status)
                self.assertNotIn("Live identity verified", stale.identity_status)

    def test_dashboard_identity_mismatch_or_simulation_never_verifies_physical(self):
        from chamber_web.services.dashboard import DashboardView
        from chamber_web.domain.chamber import ChamberIdentity
        for serial, is_sim, chamber_id in (
            ("WRONG", False, "lab-1"),
            ("ABC123", True, "lab-1"),
            ("ABC123", False, "other-chamber"),
        ):
            with self.subTest(serial=serial, sim=is_sim, chamber=chamber_id):
                identity = ChamberIdentity(
                    chamber_id, "votsch", "Vötsch", "VT4011", serial, is_sim)
                shown = project_chamber_identity(
                    DashboardView("lab-1", identity=identity, quality=ReadingQuality.GOOD),
                    configured_address="192.168.10.20", expected_serial="ABC123")
                self.assertEqual(shown.chamber, "Vötsch chamber · lab-1")
                self.assertIn("not yet verified", shown.identity_status)
                self.assertEqual(shown.serial_number, "ABC123")

    def test_navigation_role_provider_can_fail_closed(self):
        from chamber_web.ui_pages import NavigationContext, visible_navigation_routes
        self.assertEqual(visible_navigation_routes(NavigationContext()),
                         ("/", "/profiles", "/history", "/logs", "/settings"))
        ctx = NavigationContext(authenticated=True, role="VIEWER",
                                permitted_routes=frozenset({"/", "/history"}))
        self.assertEqual(visible_navigation_routes(ctx), ("/", "/history"))

    def test_limit_and_reader_bounds(self):
        self.assertEqual(len(bounded_search("X" * 10000)), 120)
        with self.assertRaises(ValueError):
            RecordPage(False, records=(object(),))
        with self.assertRaises(ValueError):
            RecordPage(True, records=tuple(range(101)))

    def test_restarting_provider_fails_closed(self):
        class Restarting:
            chamber_id = "one"
            def view(self):
                raise OSError("private backend exception")
        display = project_telemetry(safe_view(Restarting()))
        self.assertEqual(display.operation, "UNKNOWN")
        self.assertNotIn("private backend exception", display.message)
