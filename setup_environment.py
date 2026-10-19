"""Set up NiceGUI chamber dependencies on Windows or Linux (no hardware I/O)."""
from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def python_in_venv(venv: Path, system: str) -> Path:
    """Return the platform-specific virtual environment interpreter."""
    if system == "Windows":
        return venv / "Scripts" / "python.exe"
    if system == "Linux":
        return venv / "bin" / "python"
    raise RuntimeError(f"Unsupported OS: {system}. Use Windows or Linux.")


def run_command(command: list[str], *, cwd: Path) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, check=True, cwd=cwd)


def verify_discovery_install(python: Path, *, root: Path = ROOT) -> None:
    """Verify installed driver API and pinned commit in the server interpreter.

    No network or physical chamber access. 15-second import watchdog.
    """
    script = root / "scripts" / "verify_driver_install.py"
    if not script.is_file():
        raise RuntimeError(f"Driver verification helper is missing: {script}")
    command = [str(python), str(script), "--requirements",
               str(root / "requirements-hardware.txt")]
    try:
        result = subprocess.run(command, cwd=root, capture_output=True,
                                text=True, check=True, timeout=15)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Driver import verification watchdog timed out") from exc
    except subprocess.CalledProcessError as exc:
        reason = (exc.stderr or exc.stdout or "unknown verification error").strip()
        raise RuntimeError(
            f"Driver validation failed in {python}: {reason[:1200]}") from exc
    print(result.stdout.strip(), flush=True)


def install_environment(
    *,
    root: Path = ROOT,
    venv: Path | None = None,
    include_driver: bool = True,
    with_tests: bool = False,
    with_browser: bool = False,
    recreate: bool = False,
) -> Path:
    """Create/reuse a venv, install requirements, and check dependencies."""
    system = platform.system()
    if system not in {"Windows", "Linux"}:
        raise RuntimeError(f"Unsupported OS: {system}. Use Windows or Linux.")
    if sys.version_info < (3, 10):
        raise RuntimeError("Python 3.10 or newer is required (3.10 and 3.12 are CI-tested).")
    if sys.version_info >= (3, 13):
        print("Warning: Python 3.13+ has not been validated by project CI.", flush=True)
    if with_browser and not with_tests:
        raise ValueError("--browser requires --with-tests")

    root = root.resolve()
    venv = (venv or (root / ".venv")).resolve()
    requirements = [root / "requirements-web.txt"]
    if include_driver:
        if shutil.which("git") is None:
            raise RuntimeError(
                "Git is required to install the pinned external Vötsch driver. "
                "Install Git or use --no-driver for a simulation-only setup."
            )
        requirements.append(root / "requirements-hardware.txt")
    if with_tests:
        requirements.append(root / "requirements-dev.txt")
    for requirement in requirements:
        if not requirement.is_file():
            raise FileNotFoundError(f"Missing dependency file: {requirement}")

    python = python_in_venv(venv, system)
    print(f"Platform: {system}; virtualenv: {venv}", flush=True)
    if recreate and venv.exists():
        # Only ever delete a real virtual environment, never an arbitrary folder.
        if not (venv / "pyvenv.cfg").is_file():
            raise RuntimeError(
                f"Refusing to delete {venv}: it is not a virtual environment (no pyvenv.cfg).")
        print(f"Removing existing virtual environment: {venv}", flush=True)
        shutil.rmtree(venv)
    if not python.is_file():
        if venv.exists():
            raise RuntimeError(
                f"Directory exists but is not a valid {system} virtual environment: {venv}. "
                "Choose another --venv path or remove the invalid directory manually."
            )
        run_command([sys.executable, "-m", "venv", str(venv)], cwd=root)
        if not python.is_file():
            raise RuntimeError(f"Virtual environment creation did not produce {python}")

    for requirement in requirements:
        run_command(
            [str(python), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(requirement)],
            cwd=root,
        )
    if include_driver:
        try:
            verify_discovery_install(python, root=root)
        except RuntimeError as first_failure:
            # A same-version VCS distribution can still have the wrong commit.
            print(f"Driver verification failed: {first_failure}", flush=True)
            print("Repairing pinned external driver in the SAME virtualenv...", flush=True)
            run_command(
                [str(python), "-m", "pip", "install", "--disable-pip-version-check",
                 "--upgrade", "--force-reinstall", "-r",
                 str(root / "requirements-hardware.txt")], cwd=root)
            verify_discovery_install(python, root=root)
    run_command([str(python), "-m", "pip", "check"], cwd=root)
    if with_browser:
        # Does not install OS packages or request administrator rights.
        run_command([str(python), "-m", "playwright", "install", "chromium"], cwd=root)

    print("Environment ready. No physical chamber connection was attempted.")
    print(f"Run GUI: {python} {root / 'main.py'}")
    return python


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--venv", type=Path, help="Virtual environment directory (default: .venv)")
    parser.add_argument("--no-driver", action="store_true", help="Skip Git driver; simulation only")
    parser.add_argument("--with-tests", action="store_true", help="Install pinned test and lint libraries")
    parser.add_argument("--browser", action="store_true", help="Download Playwright Chromium (requires --with-tests)")
    parser.add_argument("--run", action="store_true", help="Start the simulated local NiceGUI app after setup")
    parser.add_argument("--check-driver", action="store_true",
                        help="Offline check installed driver import and pinned Git commit (no install)")
    parser.add_argument("--recreate", action="store_true",
                        help="Delete and rebuild the virtual environment (only if it is one)")
    args = parser.parse_args(argv)
    try:
        if args.check_driver:
            system = platform.system()
            if system not in {"Windows", "Linux"}:
                raise RuntimeError(f"Unsupported OS: {system}")
            target_venv = (args.venv or (ROOT / ".venv")).resolve()
            python = python_in_venv(target_venv, system)
            if not python.is_file():
                raise RuntimeError(f"Server virtualenv Python not found: {python}")
            verify_discovery_install(python, root=ROOT)
            return 0
        python = install_environment(
            venv=args.venv,
            include_driver=not args.no_driver,
            with_tests=args.with_tests,
            with_browser=args.browser,
            recreate=args.recreate,
        )
        if args.run:
            run_command([str(python), str(ROOT / "main.py")], cwd=ROOT)
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Setup failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
