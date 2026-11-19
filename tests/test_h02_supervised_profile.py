"""H02-B part 2: supervised physical profile admission (mock backends only).

No test in this module touches hardware or VotschBackend; the "physical" path
is exercised against a mock backend that carries the explicit supervised HIL
authorization marker, mirroring the H01 launch gate.
"""
from __future__ import annotations

import base64
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from chamber_web.adapters.fake import FakeBackend
from chamber_web.domain.chamber import ChamberSafetyError
from chamber_web.domain.config import ChamberConfig
from chamber_web.domain.profile import ParsedProfile, ProfileStep
from chamber_web.execution.profile_runner import (
    TERMINAL, ProfileRunner, RunParameters, RunState, SupervisedRun, VirtualClock,
)
from chamber_web.hil.profile_admission import AdmissionDenied, H02WatchdogLimits
from chamber_web.hil.supervised_profile import (
    ENV_PERMIT_FILE, ENV_TRUSTED_KEY,
    SupervisedProfilePermit, SupervisedProfileRuntime, decode_trusted_key,
    load_supervised_permit, supervised_runtime_from_env,
)
from chamber_web.persistence.profiles import ProfileStore
from chamber_web.security.auth import (
    AuthenticationError, AuthorizationError, SecurityStore,
)
from chamber_web.services.chamber_manager import ChamberManager
from chamber_web.services.profile_execution import ProfileExecutionService

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
except ImportError:
    Ed25519PrivateKey = None

CHAMBER = "unit-chamber"
SERIAL = "SN-H02-1"
GUI_COMMIT = "b" * 40
DRIVER_COMMIT = "c" * 40
WITNESS = "witness-1"


def step(target="25", *, stabilize="0", dwell="0", reach="20", up=None, down=None,
         chamber_run="ON", compressed_air="UNCHANGED", dryer="UNCHANGED", outputs=()):
    return ProfileStep(
        1, True, Decimal(target),
        Decimal(up) if up is not None else None,
        Decimal(down) if down is not None else None,
        Decimal("1"), Decimal(stabilize), Decimal(dwell),
        Decimal(reach), "test", chamber_run, compressed_air, dryer, outputs,
    )


def limits():
    return H02WatchdogLimits(
        1, 2.0, 2.0, 5.0, 120.0, 240.0, 5.0, 2.0, 2.0, 5.0, 10.0,
    )


class AdvancingSampleTime:
    """Keep distinct simulated observations from aliasing on Windows clocks."""

    def read_status(self):
        sample = super().read_status()
        if sample.sampled_at_utc is None:
            return sample
        previous = getattr(self, "_last_test_sample_utc", None)
        stamped = sample.sampled_at_utc
        if previous is not None and stamped <= previous:
            stamped = previous + timedelta(microseconds=1)
        self._last_test_sample_utc = stamped
        return replace(sample, sampled_at_utc=stamped)


class PhysicalLikeFake(AdvancingSampleTime, FakeBackend):
    """Mock marked as explicitly authorized live hardware; records commands."""

    simulation_only = False
    physical_authorized = True

    def __init__(self, chamber_id, **kwargs):
        super().__init__(chamber_id, **kwargs)
        self.commands = []
        # Keep the stored identity consistent with identify(); the controller
        # refuses readbacks whose identity differs from the connected device.
        self._identity = replace(self._identity, backend_id="votsch",
                                 serial_number=SERIAL, is_simulation=False)

    def start(self):
        self.commands.append("start")
        return super().start()

    def set_profile_running(self, running):
        self.commands.append(("set_profile_running", bool(running)))
        return super().set_profile_running(running)

    def set_digital_output(self, number, state):
        self.commands.append(("set_digital_output", number, bool(state)))
        return super().set_digital_output(number, state)


class DistinctFake(AdvancingSampleTime, FakeBackend):
    pass


class CaptureSink:
    def __init__(self):
        self.prepared = []
        self.events = []

    def prepare(self, snapshot):
        self.prepared.append(snapshot)

    def emit(self, event):
        self.events.append(event)


