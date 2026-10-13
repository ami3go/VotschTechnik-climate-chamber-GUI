"""H01 mock-only verification (NOT physical HIL evidence)."""
import tempfile
import unittest
from pathlib import Path
from chamber_web.domain.chamber import ChamberSafetyError
from chamber_web.domain.config import ChamberConfig
from chamber_web.services.chamber_controller import ChamberController
from chamber_web.hil.faults import FaultInjectingFakeBackend

class H01SimulationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.fake = FaultInjectingFakeBackend("h01sim")
        self.ctrl = ChamberController(ChamberConfig(chamber_id="h01sim", backend_id="fake"), self.fake, lease_directory=Path(self.temp.name))
        self.ctrl.connect("h01sim")
        self.addCleanup(self.close)
        if self.ctrl.health.stop_latched:
            self.ctrl.reconcile_stop("h01sim")

    def close(self):
        try:
            self.ctrl.disconnect("h01sim")
        except Exception:
            pass

    def test_identity_remains_simulated(self):
        self.assertTrue(self.ctrl.status("h01sim").identity.is_simulation)

    def test_invalid_targets_do_not_write(self):
        for value in (float("nan"), float("inf"), -999, 999, True, "20"):
            with self.subTest(value=value):
                with self.assertRaises((ChamberSafetyError, TypeError)):
                    self.ctrl.set_temperature("h01sim", value)
        self.assertEqual(self.fake.write_count, 0)

    def test_wrong_id(self):
        with self.assertRaises(ChamberSafetyError):
            self.ctrl.start("other")

    def test_operator_conflict_and_stop_without_lease(self):
        token = self.ctrl.claim_operator("h01sim", "operator-A")
        with self.assertRaises(ChamberSafetyError):
            self.ctrl.claim_operator("h01sim", "operator-B")
        self.ctrl.start("h01sim", operator_token=token)
        self.ctrl.stop("h01sim")
        self.assertTrue(self.ctrl.health.stop_latched)
        with self.assertRaises(ChamberSafetyError):
            self.ctrl.set_temperature("h01sim", 24, operator_token=token)

    def test_timeout_fails_closed(self):
        self.fake.fail_readback = True
        with self.assertRaises(Exception):
            self.ctrl.status("h01sim")
        self.assertTrue(self.ctrl.health.stop_latched)

    def test_stale_readback_fails_closed(self):
        self.fake.stale_readback = True
        with self.assertRaises(ChamberSafetyError):
            self.ctrl.set_temperature("h01sim", 24)
        self.assertTrue(self.ctrl.health.stop_latched)

    def test_target_mismatch_fails_closed(self):
        self.fake.mismatch_target = True
        with self.assertRaises(ChamberSafetyError):
            self.ctrl.set_temperature("h01sim", 24)
        self.assertTrue(self.ctrl.health.stop_latched)

    def test_ambiguous_stop_does_not_claim_success(self):
        self.fake.fail_stop = True
        with self.assertRaises(Exception):
            self.ctrl.stop("h01sim")
        self.assertTrue(self.ctrl.health.stop_latched)
        self.assertIn(self.ctrl.health.state, ("UNKNOWN", "FAULT", "STOP_REQUESTED"))

    def test_non_simulated_backend_connect_denied_pre_io(self):
        class NonSimulated(FaultInjectingFakeBackend):
            simulation_only = False
            def connect(self):
                raise AssertionError("must never dispatch")
        c = ChamberController(ChamberConfig(chamber_id="blocked", backend_id="fake"), NonSimulated("blocked"), lease_directory=Path(self.temp.name))
        with self.assertRaisesRegex(ChamberSafetyError, "Physical hardware I/O DISABLED"):
            c.connect("blocked")

if __name__ == "__main__":
    unittest.main()
