"""G03-A canonical/legacy CSV and ZIP boundary tests (no chamber I/O)."""
import io
import hashlib
import json
import unittest
from decimal import Decimal
from zipfile import ZipFile, ZIP_DEFLATED

from chamber_web.domain.profile import (
    ParsedProfile, ProfileStep, export_profile_csv, export_profile_zip,
    import_profile_zip, parse_profile_csv,
)

LEGACY = (
    b"target,ramp,tolerance,dwell,description,enabled\n"
    b"25,5,1,60,=2+2,True\n"
    b"-20,3,1,120,Cold soak,True\n"
)


class ProfileV1Tests(unittest.TestCase):
    def setUp(self):
        self.profile = parse_profile_csv(
            LEGACY, legacy_reach_timeout_s=Decimal("3600")
        )

    def test_legacy_requires_explicit_reach_deadline(self):
        with self.assertRaisesRegex(ValueError, "operator-provided"):
            parse_profile_csv(LEGACY)

    def test_legacy_ramps_never_infer_hardware_slopes(self):
        self.assertTrue(all(
            step.ramp_up_c_per_min is None and step.ramp_down_c_per_min is None
            for step in self.profile.steps
        ))
        self.assertEqual(self.profile.steps[0].reach_timeout_s, Decimal("3600"))

    def test_machine_csv_preserves_formula_text(self):
        csv_data = export_profile_csv(self.profile)
        parsed = parse_profile_csv(csv_data)
        self.assertEqual(parsed.steps, self.profile.steps)
        self.assertIn(b"=2+2", csv_data)

    def test_spreadsheet_export_is_separate_and_escaped(self):
        safe = export_profile_csv(self.profile, spreadsheet_safe=True)
        self.assertIn(b"'=2+2", safe)
        self.assertNotEqual(safe, export_profile_csv(self.profile))

    def test_zip_preserves_exact_legacy_bytes(self):
        bundle = export_profile_zip(self.profile)
        parsed = import_profile_zip(bundle)
        self.assertEqual(parsed.legacy_original, LEGACY)
        self.assertEqual(parsed.steps, self.profile.steps)

    def test_bundle_preserves_profile_level_settings(self):
        profile = ParsedProfile(
            self.profile.steps, self.profile.legacy_original,
            self.profile.migration_warning, "Cycle X", "thermal soak", 4, "STOP",
        )
        restored = import_profile_zip(export_profile_zip(profile))
        self.assertEqual(restored, profile)

    def test_unapproved_completion_action_rejected(self):
        profile = ParsedProfile(
            self.profile.steps, name="Trial", completion_action="HOLD_SETPOINT",
        )
        with self.assertRaisesRegex(ValueError, "STOP"):
            export_profile_zip(profile)

    def test_bad_digest_is_rejected(self):
        bundle = export_profile_zip(self.profile)
        with ZipFile(io.BytesIO(bundle)) as original:
            items = {name: original.read(name) for name in original.namelist()}
        items["profile.csv"] = items["profile.csv"].replace(b"25", b"26", 1)
        output = io.BytesIO()
        with ZipFile(output, "w", ZIP_DEFLATED) as archive:
            for name, content in items.items():
                archive.writestr(name, content)
        with self.assertRaisesRegex(ValueError, "checksum"):
            import_profile_zip(output.getvalue())

    def test_zip_traversal_rejected(self):
        output = io.BytesIO()
        with ZipFile(output, "w") as archive:
            archive.writestr("../unsafe.csv", b"oops")
            archive.writestr("profile.csv", b"x")
            archive.writestr("profile.json", b"{}")
        with self.assertRaisesRegex(ValueError, "allowlisted"):
            import_profile_zip(output.getvalue())

    def test_bad_v1_numeric_input_fails(self):
        data = export_profile_csv(self.profile).replace(b"3600", b"NaN", 1)
        with self.assertRaises(ValueError):
            parse_profile_csv(data)

    def test_disabled_only_rejected(self):
        data = LEGACY.replace(b",True", b",False")
        with self.assertRaisesRegex(ValueError, "enabled"):
            parse_profile_csv(data, legacy_reach_timeout_s=Decimal("3600"))

    def test_legacy_roundtrip_never_auto_enables_gradient(self):
        data = export_profile_zip(self.profile)
        restored = import_profile_zip(data)
        self.assertTrue(all(s.ramp_up_c_per_min is None for s in restored.steps))

    def test_v2_output_directives_round_trip_and_v1_remains_compatible(self):
        base = self.profile.steps[0]
        controlled = ProfileStep(
            base.step, base.enabled, base.target_temperature_c,
            base.ramp_up_c_per_min, base.ramp_down_c_per_min,
            base.tolerance_c, base.stabilize_s, base.dwell_s,
            base.reach_timeout_s, base.notes, "OFF", "ON", "OFF",
            ((2, True), (6, False)),
        )
        profile = ParsedProfile((controlled,), name="Output cycle")
        csv_data = export_profile_csv(profile)
        self.assertIn(b"chamber_run,compressed_air,dryer,digital_outputs", csv_data)
        self.assertEqual(parse_profile_csv(csv_data).steps, profile.steps)
        self.assertEqual(import_profile_zip(export_profile_zip(profile)), profile)

        v1 = csv_data.splitlines()
        keep = list(range(9)) + [13]
        v1_data = b"\n".join(
            b",".join(row.split(b",")[index] for index in keep) for row in v1
        ) + b"\n"
        migrated = parse_profile_csv(v1_data)
        self.assertEqual(migrated.steps[0].chamber_run, "ON")
        self.assertEqual(migrated.steps[0].compressed_air, "UNCHANGED")

        with ZipFile(io.BytesIO(export_profile_zip(profile))) as current:
            manifest = json.loads(current.read("profile.json"))
        manifest["schema_version"] = 1
        manifest["profile_csv_sha256"] = hashlib.sha256(v1_data).hexdigest()
        old_bundle = io.BytesIO()
        with ZipFile(old_bundle, "w", ZIP_DEFLATED) as archive:
            archive.writestr("profile.csv", v1_data)
            archive.writestr("profile.json", json.dumps(manifest).encode())
        restored_v1 = import_profile_zip(old_bundle.getvalue())
        self.assertEqual(restored_v1.steps[0].chamber_run, "ON")

    def test_numbered_output_syntax_is_strict_and_named_outputs_are_reserved(self):
        csv_data = export_profile_csv(self.profile)
        with self.assertRaisesRegex(ValueError, "outputs 1, 7 and 8"):
            parse_profile_csv(csv_data.replace(b",UNCHANGED,UNCHANGED,,", b",UNCHANGED,UNCHANGED,7=ON,"))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            parse_profile_csv(csv_data.replace(b",UNCHANGED,UNCHANGED,,", b",UNCHANGED,UNCHANGED,2=ON;2=OFF,"))


if __name__ == "__main__":
    unittest.main()
