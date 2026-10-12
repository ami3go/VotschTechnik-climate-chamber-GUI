"""Windows W01-A portable launcher/server bootstrap: simulated, loopback-only.

No vendor protocol or physical controller lives here. Production service,
authentication, STOP, and HIL release gates are deliberately out of scope.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import build_opener, ProxyHandler
import webbrowser

APP_ID = "climate-chamber-w01-demo"
DEFAULT_PORT = 8080
LOCK_WAIT_SECONDS = 35


def state_dir() -> Path:
    root = os.environ.get("LOCALAPPDATA")
    if not root:
        root = str(Path.home() / "AppData" / "Local")
    result = Path(root) / "ClimateChamber" / "W01"
    result.mkdir(parents=True, exist_ok=True)
    return result


def configured_port() -> int:
    raw = os.environ.get("CHAMBER_PORT", str(DEFAULT_PORT))
    try:
        port = int(raw)
    except ValueError as exc:
        raise RuntimeError("CHAMBER_PORT must be an integer") from exc
    if not 1024 <= port <= 65535:
        raise RuntimeError("CHAMBER_PORT must be between 1024 and 65535")
    return port


@contextmanager
def process_lock(name: str, *, wait_seconds: float = 0):
    """Windows kernel byte-range lock (released even after abrupt process exit)."""
    if os.name != "nt":
        raise RuntimeError("W01 launcher is Windows-only")
    import msvcrt  # Windows only

    path = state_dir() / name
    handle = open(path, "a+b")
    try:
        handle.seek(0)
        if handle.read(1) == b"":
            handle.write(b"0")
            handle.flush()
        end = time.monotonic() + wait_seconds
        while True:
            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError as exc:
                if time.monotonic() >= end:
                    raise RuntimeError("A Climate Chamber process already owns " + name) from exc
                time.sleep(0.2)
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    finally:
        handle.close()


def instance_path() -> Path:
    return state_dir() / "instance.json"


def read_instance() -> dict | None:
    try:
        data = json.loads(instance_path().read_text(encoding="utf-8"))
        if (data.get("app") == APP_ID and isinstance(data.get("token"), str)
                and isinstance(data.get("port"), int) and isinstance(data.get("pid"), int)):
            return data
    except (OSError, ValueError, AttributeError):
        pass
    return None


def probe(instance: dict | None) -> bool:
    if not instance or instance.get("app") != APP_ID or not 1024 <= instance["port"] <= 65535:
        return False
    challenge = secrets.token_hex(16)
    url = ("http://127.0.0.1:" + str(instance["port"])
           + "/__w01_ready?" + urlencode({"challenge": challenge}))
    try:
        # Never consult an OS/corporate HTTP proxy for loopback, including in
        # a disconnected Windows installation. Bound foreign-port responses.
        with build_opener(ProxyHandler({})).open(url, timeout=1.5) as response:
            if response.status != 200:
                return False
            payload = response.read(8193)
        if len(payload) > 8192:
            return False
        result = json.loads(payload)
        expected = hmac.new(instance["token"].encode("ascii"),
                            challenge.encode("ascii"), hashlib.sha256).hexdigest()
        return (result.get("app") == APP_ID
                and result.get("pid") == instance["pid"]
                and hmac.compare_digest(result.get("proof", ""), expected))
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, HTTPError, URLError):
        return False


def port_occupied(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
            return False
        except OSError:
            return True


def server_executable() -> Path:
    base = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else (
        Path(__file__).resolve().parents[1]
    )
    return base / "server" / "ClimateChamberServer.exe"


def launch(*, open_browser: bool = True, check_only: bool = False) -> int:
    """Attach only after HMAC proof from this user's installed server."""
    port = configured_port()
    with process_lock("launcher.lock", wait_seconds=LOCK_WAIT_SECONDS):
        instance = read_instance()
        if probe(instance):
            if instance["port"] != port:
                raise RuntimeError("Existing server uses another CHAMBER_PORT")
        else:
            if check_only:
                raise RuntimeError("No authenticated Climate Chamber server is running")
            if port_occupied(port):
                raise RuntimeError("Port is occupied by an unrecognized application: " + str(port))
            executable = server_executable()
            if not executable.is_file():
                raise RuntimeError("Missing bundled server: " + str(executable))
            log_path = state_dir() / "server.log"
            with open(log_path, "ab", buffering=0) as logfile:
                proc = subprocess.Popen(
                    [str(executable), "--port", str(port)],
                    cwd=str(state_dir()), stdin=subprocess.DEVNULL,
                    stdout=logfile, stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    close_fds=True,
                )
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                instance = read_instance()
                if instance and instance["port"] == port and probe(instance):
                    break
                if proc.poll() is not None:
                    raise RuntimeError("Server exited; see " + str(log_path))
                time.sleep(0.25)
            else:
                raise RuntimeError("Server readiness timed out; see " + str(log_path))
        if open_browser and not webbrowser.open("http://127.0.0.1:" + str(port) + "/"):
            raise RuntimeError("No default Windows browser could be opened")
        print("Authenticated simulator server PID", instance["pid"], flush=True)
    return 0