class SignedPermitFixture:
    """Build server-side signed permits around a saved profile revision."""

    def __init__(self, store, *, profile=None, operator="test_admin"):
        self.store = store
        self.private = Ed25519PrivateKey.generate()
        self.public = self.private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        header = store.create_profile(
            CHAMBER, profile or ParsedProfile((step(),), name="supervised"))
        self.profile_id = header.profile_id
        self.revision_sha = store.get_revision(
            CHAMBER, self.profile_id, revision=1,
        ).sha256
        now = datetime.now(timezone.utc)
        self.permit = {
            "schema_version": 1,
            "scope": "H02_SUPERVISED_PHYSICAL_PROFILE",
            "site_method": "SITE-H02-01", "approval_reference": "SIGNED-SITE-H02-01",
            "chamber_id": CHAMBER, "serial_number": SERIAL,
            "profile_id": self.profile_id, "profile_revision_sha256": self.revision_sha,
            "gui_commit": GUI_COMMIT, "driver_commit": DRIVER_COMMIT,
            "operator": operator, "witness": WITNESS,
            "specimen_restrictions": "Empty chamber, witness present",
            "temperature_min_c": 22.0, "temperature_max_c": 27.0,
            "valid_from_utc": (now - timedelta(minutes=2)).isoformat(),
            "valid_until_utc": (now + timedelta(hours=1)).isoformat(),
            "watchdog": asdict(limits()),
        }

    def signed(self, mutate=None):
        data = dict(self.permit)
        if mutate is not None:
            mutate(data)
        payload = json.dumps(data, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode("utf-8")
        return {
            "permit": data,
            "signature_base64": base64.b64encode(self.private.sign(payload)).decode("ascii"),
        }

    def write(self, directory: Path, mutate=None) -> Path:
        path = directory / "h02-permit.json"
        path.write_text(json.dumps(self.signed(mutate)), encoding="utf-8")
        return path

    def load(self, directory: Path, mutate=None) -> SupervisedProfilePermit:
        path = self.write(directory, mutate)
        loaded = load_supervised_permit({
            ENV_PERMIT_FILE: str(path),
            ENV_TRUSTED_KEY: base64.b64encode(self.public).decode("ascii"),
        })
        assert loaded is not None
        return loaded


class SupervisedConfigTests(unittest.TestCase):
    def test_absent_configuration_keeps_supervised_disabled(self):
        self.assertIsNone(load_supervised_permit({}))
        self.assertIsNone(supervised_runtime_from_env({}, hil_present=False))
        self.assertIsNone(supervised_runtime_from_env(
            {ENV_PERMIT_FILE: "/missing", ENV_TRUSTED_KEY: "abc"}, hil_present=False,
        ))

    def test_partial_or_broken_configuration_fails_closed(self):
        with TemporaryDirectory() as tmp:
            missing = str(Path(tmp) / "absent.json")
            for env in (
                {ENV_PERMIT_FILE: missing},
                {ENV_TRUSTED_KEY: "A" * 43},
            ):
                with self.subTest(env=env), self.assertRaises(ChamberSafetyError):
                    load_supervised_permit(env)
            with self.assertRaises(ChamberSafetyError):
                supervised_runtime_from_env(
                    {ENV_PERMIT_FILE: missing, ENV_TRUSTED_KEY: "A" * 43},
                    hil_present=True,
                )

    def test_trusted_key_accepts_base64_and_hex_only(self):
        raw = bytes(range(32))
        self.assertEqual(decode_trusted_key(base64.b64encode(raw).decode()), raw)
        self.assertEqual(decode_trusted_key(raw.hex()), raw)
        for bad in ("", "not-a-key", base64.b64encode(b"short").decode(), "zz" * 32):
            with self.subTest(bad=bad), self.assertRaises(ChamberSafetyError):
                decode_trusted_key(bad)

    def test_non_json_permit_file_fails_closed(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "permit.json"
            path.write_text("not json", encoding="utf-8")
            with self.assertRaises(ChamberSafetyError):
                load_supervised_permit({
                    ENV_PERMIT_FILE: str(path),
                    ENV_TRUSTED_KEY: base64.b64encode(bytes(32)).decode(),
                })

    @unittest.skipIf(Ed25519PrivateKey is None, "cryptography not installed")
    def test_runtime_binds_verified_installed_commits_not_saved_text(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = ProfileStore(root / "profiles.sqlite")
            fixture = SignedPermitFixture(store)
            path = fixture.write(root)
            env = {
                ENV_PERMIT_FILE: str(path),
                ENV_TRUSTED_KEY: base64.b64encode(fixture.public).decode(),
                "CHAMBER_H02_WITNESS": WITNESS,
                "CHAMBER_GUI_COMMIT": GUI_COMMIT,
                "CHAMBER_DRIVER_COMMIT": DRIVER_COMMIT,
            }
            with (
                patch("chamber_web.hil.supervised_profile.detect_gui_commit",
                      return_value=GUI_COMMIT),
                patch("chamber_web.hil.supervised_profile.detect_driver_commit",
                      return_value=DRIVER_COMMIT),
            ):
                runtime = supervised_runtime_from_env(env, hil_present=True)
                self.assertIsNotNone(runtime)
                self.assertEqual(runtime.gui_commit, GUI_COMMIT)
            with (
                patch("chamber_web.hil.supervised_profile.detect_gui_commit",
                      return_value=""),
                patch("chamber_web.hil.supervised_profile.detect_driver_commit",
                      return_value=DRIVER_COMMIT),
                self.assertRaises(ChamberSafetyError, msg="dirty checkout must fail"),
            ):
                supervised_runtime_from_env(env, hil_present=True)


class SupervisedRunnerTests(unittest.TestCase):
    """ProfileRunner-level supervised restrictions; mock physical backend."""

    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.clock = VirtualClock()
        self.backend = PhysicalLikeFake(CHAMBER)
        self.sink = CaptureSink()
        self.store = ProfileStore(self.root / "profiles.sqlite")

    def _connect(self, manager):
        manager.connect(CHAMBER)
        self.addCleanup(manager.disconnect, CHAMBER)
        return manager

    def _physical_manager(self):
        self.manager = self._connect(ChamberManager(
            [ChamberConfig(CHAMBER, "fake")],
            backend_factory=lambda config, **kwargs: self.backend,
            lease_directory=self.root / "lease",
        ))
        return self.manager

    def _runner(self, supervised, *, operator="test-operator"):
        manager = getattr(self, "manager", None) or self._physical_manager()
        runner = ProfileRunner(
            manager, self.store,
            authorize=lambda action, chamber, name=operator: name,
            sink=self.sink, clock=self.clock, supervised=supervised,
        )
        self.addCleanup(runner.close)
        return runner

    def _context(self, revalidate=None, operator="test-operator"):
        return SupervisedRun("a" * 64, operator, revalidate or (lambda: None))

    def _save(self, profile_step):
        return self.store.create_profile(
            CHAMBER, ParsedProfile((profile_step,), name="supervised"),
        ).profile_id

    def _drain(self, runner):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if runner.advance() in TERMINAL:
                break
            time.sleep(0.005)
        return runner.state

    def test_restricted_steps_are_refused_before_any_command(self):
        for bad in (
            step(chamber_run="OFF"),
            step(outputs=((2, True),)),
            step(compressed_air="ON"),
            step(dryer="ON"),
            step(up="2"),
            step(down="2"),
        ):
            with self.subTest(bad=bad):
                profile_id = self._save(bad)
                runner = self._runner(self._context())
                with self.assertRaises(ChamberSafetyError):
                    runner.start(CHAMBER, profile_id, revision=1)
                self.assertEqual(self.backend.commands, [])

    def test_run_is_bound_to_the_permit_operator(self):
        profile_id = self._save(step())
        runner = self._runner(self._context(), operator="someone-else")
        with self.assertRaises(ChamberSafetyError):
            runner.start(CHAMBER, profile_id, revision=1)

    def test_simulated_identity_is_refused_for_supervised_runs(self):
        manager = self._connect(ChamberManager(
            [ChamberConfig(CHAMBER, "fake")],
            backend_factory=lambda config, **kwargs: DistinctFake(CHAMBER),
            lease_directory=self.root / "lease-sim",
        ))
        runner = ProfileRunner(
            manager, self.store, authorize=lambda action, chamber: "test-operator",
            sink=self.sink, clock=self.clock, supervised=self._context(),
        )
        self.addCleanup(runner.close)
        profile_id = self._save(step())
        with self.assertRaises(ChamberSafetyError):
            runner.start(CHAMBER, profile_id, revision=1)

    def test_revalidation_failure_stops_before_dispatch(self):
        calls = []

        def revalidate():
            calls.append(1)
            raise AdmissionDenied("H02 permit expired")

        runner = self._runner(self._context(revalidate))
        snapshot = runner.start(CHAMBER, self._save(step()), revision=1)
        self.assertEqual(snapshot.identity.backend_id, "votsch")
        self.assertEqual(self._drain(runner), RunState.UNKNOWN)
        self.assertTrue(calls)
        self.assertEqual(self.backend.commands, [])
        self.assertIn("revalidation", runner.reason)
        self.assertTrue(self.manager.health(CHAMBER).stop_latched)

    def test_supervised_run_starts_once_through_certified_start(self):
        runner = self._runner(self._context())
        runner.start(CHAMBER, self._save(step()), revision=1)
        self.assertEqual(self._drain(runner), RunState.COMPLETED)
        self.assertEqual(self.backend.commands, ["start"])
        self.assertNotIn("set_profile_running", [c[0] for c in self.backend.commands
                                                 if isinstance(c, tuple)])


class StubSupervisionHost:
    """Healthy H02-C stand-in so part-2 tests keep their original scope."""

    def __init__(self):
        self.arms = []

    def alive(self) -> bool:
        return True

    def arm_run(self, **kwargs):
        self.arms.append(kwargs)


class SupervisedServiceTests(unittest.TestCase):
    """Service-level H02 admission with real signed permits (mock backend)."""

    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.security = SecurityStore(self.root / "auth")
        self.security.bootstrap_admin("test_admin", "StrongAdminPassword#1")
        self.operator = self.security.login("test_admin", "StrongAdminPassword#1")
        self.backend = PhysicalLikeFake(CHAMBER)
        self.manager = ChamberManager(
            [ChamberConfig(CHAMBER, "fake")],
            backend_factory=lambda config, **kwargs: self.backend,
            lease_directory=self.root / "ownership",
        )
        self.manager.connect(CHAMBER)
        self.addCleanup(self.manager.disconnect, CHAMBER)
        self.store = ProfileStore(self.root / "profiles.sqlite")
        self.fixture = SignedPermitFixture(self.store)

    def _runtime(self, permit, *, witness=WITNESS, supervisor_alive=lambda: True,
                 gui_commit=GUI_COMMIT, driver_commit=DRIVER_COMMIT,
                 supervision=None):
        if supervision is None:
            supervision = StubSupervisionHost()
        return SupervisedProfileRuntime(
            permit=permit, witness=witness, hil_acknowledged=True,
            supervisor_alive=supervisor_alive, gui_commit=gui_commit,
            driver_commit=driver_commit, supervision=supervision,
        )

    def _permit(self, mutate=None):
        return self.fixture.load(self.root, mutate)

    def _service(self, supervised, *, confirm=True):
        service = ProfileExecutionService(
            self.manager, self.store, self.security, CHAMBER,
            simulation=False, supervised=supervised,
            parameters=RunParameters(poll_s=0.05, max_gap_s=1, max_age_s=1),
        )
        if confirm and supervised is not None:
            service.confirm_physical_stop_procedure(
                self.operator.session, self.operator.csrf)

        def close_runner():
            runner = service.runner
            if runner is not None and runner.state in TERMINAL:
                runner.close()
        self.addCleanup(close_runner)
        return service

    def _drain(self, runner):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if runner.advance() in TERMINAL:
                break
            time.sleep(0.005)
        return runner.state

    def test_absent_supervision_keeps_physical_starts_disabled(self):
        service = self._service(None)
        with self.assertRaises(ChamberSafetyError):
            service.start(self.operator.session, self.operator.csrf,
                          self.fixture.profile_id, 1)
        self.assertIsNone(service.runner)

    def test_unconfirmed_stop_procedure_blocks_physical_start(self):
        """The launch-time HIL ack is not a human STOP-procedure confirmation."""
        service = self._service(self._runtime(self._permit()), confirm=False)
        view = service.view(self.operator.session)
        self.assertTrue(view.supervised)
        self.assertFalse(view.stop_procedure_confirmed)
        self.assertFalse(view.can_start)
        with self.assertRaises(AdmissionDenied):
            service.start(self.operator.session, self.operator.csrf,
                          self.fixture.profile_id, 1)
        self.assertIsNone(service.runner)
        self.assertEqual(self.backend.commands, [])
        # An explicit, audited operator act admits the run.
        service.confirm_physical_stop_procedure(
            self.operator.session, self.operator.csrf)
        self.assertTrue(service.view(self.operator.session).stop_procedure_confirmed)
        snapshot = service.start(self.operator.session, self.operator.csrf,
                                 self.fixture.profile_id, 1)
        self.assertEqual(snapshot.chamber_id, CHAMBER)
        self.assertEqual(self._drain(service.runner), RunState.COMPLETED)

    def test_stop_confirmation_requires_profile_run_permission(self):
        service = self._service(self._runtime(self._permit()), confirm=False)
        with self.assertRaises((AuthenticationError, AuthorizationError)):
            service.confirm_physical_stop_procedure(None, None)
        self.assertFalse(service.stop_procedure_confirmed("test_admin"))

    def test_supervised_start_admits_preflights_and_completes(self):
        service = self._service(self._runtime(self._permit()))
        view = service.view(self.operator.session)
        self.assertTrue(view.supervised)
        self.assertTrue(view.can_start, view.reason)
        snapshot = service.start(self.operator.session, self.operator.csrf,
                                 self.fixture.profile_id, 1)
        self.assertEqual(snapshot.chamber_id, CHAMBER)
        self.assertEqual(snapshot.identity.backend_id, "votsch")
        self.assertEqual(self._drain(service.runner), RunState.COMPLETED)
        self.assertEqual(self.backend.commands, ["start"])

    def test_simulated_composition_rejects_supervised_runtime(self):
        with self.assertRaises(ValueError):
            ProfileExecutionService(
                self.manager, self.store, self.security, CHAMBER,
                simulation=True, supervised=self._runtime(self._permit()),
            )

    def test_no_supervisor_witness_or_commit_mismatches_fail_closed(self):
        cases = (
            (lambda p: self._runtime(p, supervisor_alive=lambda: False), AdmissionDenied),
            (lambda p: self._runtime(p, witness="intruder"), AdmissionDenied),
            (lambda p: self._runtime(p, gui_commit="d" * 40), AdmissionDenied),
            (lambda p: self._runtime(p, driver_commit="d" * 40), AdmissionDenied),
        )
        for build, error in cases:
            with self.subTest(build=build):
                service = self._service(build(self._permit()))
                with self.assertRaises(error):
                    service.start(self.operator.session, self.operator.csrf,
                                  self.fixture.profile_id, 1)
                self.assertIsNone(service.runner)
                self.assertEqual(self.backend.commands, [])

    def test_wrong_operator_or_expired_permit_fail_closed(self):
        def other_operator(data):
            data["operator"] = "someone-else"

        service = self._service(
            self._runtime(self._permit(mutate=other_operator)))
        with self.assertRaises(AdmissionDenied):
            service.start(self.operator.session, self.operator.csrf,
                          self.fixture.profile_id, 1)
        self.assertIsNone(service.runner)

        def expired(data):
            now = datetime.now(timezone.utc)
            data["valid_from_utc"] = (now - timedelta(minutes=2)).isoformat()
            data["valid_until_utc"] = (now - timedelta(minutes=1)).isoformat()

        with self.assertRaises(AdmissionDenied):
            self._permit(mutate=expired)

    def test_mutating_or_out_of_envelope_profiles_fail_closed(self):
        cases = (
            ParsedProfile((step(chamber_run="OFF"),), name="off"),
            ParsedProfile((step(outputs=((2, True),)),), name="outputs"),
            ParsedProfile((step(up="2"),), name="ramped"),
            ParsedProfile((step(target="30"),), name="hot"),
        )
        for profile in cases:
            with self.subTest(profile=profile.name):
                fixture = SignedPermitFixture(self.store, profile=profile)
                service = self._service(self._runtime(fixture.load(self.root)))
                with self.assertRaises((AdmissionDenied, ChamberSafetyError)):
                    service.start(self.operator.session, self.operator.csrf,
                                  fixture.profile_id, 1)
                self.assertIsNone(service.runner)
                self.assertEqual(self.backend.commands, [])

    def test_permit_revalidation_detects_expiry_after_admission(self):
        permit = self._permit()
        permit.revalidate()
        with self.assertRaises(AdmissionDenied):
            permit.revalidate(now_utc=datetime.now(timezone.utc) + timedelta(hours=2))


if __name__ == "__main__":
    unittest.main()
