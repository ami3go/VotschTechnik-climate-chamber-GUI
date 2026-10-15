"""H02 subprocess-watchdog fault injection: simulation-only; no hardware."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "h02_watchdog_command.py"


def invoke(root: Path, *options: str, command: list[str]) -> tuple[subprocess.CompletedProcess, dict]:
    args = [sys.executable, str(SCRIPT), "--timeout-s", "3", "--poll-s", "0.05",
            "--cleanup-s", "2", "--log-dir", str(root), *options, "--", *command]
    proc = subprocess.run(args, capture_output=True, text=True, timeout=12)
    summaries = list(root.glob("watchdog-*/summary.json"))
    if len(summaries) != 1:
        raise AssertionError(f"Expected one evidence record: {proc.stdout} {proc.stderr}")
    return proc, json.loads(summaries[0].read_text())


class ExternalProcessWatchdogTests(unittest.TestCase):
    def test_success_captures_pid_and_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result, summary = invoke(root, command=[sys.executable, "-c",
                "import sys;print('alive',flush=True);print('stderr',file=sys.stderr,flush=True)"])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(summary["result"], "EXITED")
            self.assertGreater(summary["pid"], 0)
            self.assertIn("alive", Path(summary["stdout"]).read_text())
            self.assertIn("stderr", Path(summary["stderr"]).read_text())
            timeline = list(root.glob("*/timeline.jsonl"))[0].read_text()
            self.assertIn('"event": "SPAWN"', timeline)
            self.assertIn('"event": "FINAL"', timeline)

    def test_deadline_kills_child_and_never_reports_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, summary = invoke(Path(tmp), "--timeout-s", "0.5",
                                     command=[sys.executable, "-c", "import time;time.sleep(20)"])
            self.assertEqual(result.returncode, 124, result.stderr)
            self.assertEqual(summary["result"], "TIMEOUT")

    def test_output_stall_triggers_bounded_abort(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, summary = invoke(Path(tmp), "--idle-timeout-s", "0.5",
                                     command=[sys.executable, "-c", "import time;time.sleep(20)"])
            self.assertEqual(result.returncode, 125, result.stderr)
            self.assertEqual(summary["result"], "NO_OUTPUT")

    def test_missing_application_heartbeat_triggers_abort(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, summary = invoke(
                Path(tmp), "--heartbeat-file", str(Path(tmp) / "missing.heartbeat"),
                "--heartbeat-timeout-s", "0.5",
                command=[sys.executable, "-c", "import time;time.sleep(20)"],
            )
            self.assertEqual(result.returncode, 125, result.stderr)
            self.assertEqual(summary["result"], "LOST_HEARTBEAT")

    def test_nonfinite_timeouts_rejected_before_spawn(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--timeout-s", "nan",
                 "--log-dir", tmp, "--", sys.executable, "-c", "pass"],
                capture_output=True, text=True, timeout=5,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(list(Path(tmp).glob("watchdog-*")))


if __name__ == "__main__":
    unittest.main()
