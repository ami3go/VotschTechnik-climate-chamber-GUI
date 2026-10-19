"""Administrator-saved chamber configuration, applied at the NEXT server start.

The Chambers page stores the chamber type, connection and supervised HIL
envelope in a private server-side file instead of requiring ``CHAMBER_HIL_*``
environment variables. The saved values are translated into the same
``CHAMBER_HIL_*`` mapping and validated by ``hil_authorization_from_env``, so
every launch-time rule (private IPv4, serial pin, bounded envelope, explicit
person-present acknowledgement, loopback/LAN policy, factory credentials) still
applies. A running server never switches between simulation and hardware.

Precedence: any ``CHAMBER_HIL_*`` variable in the process environment wins over
the saved file, so scripts and hardware tests keep their explicit behaviour.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from chamber_web.domain.chamber import ChamberSafetyError, validate_chamber_id
from chamber_web.hil.physical import (
    ACKNOWLEDGEMENT, HilAuthorization, hil_authorization_from_env,
)
from chamber_web.security.paths import security_directory

CHAMBER_TYPES = {
    "simulator": "Simulator (no hardware)",
    "votsch": "Vötsch climate chamber (TCP/IP)",
}
MAX_SETTINGS_BYTES = 16 * 1024
_HIL_ENV_KEYS = (
    "CHAMBER_HIL_ADDRESS", "CHAMBER_HIL_EXPECTED_SERIAL", "CHAMBER_HIL_TEMP_MIN_C",
    "CHAMBER_HIL_TEMP_MAX_C", "CHAMBER_HIL_ACK", "CHAMBER_HIL_CHAMBER_ID",
)


@dataclass(frozen=True)
class ChamberSettings:
    chamber_type: str = "simulator"
    chamber_id: str = "hil-votsch"
    address: str = ""
    expected_serial: str = ""
    temperature_min_c: float = 15.0
    temperature_max_c: float = 35.0
    person_present_acknowledged: bool = False
    saved_by: str = ""
    saved_at_utc: str = ""

    def hil_environment(self) -> dict[str, str]:
        """Equivalent ``CHAMBER_HIL_*`` mapping; empty for the simulator."""
        if self.chamber_type == "simulator":
            return {}
        return {
            "CHAMBER_HIL_CHAMBER_ID": self.chamber_id,
            "CHAMBER_HIL_ADDRESS": self.address,
            "CHAMBER_HIL_EXPECTED_SERIAL": self.expected_serial,
            "CHAMBER_HIL_TEMP_MIN_C": repr(float(self.temperature_min_c)),
            "CHAMBER_HIL_TEMP_MAX_C": repr(float(self.temperature_max_c)),
            "CHAMBER_HIL_ACK": ACKNOWLEDGEMENT if self.person_present_acknowledged else "",
        }

    def validate(self) -> HilAuthorization | None:
        """Apply exactly the launch-time HIL rules; None for the simulator."""
        if self.chamber_type not in CHAMBER_TYPES:
            raise ChamberSafetyError("Unsupported chamber type")
        if self.chamber_type == "simulator":
            return None
        validate_chamber_id(self.chamber_id)
        if not self.person_present_acknowledged:
            raise ChamberSafetyError(
                "Physical chamber requires acknowledging that a person is present")
        return hil_authorization_from_env(self.hil_environment())


def settings_path() -> Path:
    return security_directory() / "chamber_settings.json"


def load_settings(path: Path | None = None) -> ChamberSettings | None:
    """Saved settings, or None when nothing was saved. Corrupt files fail closed."""
    path = path or settings_path()
    if not path.exists():
        return None
    try:
        if path.stat().st_size > MAX_SETTINGS_BYTES:
            raise ChamberSafetyError("Chamber settings file exceeds bounded size")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("not an object")
        settings = ChamberSettings(
            chamber_type=str(data["chamber_type"]),
            chamber_id=str(data["chamber_id"]),
            address=str(data["address"]),
            expected_serial=str(data["expected_serial"]),
            temperature_min_c=float(data["temperature_min_c"]),
            temperature_max_c=float(data["temperature_max_c"]),
            person_present_acknowledged=data["person_present_acknowledged"] is True,
            saved_by=str(data.get("saved_by", "")),
            saved_at_utc=str(data.get("saved_at_utc", "")),
        )
    except ChamberSafetyError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ChamberSafetyError(
            f"Chamber settings file {path} is unreadable; delete it to return "
            "to simulation") from exc
    return settings


def _write_settings(settings: ChamberSettings, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    payload = json.dumps(asdict(settings), indent=2, sort_keys=True).encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0)
    descriptor = os.open(temporary, flags, 0o600)
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)


def save_settings(security, session: str | None, csrf: str | None,
                  admin_password: str, settings: ChamberSettings, *,
                  path: Path | None = None) -> ChamberSettings:
    """Administrator-only, password-confirmed and audited; takes effect on restart."""
    admin = security.reauthenticate_admin(session, csrf, admin_password)
    try:
        settings.validate()
        if settings.chamber_type != "simulator" and any(
                security.factory_credentials_active()):
            raise ChamberSafetyError(
                "Change the factory administrator password and PIN before "
                "configuring a physical chamber")
    except ChamberSafetyError as exc:
        security.audit(admin, "chamber.settings.save", "DENIED", detail=str(exc))
        raise
    stamped = ChamberSettings(**{
        **asdict(settings),
        "saved_by": admin.username,
        "saved_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    _write_settings(stamped, path or settings_path())
    detail = ("simulator" if stamped.chamber_type == "simulator" else
              f"{stamped.chamber_type} {stamped.chamber_id} {stamped.address} "
              f"serial {stamped.expected_serial} "
              f"{stamped.temperature_min_c}..{stamped.temperature_max_c} C")
    security.audit(admin, "chamber.settings.save", "SUCCESS",
                   chamber_id=None if stamped.chamber_type == "simulator"
                   else stamped.chamber_id, detail=detail)
    return stamped


def effective_hil_environment(env: Mapping[str, str],
                              path: Path | None = None) -> tuple[Mapping[str, str], str]:
    """Environment for ``hil_authorization_from_env`` and a source label.

    Explicit ``CHAMBER_HIL_*`` process variables take precedence; otherwise the
    administrator-saved settings are used; otherwise simulation.
    """
    if any(env.get(key, "").strip() for key in _HIL_ENV_KEYS):
        return env, "environment"
    settings = load_settings(path)
    if settings is None or settings.chamber_type == "simulator":
        return env, "default"
    return {**env, **settings.hil_environment()}, "chamber settings"
