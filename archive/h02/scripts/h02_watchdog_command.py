"""H02: portable, external-process watchdog for simulated tests and build commands.

This utility does NOT issue hardware commands or perform an emergency stop.
It is intentionally a standalone standard-library process, not a NiceGUI timer.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def positive(text: str) -> float:
    value = float(text)
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError("Deadline must be finite and positive")
    return value


def terminate_tree(process: subprocess.Popen, cleanup_s: float) -> None:
    """Kill only the owned subprocess group. Never signal the caller's group."""
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                timeout=cleanup_s, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            process.kill() if process.poll() is None else None
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=cleanup_s)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=cleanup_s)


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout-s", required=True, type=positive)
    parser.add_argument("--idle-timeout-s", type=positive)
    parser.add_argument("--heartbeat-file", type=Path)
    parser.add_argument("--heartbeat-timeout-s", type=positive)
    parser.add_argument("--poll-s", type=positive, default=0.25)
    parser.add_argument("--cleanup-s", type=positive, default=5.0)
    parser.add_argument("--log-dir", required=True, type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("Expected command after --")
    if bool(args.heartbeat_file) != bool(args.heartbeat_timeout_s):
        parser.error("--heartbeat-file and --heartbeat-timeout-s are required together")
    if args.poll_s > min(args.timeout_s, args.heartbeat_timeout_s or args.timeout_s):
        parser.error("Polling interval exceeds deadline")
    args.log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    root = args.log_dir / f"watchdog-{stamp}-{os.getpid()}"
    root.mkdir(mode=0o700)
    start = time.monotonic()
    last_activity = start
    last_heartbeat = start
    heartbeat_stamp = None
    reason = "EXITED"
    exit_code = 125
    process = None
    stdout_path, stderr_path = root / "stdout.log", root / "stderr.log"
    with stdout_path.open("wb") as out, stderr_path.open("wb") as err, (
        root / "timeline.jsonl"
    ).open("w", encoding="utf-8") as timeline:
        def event(name: str, **fields) -> None:
            timeline.write(json.dumps({
                "event": name,
                "utc": datetime.now(timezone.utc).isoformat(),
                "elapsed_s": round(time.monotonic() - start, 3),
                **fields,
            }, sort_keys=True) + "\n")
            timeline.flush()

        try:
            flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
            process = subprocess.Popen(
                command, stdout=out, stderr=err,
                start_new_session=(os.name != "nt"), creationflags=flags,
            )
            event("SPAWN", pid=process.pid, process_group=process.pid,
                  command=command, timeout_s=args.timeout_s)
            print(f"watchdog PID={process.pid} evidence={root}", flush=True)
            sizes = (0, 0)
            next_progress = start
            while True:
                now = time.monotonic()
                sizes_now = (stdout_path.stat().st_size, stderr_path.stat().st_size)
                if sizes_now != sizes:
                    last_activity = now
                    sizes = sizes_now
                if args.heartbeat_file:
                    try:
                        stamp_ns = args.heartbeat_file.stat().st_mtime_ns
                    except FileNotFoundError:
                        stamp_ns = None
                    if stamp_ns is not None and stamp_ns != heartbeat_stamp:
                        heartbeat_stamp = stamp_ns
                        last_heartbeat = now
                status = process.poll()
                if status is not None:
                    exit_code = status
                    reason = "EXITED"
                    break
                if now - start >= args.timeout_s:
                    reason, exit_code = "TIMEOUT", 124
                    break
                if args.idle_timeout_s and now - last_activity >= args.idle_timeout_s:
                    reason, exit_code = "NO_OUTPUT", 125
                    break
                if args.heartbeat_timeout_s and now - last_heartbeat >= args.heartbeat_timeout_s:
                    reason, exit_code = "LOST_HEARTBEAT", 125
                    break
                if now >= next_progress:
                    event("HEARTBEAT", pid=process.pid, stdout_bytes=sizes[0],
                          stderr_bytes=sizes[1])
                    next_progress = now + min(5.0, args.timeout_s / 2)
                time.sleep(min(args.poll_s, max(0.01, args.timeout_s - (now - start))))
            if reason != "EXITED":
                event("ABORT", reason=reason, pid=process.pid)
                terminate_tree(process, args.cleanup_s)
            event("FINAL", reason=reason, returncode=exit_code, pid=process.pid)
        except BaseException as exc:
            event("WRAPPER_ERROR", error=type(exc).__name__)
            if process is not None:
                terminate_tree(process, args.cleanup_s)
            raise
        finally:
            (root / "summary.json").write_text(json.dumps({
                "result": reason, "returncode": exit_code,
                "pid": process.pid if process else None,
                "elapsed_s": round(time.monotonic() - start, 3),
                "stdout": str(stdout_path), "stderr": str(stderr_path),
            }, indent=2) + "\n", encoding="utf-8")
    return exit_code


if __name__ == "__main__":
    sys.exit(run())
