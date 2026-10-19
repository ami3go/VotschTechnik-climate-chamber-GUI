"""Offline tests of cross-platform environment setup (no network/hardware)."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import setup_environment as setup


class SetupEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ("requirements-web.txt", "requirements-hardware.txt", "requirements-dev.txt"):
            (self.root / name).write_text("# test\n", encoding="utf-8")

    def fake_venv(self, system="Linux"):
        python = setup.python_in_venv(self.root.resolve() / ".venv", system)
        python.parent.mkdir(parents=True, exist_ok=True)
        python.touch()
        return python

    def test_windows_uses_scripts_python_and_pinned_files(self):
        python = self.fake_venv("Windows")
        with (mock.patch.object(setup.platform, "system", return_value="Windows"),
              mock.patch.object(setup.shutil, "which", return_value="git.exe"),
              mock.patch.object(setup, "run_command") as run,
              mock.patch.object(setup, "verify_discovery_install") as verify):
            result = setup.install_environment(root=self.root, with_tests=True, with_browser=True)
        verify.assert_called_once_with(python, root=self.root.resolve())
        self.assertEqual(result, python)
        calls = [call.args[0] for call in run.call_args_list]
        self.assertEqual(len(calls), 5)
        self.assertTrue(all(cmd[0] == str(python) for cmd in calls))
        self.assertEqual([Path(cmd[-1]).name for cmd in calls[:3]],
                         ["requirements-web.txt", "requirements-hardware.txt", "requirements-dev.txt"])
        self.assertEqual(calls[3][-2:], ["pip", "check"])
        self.assertEqual(calls[4][-3:], ["playwright", "install", "chromium"])

    def test_linux_simulation_skips_git_and_driver(self):
        python = self.fake_venv()
        with (mock.patch.object(setup.platform, "system", return_value="Linux"),
              mock.patch.object(setup.shutil, "which", return_value=None),
              mock.patch.object(setup, "run_command") as run):
            result = setup.install_environment(root=self.root, include_driver=False)
        self.assertEqual(result, python)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(Path(run.call_args_list[0].args[0][-1]).name, "requirements-web.txt")

    def test_creates_platform_virtual_environment(self):
        # Exercise the real venv bootstrap without downloading packages.
        real_run = setup.run_command
        observed = []

        def intercept(command, *, cwd):
            observed.append(command)
            if command[1:3] == ["-m", "venv"]:
                real_run(command, cwd=cwd)

        with mock.patch.object(setup, "run_command", side_effect=intercept):
            python = setup.install_environment(root=self.root, include_driver=False)
        self.assertTrue(python.is_file())
        self.assertEqual(observed[0][1:3], ["-m", "venv"])
        self.assertEqual(observed[-1][-2:], ["pip", "check"])

    def test_missing_git_fails_before_install(self):
        with (mock.patch.object(setup.platform, "system", return_value="Linux"),
              mock.patch.object(setup.shutil, "which", return_value=None),
              mock.patch.object(setup, "run_command") as run):
            with self.assertRaisesRegex(RuntimeError, "Git is required"):
                setup.install_environment(root=self.root)
        run.assert_not_called()

    def test_invalid_existing_venv_is_not_overwritten(self):
        (self.root / ".venv").mkdir()
        with (mock.patch.object(setup.platform, "system", return_value="Linux"),
              mock.patch.object(setup, "run_command") as run):
            with self.assertRaisesRegex(RuntimeError, "not a valid"):
                setup.install_environment(root=self.root, include_driver=False)
        run.assert_not_called()

    def test_recreate_removes_only_a_real_virtual_environment(self):
        python = self.fake_venv()
        venv = python.parent.parent
        (venv / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
        (venv / "stale.txt").write_text("old", encoding="utf-8")

        def fake_run(command, *, cwd):
            if command[1:3] == ["-m", "venv"]:
                python.parent.mkdir(parents=True, exist_ok=True)
                python.touch()

        with (mock.patch.object(setup.platform, "system", return_value="Linux"),
              mock.patch.object(setup, "run_command", side_effect=fake_run) as run):
            setup.install_environment(root=self.root, include_driver=False, recreate=True)
        self.assertFalse((venv / "stale.txt").exists())
        self.assertEqual(run.call_args_list[0].args[0][1:3], ["-m", "venv"])

    def test_recreate_refuses_non_virtualenv_directory(self):
        target = self.root / "not-a-venv"
        target.mkdir()
        (target / "keep.txt").write_text("data", encoding="utf-8")
        with (mock.patch.object(setup.platform, "system", return_value="Linux"),
              mock.patch.object(setup, "run_command") as run,
              self.assertRaises(RuntimeError)):
            setup.install_environment(root=self.root, venv=target,
                                      include_driver=False, recreate=True)
        self.assertTrue((target / "keep.txt").exists())
        run.assert_not_called()

    def test_browser_requires_test_dependencies(self):
        with mock.patch.object(setup.platform, "system", return_value="Linux"):
            with self.assertRaisesRegex(ValueError, "requires --with-tests"):
                setup.install_environment(root=self.root, include_driver=False, with_browser=True)

    def test_unsupported_os_is_rejected(self):
        with mock.patch.object(setup.platform, "system", return_value="Darwin"):
            with self.assertRaisesRegex(RuntimeError, "Unsupported OS"):
                setup.install_environment(root=self.root, include_driver=False)

    def test_stale_driver_forces_one_reinstall_and_reverification(self):
        python = self.fake_venv()
        observations = []
        def verify(*args, **kwargs):
            observations.append(args[0])
            if len(observations) == 1:
                raise RuntimeError("Installed driver revision mismatch")
        with (mock.patch.object(setup.platform, "system", return_value="Linux"),
              mock.patch.object(setup.shutil, "which", return_value="git"),
              mock.patch.object(setup, "run_command") as run,
              mock.patch.object(setup, "verify_discovery_install", side_effect=verify)):
            self.assertEqual(setup.install_environment(root=self.root), python)
        self.assertEqual(observations, [python, python])
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(len(commands), 4)
        self.assertIn("--force-reinstall", commands[2])
        self.assertEqual(commands[2][-1], str(self.root / "requirements-hardware.txt"))

    def test_missing_driver_after_repair_is_a_setup_failure(self):
        self.fake_venv()
        with (mock.patch.object(setup.platform, "system", return_value="Linux"),
              mock.patch.object(setup.shutil, "which", return_value="git"),
              mock.patch.object(setup, "run_command") as run,
              mock.patch.object(setup, "verify_discovery_install",
                                side_effect=RuntimeError("discovery missing")) as verify):
            with self.assertRaisesRegex(RuntimeError, "discovery missing"):
                setup.install_environment(root=self.root)
        self.assertEqual(verify.call_count, 2)
        self.assertIn("--force-reinstall", run.call_args_list[-1].args[0])

    def test_check_driver_does_not_install_or_connect(self):
        python = setup.python_in_venv(setup.ROOT / ".venv", setup.platform.system())
        with (mock.patch.object(setup, "verify_discovery_install") as verify,
              mock.patch.object(setup, "install_environment") as install,
              mock.patch.object(setup.Path, "is_file", return_value=True)):
            self.assertEqual(setup.main(["--check-driver"]), 0)
            verify.assert_called_once()
            install.assert_not_called()

    def test_verify_driver_watchdog_reports_timeout(self):
        python = self.fake_venv()
        script = self.root / "scripts" / "verify_driver_install.py"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text("# fixture", encoding="utf-8")
        with mock.patch.object(setup.subprocess, "run",
                               side_effect=subprocess.TimeoutExpired("check", 15)):
            with self.assertRaisesRegex(RuntimeError, "watchdog timed out"):
                setup.verify_discovery_install(python, root=self.root)

    def test_pip_error_propagates(self):
        self.fake_venv()
        with (mock.patch.object(setup.platform, "system", return_value="Linux"),
              mock.patch.object(setup, "run_command", side_effect=subprocess.CalledProcessError(1, "pip"))):
            with self.assertRaises(subprocess.CalledProcessError):
                setup.install_environment(root=self.root, include_driver=False)


if __name__ == "__main__":
    unittest.main()
