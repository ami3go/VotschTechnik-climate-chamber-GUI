"""H02 software-only permit tests. Never instantiate VotschBackend or hardware."""
from __future__ import annotations

import base64
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import json
import unittest

from chamber_web.domain.chamber import ChamberIdentity
from chamber_web.hil.profile_admission import (
    AdmissionDenied, H02LiveChecks, H02WatchdogLimits, preflight_physical_profile,
    verify_signed_permit,
)

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
except ImportError:
    Ed25519PrivateKey = None


def limits():
    return H02WatchdogLimits(
        1, 2.0, 2.0, 5.0, 120.0, 240.0, 5.0, 2.0, 2.0, 5.0, 10.0,
    )


class PermitSafetyTests(unittest.TestCase):
    def test_nonfinite_and_unbounded_limits(self):
        for bad in (float("nan"), float("inf"), -1, 0, True):
            with self.subTest(bad=bad), self.assertRaises(AdmissionDenied):
                replace(limits(), whole_profile_deadline_s=bad)
        with self.assertRaises(AdmissionDenied):
            replace(limits(), max_telemetry_gap_s=5.01)
        with self.assertRaises(AdmissionDenied):
            replace(limits(), readback_deadline_s=5.01)
        with self.assertRaises(AdmissionDenied):
            replace(limits(), profile_step_deadline_s=300.0)
        with self.assertRaises(AdmissionDenied):
            H02WatchdogLimits.from_dict({"schema_version": 1})

    def test_live_checks_refuse_unknown(self):
        checks = H02LiveChecks(*(True for _ in range(9)))
        checks.require_all()
        for field in checks.__dataclass_fields__:
            with self.subTest(field=field), self.assertRaises(AdmissionDenied):
                replace(checks, **{field: False}).require_all()

    @unittest.skipUnless(Ed25519PrivateKey is not None, "cryptography is unavailable; fail closed")
    def test_signed_permit_scope_and_identity(self):
        private = Ed25519PrivateKey.generate()
        public = private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        now = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
        permit = {
            "schema_version": 1,
            "scope": "H02_SUPERVISED_PHYSICAL_PROFILE",
            "site_method": "SITE-H02-01", "approval_reference": "SIGNED-SITE-H02-01",
            "chamber_id": "hil-votsch", "serial_number": "S123",
            "profile_id": "profile-1", "profile_revision_sha256": "a" * 64,
            "gui_commit": "b" * 40, "driver_commit": "c" * 40,
            "operator": "operator-1", "witness": "witness-2",
            "specimen_restrictions": "Empty chamber, witness present",
            "temperature_min_c": 22.0, "temperature_max_c": 27.0,
            "valid_from_utc": (now - timedelta(minutes=2)).isoformat(),
            "valid_until_utc": (now + timedelta(hours=1)).isoformat(),
            "watchdog": asdict(limits()),
        }
        def signed(data):
            payload = json.dumps(data, sort_keys=True, separators=(",", ":"),
                                 ensure_ascii=False, allow_nan=False).encode("utf-8")
            return {"permit": data, "signature_base64": base64.b64encode(
                private.sign(payload)).decode("ascii")}
        doc = signed(permit)
        identity = ChamberIdentity("hil-votsch", "votsch", "Votsch", "VT4011", "S123")
        live = H02LiveChecks(*(True for _ in range(9)))
        kwargs = dict(
            trusted_site_public_key=public, live=live, identity=identity,
            profile_id="profile-1", profile_sha256="a"*64, gui_commit="b"*40,
            driver_commit="c"*40, operator="operator-1", witness="witness-2",
            targets_c=(23.0, 25.0), has_outputs_or_gradient_mutations=False,
            now_utc=now,
        )
        self.assertEqual(len(preflight_physical_profile(doc, **kwargs)), 64)
        with self.assertRaises(AdmissionDenied):
            preflight_physical_profile(doc, **{**kwargs, "identity": replace(identity, serial_number="OTHER")})
        with self.assertRaises(AdmissionDenied):
            preflight_physical_profile(doc, **{**kwargs, "targets_c": (31.0,)})
        with self.assertRaises(AdmissionDenied):
            preflight_physical_profile(doc, **{**kwargs, "has_outputs_or_gradient_mutations": True})
        with self.assertRaises(AdmissionDenied):
            preflight_physical_profile(doc, **{**kwargs, "live": replace(live, supervisor_alive=False)})
        with self.assertRaises(AdmissionDenied):
            preflight_physical_profile(doc, **{**kwargs, "operator": "another"})
        with self.assertRaises(AdmissionDenied):
            preflight_physical_profile(doc, **{**kwargs, "now_utc": now + timedelta(days=1)})
        with self.assertRaises(AdmissionDenied):
            preflight_physical_profile(doc, **{**kwargs, "trusted_site_public_key": b""})
        changed = {**permit, "scope": "H01_MANUAL_HIL"}
        with self.assertRaises(AdmissionDenied):
            verify_signed_permit(signed(changed), trusted_site_public_key=public, now_utc=now)
        with self.assertRaises(AdmissionDenied):
            verify_signed_permit({**doc, "permit": {**permit, "operator": "mallory"}},
                                 trusted_site_public_key=public, now_utc=now)
        with self.assertRaises(AdmissionDenied):
            verify_signed_permit(signed({**permit, "watchdog": {
                **permit["watchdog"], "max_telemetry_gap_s": 20.0,
            }}), trusted_site_public_key=public, now_utc=now)


if __name__ == "__main__":
    unittest.main()
