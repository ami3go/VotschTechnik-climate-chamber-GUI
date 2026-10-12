"""G02-A telemetry/service boundaries; all fixtures are local, no device I/O."""
import asyncio
import ast
import pathlib
import unittest
from datetime import datetime, timedelta, timezone

from chamber_web.adapters.alternate_stub import AlternateStubBackend
from chamber_web.adapters.fake import FakeBackend
from chamber_web.adapters.votsch import VotschBackend
from chamber_web.bootstrap import create_demo_dashboard_service
from chamber_web.domain.chamber import (
    ChamberSafetyError, OperationState, ReadingQuality,
)
from chamber_web.domain.config import ChamberConfig
from chamber_web.services.chamber_manager import ChamberManager
from chamber_web.services.dashboard import DashboardService


class FakeDriver:
    test_system_type = "VT4011-MOCK"
    serial_number = "SIM-1"
    temperature_measured = 25.0
    temperature_set_point = 25.0
    is_running = False

    def disconnect(self):
        pass


class DashboardServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_server_survives_browser_disconnect_and_refresh(self):
        service = create_demo_dashboard_service()
        await service.start()
        try:
            a = service.view()
            self.assertEqual(a.chamber_id, "demo-chamber")
            self.assertTrue(a.identity.is_simulation)
            self.assertEqual(a.quality, ReadingQuality.GOOD)
            await asyncio.sleep(0)
            b = service.view()  # next browser consumes the same process-owned state
            self.assertEqual(a.identity, b.identity)
            self.assertGreaterEqual(len(service.recent_samples()), 1)
        finally:
            await service.close()

    async def test_three_backends_sequential_no_hardware(self):
        constructors = [
            ("fake", lambda cid: FakeBackend(cid)),
            ("alternate_stub", lambda cid: AlternateStubBackend(cid)),
            ("votsch", lambda cid: VotschBackend(cid, "mock.invalid",
                                                mock_driver_factory=FakeDriver)),
        ]
        for name, constructor in constructors:
            with self.subTest(adapter=name):
                chamber_id = "fixture-1"
                manager = ChamberManager(
                    [ChamberConfig(chamber_id, name)],
                    backend_factory=lambda cfg, allow_test_backend=False:
                    constructor(cfg.chamber_id),
                    allow_test_backend=True,
                )
                manager.connect(chamber_id)
                service = DashboardService(manager, chamber_id)
                view = await service.poll_once()
                self.assertEqual(view.identity.backend_id, name)
                self.assertTrue(view.identity.is_simulation)
                self.assertEqual(view.quality, ReadingQuality.GOOD)
                self.assertEqual(view.operation_state, OperationState.STOPPED)
                self.assertEqual(len(service.recent_samples()), 1)
                manager.disconnect(chamber_id)

    async def test_wrong_id_rejected_before_dispatch(self):
        manager = ChamberManager([ChamberConfig("valid", "fake")],
                                 backend_factory=lambda cfg, **kw: FakeBackend(cfg.chamber_id))
        with self.assertRaises(ChamberSafetyError):
            DashboardService(manager, "other")

    async def test_failure_clears_current_telemetry_and_preserves_history(self):
        backend = FakeBackend("test")
        manager = ChamberManager([ChamberConfig("test", "fake")],
                                 backend_factory=lambda cfg, **kw: backend)
        manager.connect("test")
        service = DashboardService(manager, "test")
        self.assertEqual((await service.poll_once()).quality, ReadingQuality.GOOD)
        manager.disconnect("test")
        failed = await service.poll_once()
        self.assertIsNone(failed.measured_temperature_c)
        self.assertIsNone(failed.setpoint_temperature_c)
        self.assertEqual(failed.operation_state, OperationState.UNKNOWN)
        self.assertEqual(failed.quality, ReadingQuality.ERROR)
        self.assertEqual(len(service.recent_samples()), 1)

    async def test_stale_does_not_report_old_running_state(self):
        manager = ChamberManager([ChamberConfig("test", "fake")],
                                 backend_factory=lambda cfg, **kw: FakeBackend(cfg.chamber_id))
        manager.connect("test")
        service = DashboardService(manager, "test", stale_after_s=0.001)
        await service.poll_once()
        await asyncio.sleep(0.02)
        stale = service.view()
        self.assertEqual(stale.quality, ReadingQuality.STALE)
        self.assertIsNone(stale.measured_temperature_c)
        self.assertEqual(stale.operation_state, OperationState.UNKNOWN)

    async def test_slow_read_does_not_block_async_loop(self):
        class SlowBackend(FakeBackend):
            def read_status(self):
                import time
                time.sleep(0.08)
                return super().read_status()
        manager = ChamberManager([ChamberConfig("test", "fake")],
                                 backend_factory=lambda cfg, **kw: SlowBackend(cfg.chamber_id))
        manager.connect("test")
        service = DashboardService(manager, "test")
        task = asyncio.create_task(service.poll_once())
        await asyncio.sleep(0.005)
        self.assertFalse(task.done())
        self.assertEqual((await task).quality, ReadingQuality.GOOD)

    def test_generic_ui_does_not_own_chamber_or_driver(self):
        source = (pathlib.Path(__file__).resolve().parents[1] /
                  "chamber_web" / "main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        self.assertNotIn("DemoChamber", source)
        self.assertNotIn("VotschTechnikClimateChamber", source)
        self.assertNotIn(".set_temperature(", source)
        self.assertNotIn(".start(", source)
        self.assertNotIn(".stop(", source)
        self.assertNotIn(".connect(", source)
        self.assertNotIn(".tick(", source)
        self.assertTrue(tree)
