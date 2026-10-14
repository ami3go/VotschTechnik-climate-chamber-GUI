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
        python = setup.python_in_venv(self.root / ".venv", system)
        python.parent.mkdir(parents=True, exist_ok=True)
        python.touch()
        return python

    def test_windows_uses_scripts_python_and_pinned_files(self):
        python = self.fake_venv("Windows")
        with (mock.patch.object(setup.platform, "system", return_value="Windows"),
              mock.patch.object(setup.shutil, "which", return_value="git.exe"),
              mock.patch.object(setup, "run_command") as run):
            result = setup.install_environment(root=self.root, with_tests=True, with_browser=True)
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

    def test_browser_requires_test_dependencies(self):
        with mock.patch.object(setup.platform, "system", return_value="Linux"):
            with self.assertRaisesRegex(ValueError, "requires --with-tests"):
                setup.install_environment(root=self.root, include_driver=False, with_browser=True)

    def test_unsupported_os_is_rejected(self):
        with mock.patch.object(setup.platform, "system", return_value="Darwin"):
            with self.assertRaisesRegex(RuntimeError, "Unsupported OS"):
                setup.install_environment(root=self.root, include_driver=False)

    def test_pip_error_propagates(self):
        self.fake_venv()
        with (mock.patch.object(setup.platform, "system", return_value="Linux"),
              mock.patch.object(setup, "run_command", side_effect=subprocess.CalledProcessError(1, "pip"))):
            with self.assertRaises(subprocess.CalledProcessError):
                setup.install_environment(root=self.root, include_driver=False)


if __name__ == "__main__":
    unittest.main()