def frozen_self_test(*, required_modules: tuple[str, ...] = ()) -> int:
    """Exercise allowlisted factories/assets without connecting any device."""
    from chamber_web.adapters.registry import make_backend
    from chamber_web.domain.chamber import ChamberSafetyError
    from chamber_web.domain.config import ChamberConfig
    from chamber_web.main import CSS  # Exercises frozen local CSS and NiceGUI import

    if not CSS.strip():
        raise RuntimeError("Local CSS was not bundled")
    for adapter_id in ("fake", "alternate_stub"):
        backend = make_backend(
            ChamberConfig("w01-test", adapter_id), allow_test_backend=True
        )
        backend.connect()
        try:
            if not backend.identify().is_simulation:
                raise RuntimeError("Non-simulated adapter in W01 self-test")
            backend.read_status()
        finally:
            backend.disconnect()
    real = make_backend(ChamberConfig("w01-test", "votsch", "192.0.2.1"))
    try:
        real.connect()
    except ChamberSafetyError:
        pass
    else:
        raise RuntimeError("Physical device unexpectedly enabled")
    # Vendor-specific import verification must remain inside its adapter.
    # Import only; NEVER instantiate or connect a physical chamber.
    from importlib.util import find_spec
    for module in required_modules:
        if module == "VotschTechnikClimateChamber":
            try:
                from chamber_web.adapters.votsch import verify_bundled_driver_import
                verify_bundled_driver_import()
            except (ImportError, AttributeError, RuntimeError) as exc:
                raise RuntimeError("Required packaged module missing or broken: " + module) from exc
        elif not module.isidentifier() or find_spec(module) is None:
            raise RuntimeError("Required packaged module missing: " + module)
    print("W01 self-test OK (simulated only)", flush=True)
    return 0


def serve(*, port: int) -> int:
    if os.name != "nt":
        raise RuntimeError("The W01 frozen server is Windows-only")
    if not 1024 <= port <= 65535:
        raise RuntimeError("Invalid server port")
    # Ownership lock is held for the entire server lifetime, not browser lifetime.
    with process_lock("server.lock"):
        if port_occupied(port):
            raise RuntimeError("Server port is already occupied")
        token = secrets.token_hex(32)
        identity = {"app": APP_ID, "pid": os.getpid(), "port": port, "token": token}
        path = instance_path()
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(identity), encoding="utf-8")
        temporary.replace(path)
        try:
            from nicegui import app, ui
            os.environ["CHAMBER_PORT"] = str(port)
            import chamber_web.main  # noqa: F401 - register demo page/assets
            from chamber_web.security.nicegui import cookie_secret

            @app.get("/__w01_ready")
            def ready(challenge: str = "") -> dict:
                if len(challenge) != 32 or any(c not in "0123456789abcdef" for c in challenge):
                    return {"error": "invalid challenge"}
                return {
                    "app": APP_ID, "pid": os.getpid(),
                    "proof": hmac.new(token.encode("ascii"), challenge.encode("ascii"),
                                      hashlib.sha256).hexdigest(),
                }

            ui.run(title="Climate Chamber - SIMULATION ONLY", host="127.0.0.1",
                   port=port, reload=False, show=False,
                    storage_secret=cookie_secret(),
                    session_middleware_kwargs={"same_site": "strict", "max_age": 28800})
        finally:
            if read_instance() == identity:
                path.unlink(missing_ok=True)
    return 0


def launcher_main() -> int:
    parser = argparse.ArgumentParser(description="Windows W01 demo browser launcher")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    try:
        return launch(open_browser=not args.no_browser, check_only=args.check_only)
    except Exception as exc:
        message = str(exc) + "\nLogs: " + str(state_dir() / "server.log")
        print(message, file=sys.stderr)
        if not args.no_browser and os.name == "nt":
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, message, "Climate Chamber launcher", 0x10)
        return 1


def server_main() -> int:
    parser = argparse.ArgumentParser(description="W01 simulated NiceGUI server")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--bootstrap-admin", action="store_true",
                        help="Interactive, offline first administrator; no web provisioning")
    parser.add_argument("--require-module", action="append", default=[])
    args = parser.parse_args()
    try:
        if args.bootstrap_admin:
            from chamber_web.security.bootstrap import interactive_bootstrap
            return interactive_bootstrap()
        if args.self_test:
            return frozen_self_test(required_modules=tuple(args.require_module))
        return serve(port=args.port)
    except Exception as exc:
        print("W01 server error:", str(exc), file=sys.stderr)
        return 1
