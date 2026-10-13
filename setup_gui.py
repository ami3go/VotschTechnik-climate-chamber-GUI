#!/usr/bin/env python3
"""Set up the NiceGUI chamber simulator on Windows or Linux.

Usage: python setup_gui.py [--run] [--recreate]
Requires Python >= 3.10. Does not enable physical chamber I/O.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements-web.txt"


def run(*args: str) -> None:
    print("+", " ".join(str(arg) for arg in args), flush=True)
    subprocess.run([str(arg) for arg in args], cwd=ROOT, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Launch the local mock-only GUI after installing")
    parser.add_argument("--recreate", action="store_true", help="Delete and rebuild only the local .venv")
    args = parser.parse_args()

    if sys.version_info < (3, 10):
        parser.error("Python 3.10 or newer is required")
    system = platform.system()
    if system not in ("Windows", "Linux"):
        parser.error(f"Unsupported OS: {system}; use Windows or Linux")
    if not REQUIREMENTS.is_file() or not (ROOT / "main.py").is_file():
        parser.error("Run this script from its original repository (main.py and requirements-web.txt required)")

    python = VENV / ("Scripts/python.exe" if system == "Windows" else "bin/python")
    print(f"OS: {system} | Python: {sys.version.split()[0]} | Environment: {VENV}", flush=True)

    if args.recreate and VENV.exists():
        print("Removing local virtual environment...", flush=True)
        shutil.rmtree(VENV)
    if not python.is_file():
        print("Creating virtual environment...", flush=True)
        try:
            venv.EnvBuilder(with_pip=True, clear=False).create(VENV)
        except Exception as exc:
            if system == "Linux":
                print("Install your distro's python3-venv package and retry if ensurepip is missing.", file=sys.stderr)
            raise RuntimeError("Unable to create virtual environment") from exc
    if not python.is_file():
        raise RuntimeError(f"Virtual environment interpreter missing: {python}")

    run(str(python), "-m", "pip", "install", "--upgrade", "pip")
    run(str(python), "-m", "pip", "install", "-r", str(REQUIREMENTS))
    run(str(python), "-m", "pip", "check")
    print("\nEnvironment ready. GUI runs with the repository's mock-only configuration.", flush=True)
    if args.run:
        print("Starting GUI at http://127.0.0.1:8080", flush=True)
        run(str(python), str(ROOT / "main.py"))
    else:
        command = ".venv\\Scripts\\python.exe main.py" if system == "Windows" else ".venv/bin/python main.py"
        print(f"To start: {command}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, subprocess.CalledProcessError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
