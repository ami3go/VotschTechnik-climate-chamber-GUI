import unittest

from chamber_web.model import (
    DemoChamber, Step, default_steps, export_profile_csv,
    import_profile_csv, validate_steps,
)


class ProfileCsvTests(unittest.TestCase):
    def test_round_trip(self):
        profile = default_steps()
        profile[2].description = "Hot soak, release"
        self.assertEqual(import_profile_csv(export_profile_csv(profile)), profile)

    def test_bad_header(self):
        with self.assertRaises(ValueError):
            import_profile_csv("target,dwell\n25,300\n")

    def test_invalid_enabled(self):
        with self.assertRaises(ValueError):
            import_profile_csv("target,ramp,tolerance,dwell,description,enabled\n"
                               "25,5,1,60,test,maybe\n")

    def test_out_of_range_and_nonfinite(self):
        for value in ("200", "nan", "inf", "-inf"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    import_profile_csv("target,ramp,tolerance,dwell,description,enabled\n"
                                       f"{value},5,1,60,test,True\n")

    def test_unsafe_formula_description_export(self):
        with self.assertRaisesRegex(ValueError, "formula"):
            export_profile_csv([Step(25, 5, 1, 60, "=1+1")])

    def test_atomic_validation(self):
        with self.assertRaises(ValueError):
            validate_steps([Step(25, 5, 1, 60, "off", False)])

    def test_dwell_must_be_integral(self):
        with self.assertRaises(ValueError):
            import_profile_csv("target,ramp,tolerance,dwell,description,enabled\n"
                               "25,5,1,2.5,test,True\n")

    def test_csv_with_bom(self):
        self.assertEqual(import_profile_csv("\ufeff" + export_profile_csv(default_steps())),
                         default_steps())


class DemoTests(unittest.TestCase):
    def test_starts_stopped_with_no_real_connection(self):
        demo = DemoChamber()
        self.assertFalse(demo.running)
        self.assertEqual(demo.status, "Stopped")
        self.assertFalse(demo.samples)

    def test_snapshot_not_mutated_after_start(self):
        demo = DemoChamber()
        demo.start()
        demo.steps[0].target = 99
        self.assertEqual(demo.run_steps[0].target, 25)

    def test_stop_and_hold(self):
        demo = DemoChamber()
        demo.start()
        demo.hold()
        self.assertEqual(demo.status, "Held")
        old = demo.current
        demo.tick()
        self.assertEqual(demo.current, old)
        demo.hold()
        demo.stop()
        self.assertEqual(demo.status, "Stopped")

    def test_skip_disabled_steps(self):
        demo = DemoChamber()
        demo.steps = [Step(23.4, 5, 1, 0, "one"), Step(45, 5, 1, 10, "skip", False),
                      Step(23.4, 5, 1, 0, "final")]
        demo.start()
        demo.tick()
        self.assertEqual(demo.step_index, 2)
        demo.tick()
        self.assertTrue(demo.completed)


if __name__ == "__main__":
    unittest.main()
