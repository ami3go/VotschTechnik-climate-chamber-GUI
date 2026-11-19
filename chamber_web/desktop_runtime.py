"""Pre-production desktop runtime: the FULL server in a portable Windows bundle.

Unlike the W01 demo runtime (``chamber_web.windows_runtime``, loopback-only and
simulated with HIL/auth deliberately out of scope), this entry point starts the
real application: G08 authentication, G07 recording, STOP fencing, G05/G06
control and the optional supervised H02 physical profile path with its signed
permit and independent watchdog.

Launch-time configuration comes from an allowlisted ``chamber.env`` file (see
``load_environment``) so a frozen bundle has no Python or shell dependency.
Browser input can never select the backend, certificate or permit files.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import secrets
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

from chamber_web import maintenance, windows_runtime
from chamber_web.windows_runtime import (
    READY_PATH,
    configured_port,
    port_occupied,
    process_lock,
    read_instance,
    state_dir,
)

APP_ID = "climate-chamber-preproduction"
STATE_NAMESPACE = "App"
DEFAULT_PORT = 8090
CONFIG_NAME = "chamber.env"
MAX_CONFIG_BYTES = 64 * 1024
MAX_LOG_BYTES = 10 * 1024 * 1024
LOG_NAME = "app.log"
ENV_PREFIX = "CHAMBER_"


def config_path() -> Path:
    """Explicit CHAMBER_CONFIG_FILE, else ``chamber.env`` in the state dir."""
    configured = os.environ.get("CHAMBER_CONFIG_FILE", "").strip()
    if configured:
        return Path(configured).expanduser()
    return state_dir(STATE_NAMESPACE) / CONFIG_NAME


def parse_config(text: str) -> dict[str, str]:
    """Parse allowlisted ``KEY=VALUE`` lines; anything unexpected fails closed.

    Only ``CHAMBER_*`` process keys are accepted, so a bundle-local text file can
    never inject ``PATH``, ``PYTHONPATH`` or proxy settings into the server.
    """
    result: dict[str, str] = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Invalid configuration line {number}: expected KEY=VALUE")
        key, value = (part.strip() for part in line.split("=", 1))
        if (not key.startswith(ENV_PREFIX) or not key.isupper()
                or not key.replace("_", "A").isalnum()):
            raise ValueError(
                f"Configuration key {key!r} is not an allowlisted {ENV_PREFIX}* name")
        if key in result:
            raise ValueError(f"Duplicate configuration key: {key}")
        if len(value) > 4096 or "\x00" in value:
            raise ValueError(f"Configuration value for {key} is invalid")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        result[key] = value
    return result


def load_environment(path: Path | None = None) -> tuple[Path, list[str]]:
    """Apply the config file without overriding real process variables."""
    target = path or config_path()
    if not target.exists():
        return target, []
    if target.is_symlink():
        raise RuntimeError("Refusing a symlinked configuration file")
    if not target.is_file():
        raise RuntimeError("Configuration path is not a regular file")
    if target.stat().st_size > MAX_CONFIG_BYTES:
        raise RuntimeError("Configuration file exceeds the size limit")
    values = parse_config(target.read_text(encoding="utf-8"))
    applied = []
    for key, value in values.items():
        if key not in os.environ:
            os.environ[key] = value
            applied.append(key)
    return target, applied


@contextmanager
def _capture_console_log(directory: Path):
    """Send native stdout/stderr (uvicorn included) to one rotated log file."""
    log = directory / LOG_NAME
    try:
        if log.is_file() and log.stat().st_size > MAX_LOG_BYTES:
            log.replace(directory / (LOG_NAME + ".1"))
    except OSError:
        pass  # Rotation is best effort; never block server start on the log.
    stream = open(log, "ab", buffering=0)  # noqa: SIM115 - fd kept for dup2
    saved = (os.dup(1), os.dup(2))
    try:
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(stream.fileno(), 1)
        os.dup2(stream.fileno(), 2)
        yield log
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(saved[0], 1)
        os.dup2(saved[1], 2)
        os.close(saved[0])
        os.close(saved[1])
        stream.close()


def _write_instance(path: Path, identity: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(identity), encoding="utf-8")
    temporary.replace(path)


def serve(*, port: int | None = None) -> int:
    _, applied = load_environment()
    if port is None:
        port = configured_port(DEFAULT_PORT)
    if not 1024 <= port <= 65535:
        raise RuntimeError("Invalid server port")
    os.environ["CHAMBER_PORT"] = str(port)
    directory = state_dir(STATE_NAMESPACE)
    # The ownership lock is held for the whole server lifetime, so a second
    # instance (or a stale session) can never reach the chamber.
    with _capture_console_log(directory):  # noqa: SIM117 - explicit lifetime
        with process_lock("server.lock", state_name=STATE_NAMESPACE):
            if port_occupied(port):
                raise RuntimeError("Server port is already occupied")
            token = secrets.token_hex(32)
            path = windows_runtime.instance_path(STATE_NAMESPACE)
            identity = {"app": APP_ID, "pid": os.getpid(),
                        "port": port, "token": token}
            _write_instance(path, identity)
            try:
                from nicegui import app

                import chamber_web.main as application

                @app.get(READY_PATH)
                def ready(challenge: str = ""):
                    if (len(challenge) != 32 or
                            any(char not in "0123456789abcdef" for char in challenge)):
                        return {"error": "invalid challenge"}
                    return {
                        "app": APP_ID, "pid": os.getpid(),
                        "proof": hmac.new(token.encode("ascii"),
                                          challenge.encode("ascii"),
                                          hashlib.sha256).hexdigest(),
                    }

                if applied:
                    print("Configuration applied: " + ", ".join(applied), flush=True)
                mode = ("simulation" if application.profile_execution_is_simulation()
                        else "supervised physical HIL")
                print(f"Pre-production server starting on port {port} "
                      f"(mode: {mode})", flush=True)
                application.run()
            finally:
                if read_instance(STATE_NAMESPACE) == identity:
                    path.unlink(missing_ok=True)
    return 0


def launcher_url() -> str:
    port = configured_port(DEFAULT_PORT)
    origin = os.environ.get("CHAMBER_PUBLIC_ORIGIN", "").strip()
    if origin:
        return origin.rstrip("/") + "/"
    return "http://127.0.0.1:" + str(port) + "/"


def launch(*, open_browser: bool = True, check_only: bool = False) -> int:
    if os.environ.get("CHAMBER_NETWORK_MODE", "localhost").strip().lower() == "lan":
        # A LAN server is TLS-only and is started by the scheduled task, not by
        # a launcher child process; open the exact configured origin instead.
        origin = os.environ.get("CHAMBER_PUBLIC_ORIGIN", "").strip()
        if not origin:
            raise RuntimeError("LAN mode requires CHAMBER_PUBLIC_ORIGIN")
        if check_only:
            print("LAN deployment: open " + origin, flush=True)
            return 0
        import webbrowser
        if not webbrowser.open(origin.rstrip("/") + "/"):
            raise RuntimeError("No default browser could be opened")
        return 0
    executable = None
    command = None
    env = None
    port = configured_port(DEFAULT_PORT)
    if getattr(sys, "frozen", False):
        executable = (Path(sys.executable).resolve().parent / "server"
                      / "ClimateChamberServer.exe")
    elif os.name != "nt":
        root = str(Path(__file__).resolve().parents[1])
        existing = os.environ.get("PYTHONPATH", "")
        command = [sys.executable, "-m", "chamber_web.desktop_runtime",
                   "--port", str(port)]
        env = {"PYTHONPATH": root + (os.pathsep + existing if existing else "")}
    return windows_runtime.launch(
        open_browser=open_browser, check_only=check_only, app_id=APP_ID,
        state_name=STATE_NAMESPACE, executable=executable, url=launcher_url(),
        host=os.environ.get("CHAMBER_BIND_HOST", "127.0.0.1"),
        command=command, env=env, default_port=DEFAULT_PORT)


def launcher_main() -> int:
    parser = argparse.ArgumentParser(
        description="Climate Chamber pre-production browser launcher")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    try:
        return launch(open_browser=not args.no_browser, check_only=args.check_only)
    except Exception as exc:  # noqa: BLE001 - report any launcher failure
        message = str(exc) + "\nLogs: " + str(state_dir(STATE_NAMESPACE) / LOG_NAME)
        print(message, file=sys.stderr)
        if not args.no_browser and os.name == "nt":
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0, message, "Climate Chamber launcher", 0x10)
        return 1


def check_config(path: Path | None = None) -> int:
    target, applied = load_environment(path)
    if not applied:
        print("No configuration values need applying from " + str(target), flush=True)
    else:
        print("Configuration OK (" + str(target) + "): " + ", ".join(applied), flush=True)
    return 0


def self_test(*, required_modules: tuple[str, ...] = ()) -> int:
    """Deterministic, device-free verification of a frozen pre-production build."""
    with tempfile.TemporaryDirectory() as scratch:
        os.environ["CHAMBER_STATE_DIR"] = scratch
        os.environ["CHAMBER_SECURITY_DIR"] = scratch
        for key in list(os.environ):
            if key.startswith(("CHAMBER_HIL_", "CHAMBER_H02_", "CHAMBER_LAB_")):
                os.environ.pop(key, None)
        values = parse_config(
            "# comment\nCHAMBER_PORT=8091\nCHAMBER_NETWORK_MODE=\"localhost\"\n")
        if values != {"CHAMBER_PORT": "8091", "CHAMBER_NETWORK_MODE": "localhost"}:
            raise RuntimeError("Configuration parser self-test failed")
        for bad in ("PATH=/tmp", "CHAMBER_BAD-KEY=1", "NOEQUALS",
                    "CHAMBER_PORT=1\nCHAMBER_PORT=2"):
            try:
                parse_config(bad)
            except ValueError:
                continue
            raise RuntimeError("Configuration parser accepted: " + bad)

        import chamber_web.main as application
        from chamber_web.adapters.registry import make_backend
        from chamber_web.domain.chamber import ChamberSafetyError
        from chamber_web.domain.config import ChamberConfig
        from chamber_web.hil.commits import detect_gui_commit
        from chamber_web.main import CSS

        if not CSS.strip():
            raise RuntimeError("Local CSS was not bundled")
        if application.profile_execution_is_simulation() is not True:
            raise RuntimeError("Self-test started with a physical HIL authorization")
        for adapter_id in ("fake", "alternate_stub"):
            backend = make_backend(
                ChamberConfig("pre-test", adapter_id), allow_test_backend=True)
            backend.connect()
            try:
                if not backend.identify().is_simulation:
                    raise RuntimeError("Non-simulated adapter in self-test")
                backend.read_status()
            finally:
                backend.disconnect()
        real = make_backend(ChamberConfig("pre-test", "votsch", "192.0.2.1"))
        try:
            real.connect()
        except ChamberSafetyError:
            pass
        else:
            raise RuntimeError("Physical device unexpectedly enabled")
        if not detect_gui_commit():
            raise RuntimeError(
                "No clean GUI revision is detectable; the bundle needs a valid "
                "chamber_web/build-revision.json stamp")
        from importlib.util import find_spec
        for module in required_modules:
            if module == "VotschTechnikClimateChamber":
                from chamber_web.adapters.votsch import verify_bundled_driver_import
                try:
                    verify_bundled_driver_import()
                except (ImportError, AttributeError, RuntimeError) as exc:
                    raise RuntimeError(
                        "Required packaged module missing or broken: " + module) from exc
            elif not module.isidentifier() or find_spec(module) is None:
                raise RuntimeError("Required packaged module missing: " + module)
    print("Pre-production self-test OK (simulated, no device opened)", flush=True)
    return 0


def server_main() -> int:
    parser = argparse.ArgumentParser(
        description="Climate Chamber pre-production NiceGUI server")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--config", type=Path,
                        help="Allowlisted CHAMBER_* configuration file")
    parser.add_argument("--check-config", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--require-module", action="append", default=[])
    maintenance.add_arguments(parser)
    args = parser.parse_args()
    try:
        if args.config is not None:
            os.environ["CHAMBER_CONFIG_FILE"] = str(args.config.expanduser())
        if args.check_config:
            return check_config()
        if args.self_test:
            return self_test(required_modules=tuple(args.require_module))
        result = maintenance.run(args)
        if result is not None:
            return result
        return serve(port=args.port)
    except Exception as exc:  # noqa: BLE001 - report any startup failure
        print("Climate Chamber server error: " + str(exc), file=sys.stderr)
        return 1


__all__ = [
    "APP_ID", "STATE_NAMESPACE", "check_config", "config_path", "launch",
    "launcher_main", "launcher_url", "load_environment", "parse_config",
    "self_test", "serve", "server_main",
]


if __name__ == "__main__":
    raise SystemExit(server_main())
