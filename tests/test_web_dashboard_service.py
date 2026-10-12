"""G02-A shared-service/abstraction tests; all adapter I/O is simulated."""
import ast
import pathlib
import unittest
from dataclasses import replace

from chamber_web.adapters.alternate_stub import AlternateStubBackend
from chamber_web.adapters.fake import FakeBackend
from chamber_web.adapters.registry import make_backend
from chamber_web.adapters.votsch import VotschBackend
from chamber_web.bootstrap import get_dashboard_service
from chamber_web.domain.chamber import (
    ChamberConnectionError, ChamberSafetyError, OperationState, ReadingQuality,
)
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

    def start(self):
        self.is_running = True

    def stop(self):
        self.is_running = False


class ReadFaultFake(FakeBackend):
    fail = False

    def read_status(self):
        if self.fail:
            raise ChamberConnectionError("test read fault")
        return super().read_status()


class NonGoodFake(FakeBackend):
    def read_status(self):
        snapshot = super().read_status()
        return replace(snapshot, quality=ReadingQuality.STALE,
                       operation_state=OperationState.RUNNING,
                       measured_temperature_c=42.0)


def setup_dashboard(config, factory=make_backend, *, allow_test_backend=False,
                    history_limit=240):
    manager = ChamberManager([config], backend_factory=factory,
                             allow_test_backend=allow_test_backend)
    service = DashboardService(manager, config.chamber_id, history_limit=history_limit)
    service.connect()
    return manager, service


class DashboardServiceTests(unittest.TestCase):
    def test_runtime_fixed_to_server_shared_fake(self):
        first = get_dashboard_service()
        second = get_dashboard_service()
        self.assertIs(first, second)
        view = first.read(first.chamber_id)
        self.assertEqual(view.snapshot.identity.backend_id, "fake")
        self.assertTrue(view.snapshot.identity.is_simulation)
        self.assertEqual(view.snapshot.quality, ReadingQuality.GOOD)
        self.assertFalse(hasattr(first, "start"))
        self.assertFalse(hasattr(first, "set_temperature"))
        self.assertFalse(hasattr(first, "stop"))

    def test_shared_state_survives_page_view_discard(self):
        manager, service = setup_dashboard(ChamberConfig("test-shared", "fake"))
        first = service.read("test-shared")
        self.assertEqual(first.snapshot.operation_state, OperationState.STOPPED)
        del first
        manager.start("test-shared")  # test injection; no UI hardware command
        second = service.read("test-shared")
        self.assertEqual(second.snapshot.operation_state, OperationState.RUNNING)

    def test_sequential_adapter_substitution_no_manufacturer_branches(self):
        fixtures = [
            (ChamberConfig("fake-test", "fake"), make_backend, False, -40, 130),
            (ChamberConfig("other-test", "alternate_stub"), make_backend, True, -10, 50),
            (ChamberConfig("votsch-mock", "votsch", "mock.invalid"),
             lambda config, **_kw: VotschBackend(
                 config.chamber_id, config.address or "",
                 mock_driver_factory=MockDriver,
             ), False, -20, 80),
        ]
        for config, factory, allow_test, min_temp, max_temp in fixtures:
            with self.subTest(backend=config.backend_id):
                manager, service = setup_dashboard(
                    config, factory, allow_test_backend=allow_test,
                )
                view = service.read(config.chamber_id)
                self.assertTrue(view.snapshot.identity.is_simulation)
                self.assertEqual(view.snapshot.identity.chamber_id, config.chamber_id)
                self.assertEqual(view.capabilities.temperature_min_c, min_temp)
                self.assertEqual(view.capabilities.temperature_max_c, max_temp)
                manager.start(config.chamber_id)  # simulated test fixture ONLY
                self.assertEqual(service.read(config.chamber_id).snapshot.operation_state,
                                 OperationState.RUNNING)
                manager.disconnect(config.chamber_id)

    def test_wrong_id_never_dispatches(self):
        _, service = setup_dashboard(ChamberConfig("correct-id", "fake"))
        with self.assertRaisesRegex(ChamberSafetyError, "Wrong/stale"):
            service.read("stale-id")
        with self.assertRaisesRegex(ChamberSafetyError, "bind"):
            DashboardService(
                ChamberManager([ChamberConfig("correct-id", "fake")],
                               backend_factory=make_backend),
                "stale-id",
            )

    def test_fault_never_reuses_good_measurement(self):
        backend = ReadFaultFake("fault-test")
        manager, service = setup_dashboard(
            ChamberConfig("fault-test", "fake"),
            lambda _config, **_kw: backend,
        )
        good = service.read("fault-test")
        self.assertIsNotNone(good.snapshot.measured_temperature_c)
        backend.fail = True
        failed = service.read("fault-test")
        self.assertEqual(failed.snapshot.operation_state, OperationState.UNKNOWN)
        self.assertEqual(failed.snapshot.quality, ReadingQuality.ERROR)
        self.assertIsNone(failed.snapshot.measured_temperature_c)
        self.assertIsNone(failed.snapshot.sampled_at_utc)
        self.assertEqual(failed.error, "Status unavailable: ChamberConnectionError")
        self.assertEqual(len(failed.observations), len(good.observations))
        manager.disconnect("fault-test")

    def test_stale_quality_does_not_display_current_temperature(self):
        backend = NonGoodFake("stale-test")
        _, service = setup_dashboard(
            ChamberConfig("stale-test", "fake"),
            lambda _config, **_kw: backend,
        )
        view = service.read("stale-test")
        self.assertEqual(view.snapshot.quality, ReadingQuality.STALE)
        self.assertEqual(view.snapshot.operation_state, OperationState.UNKNOWN)
        self.assertIsNone(view.snapshot.measured_temperature_c)
        self.assertIsNone(view.snapshot.setpoint_temperature_c)
        self.assertFalse(view.observations)

    def test_identity_change_fails_closed(self):
        backend = FakeBackend("identity-test")
        _, service = setup_dashboard(
            ChamberConfig("identity-test", "fake"),
            lambda _config, **_kw: backend,
        )
        backend._identity = AlternateStubBackend("identity-test").identify()
        result = service.read("identity-test")
        self.assertEqual(result.snapshot.operation_state, OperationState.UNKNOWN)
        self.assertIsNone(result.snapshot.measured_temperature_c)
        self.assertEqual(result.error, "Status unavailable: ChamberSafetyError")

    def test_bounded_server_observations(self):
        _, service = setup_dashboard(ChamberConfig("bounded-test", "fake"), history_limit=3)
        for _ in range(15):
            view = service.read("bounded-test")
        self.assertEqual(len(view.observations), 3)
        self.assertTrue(all(sample.measured_temperature_c is not None
                            for sample in view.observations))

    def test_no_page_simulator_or_adapter_import(self):
        root = pathlib.Path(__file__).resolve().parents[1] / "chamber_web"
        source = (root / "main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = [node for node in ast.walk(tree)
                   if isinstance(node, (ast.Import, ast.ImportFrom))]
        for node in imports:
            module = node.module or "" if isinstance(node, ast.ImportFrom) else ""
            self.assertFalse(module.startswith("chamber_web.adapters"))
        self.assertNotIn("DemoChamber(", source)
        self.assertNotIn("state.tick()", source)
