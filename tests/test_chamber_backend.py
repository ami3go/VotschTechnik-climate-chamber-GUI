"""G01 contract/safety tests. No physical connections are initiated."""
import ast
import pathlib
import unittest

from chamber_web.adapters.alternate_stub import AlternateStubBackend
from chamber_web.adapters.fake import FakeBackend
from chamber_web.domain.config import ChamberConfig
from chamber_web.adapters.registry import make_backend
from chamber_web.adapters.votsch import VotschBackend
from chamber_web.domain.chamber import (
    ChamberSafetyError, OperationState, ReadingQuality, UnsupportedCapability,
)
from chamber_web.services.chamber_manager import ChamberManager


class FakeDriver:
    test_system_type = "VT4011-MOCK"
    serial_number = "SIM-1"
    temperature_measured = 25.0
    temperature_set_point = 25.0
    is_running = False

    def __init__(self):
        self.outputs = {number: False for number in range(1, 9)}
        self.calls = []

    def disconnect(self):
        pass

    def start(self):
        self.is_running = True
        self.outputs[1] = True

    def stop(self):
        self.is_running = False
        self.outputs[1] = False

    def read_digital_output(self, number):
        self.calls.append(("read", number))
        return self.outputs[number]

    def set_digital_output(self, number, state):
        self.calls.append(("set", number, state))
        self.outputs[number] = state


class BackendContractTests(unittest.TestCase):
    def test_votsch_typed_numbered_output_api_is_used(self):
        driver = FakeDriver()
        backend = VotschBackend("chamber-c", "mock.invalid",
                                mock_driver_factory=lambda: driver)
        backend.connect()
        self.addCleanup(backend.disconnect)
        backend.set_digital_output(2, True)
        self.assertTrue(backend.read_digital_output(2))
        backend.set_digital_output(2, False)
        self.assertFalse(backend.read_digital_output(2))
        self.assertEqual(driver.calls, [
            ("set", 2, True), ("read", 2), ("set", 2, False), ("read", 2),
        ])
        with self.assertRaises(UnsupportedCapability):
            backend.set_digital_output(65, True)

    def test_three_backends_sequential_contract(self):
        backends = (
            FakeBackend("chamber-a"),
            AlternateStubBackend("chamber-b"),
            VotschBackend("chamber-c", "mock.invalid", mock_driver_factory=FakeDriver),
        )
        for backend in backends:
            with self.subTest(backend=type(backend).__name__):
                backend.connect()
                identity = backend.identify()
                self.assertTrue(identity.is_simulation)
                self.assertEqual(backend.read_status().quality, ReadingQuality.GOOD)
                caps = backend.capabilities()
                backend.set_temperature(max(caps.temperature_min_c, 25))
                backend.start()
                self.assertEqual(backend.read_status().operation_state, OperationState.RUNNING)
                backend.stop()
                self.assertEqual(backend.read_status().operation_state, OperationState.STOPPED)
                with self.assertRaises(UnsupportedCapability):
                    backend.set_ramp_up(1)
                backend.disconnect()

    def test_strict_cardinality_before_io(self):
        with self.assertRaisesRegex(ChamberSafetyError, "multiple physical"):
            ChamberManager([
                ChamberConfig("a", "votsch", "192.0.2.1"),
                ChamberConfig("b", "votsch", "192.0.2.2"),
            ], backend_factory=make_backend)

    def test_wrong_device_never_dispatches(self):
        manager = ChamberManager([ChamberConfig("ch1", "fake")], backend_factory=make_backend)
        manager.connect("ch1")
        self.addCleanup(manager.disconnect, "ch1")
        for command in (
            lambda: manager.start("other"),
            lambda: manager.set_temperature("other", 30),
            lambda: manager.stop("other"),
            lambda: manager.disconnect("other"),
        ):
            with self.assertRaises(ChamberSafetyError):
                command()
        self.assertEqual(manager.status("ch1").operation_state, OperationState.STOPPED)

    def test_manager_does_not_expose_backend_bypass(self):
        manager = ChamberManager([ChamberConfig("ch1", "fake")], backend_factory=make_backend)
        self.assertIs(manager.get("ch1"), manager)
        # Gradients, like every other mutation, go through the managed
        # controller; no raw backend (or backend handle) is exposed.
        self.assertFalse(hasattr(manager, "_backend"))
        self.assertTrue(callable(manager.set_ramp_up))
        self.assertTrue(callable(manager.set_ramp_down))

    def test_stop_latch_blocks_old_commands(self):
        manager = ChamberManager([ChamberConfig("ch1", "fake")], backend_factory=make_backend)
        manager.connect("ch1")
        self.addCleanup(manager.disconnect, "ch1")
        manager.start("ch1")
        manager.stop("ch1")
        with self.assertRaises(ChamberSafetyError):
            manager.set_temperature("ch1", 45)
        manager.reconcile_stop("ch1")
        manager.set_temperature("ch1", 45)

    def test_physical_driver_cannot_connect_in_g01(self):
        manager = ChamberManager([ChamberConfig("vt4011", "votsch", "192.0.2.20")], backend_factory=make_backend)
        with self.assertRaisesRegex(ChamberSafetyError, "DISABLED"):
            manager.connect("vt4011")

    def test_generic_core_never_branches_on_vendor_name(self):
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1] / "chamber_web"
        for relative in ("domain/config.py", "services/chamber_manager.py"):
            source = (root / relative).read_text(encoding="utf-8")
            self.assertNotIn("== \"votsch\"", source)
            self.assertNotIn("== 'votsch'", source)

    def test_test_backend_not_available_in_production(self):
        with self.assertRaises(ChamberSafetyError):
            ChamberManager([ChamberConfig("st1", "alternate_stub")], backend_factory=make_backend)
        manager = ChamberManager([ChamberConfig("st1", "alternate_stub")],
                                 backend_factory=make_backend, allow_test_backend=True)
        manager.connect("st1")
        self.addCleanup(manager.disconnect, "st1")
        with self.assertRaises(ChamberSafetyError):
            manager.set_temperature("st1", 100)

    def test_architecture_import_boundary(self):
        root = pathlib.Path(__file__).resolve().parents[1] / "chamber_web"
        for file in root.rglob("*.py"):
            if file.relative_to(root).as_posix() == "adapters/votsch.py":
                continue
            tree = ast.parse(file.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    for alias in (node.names if isinstance(node, ast.Import) else
                                  [type("A", (), {"name": node.module or ""})()]):
                        self.assertFalse(alias.name.startswith("VotschTechnikClimateChamber"),
                                         f"illegal driver import in {file}")
                if isinstance(node, ast.ImportFrom) and file.parent.name in {
                    "services", "domain", "execution", "pages", "persistence"
                }:
                    self.assertFalse((node.module or "").startswith("chamber_web.adapters"),
                                     f"illegal vendor dependency in {file}")


if __name__ == "__main__":
    unittest.main()
