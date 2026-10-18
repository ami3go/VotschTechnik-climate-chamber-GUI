"""H02-B supervised physical profile admission (server-side, fail-closed).

The site-signed H02 permit and the trusted Ed25519 site key are loaded only
from the launch-time server environment; no browser input can supply or alter
them. A partial configuration refuses to start. Every physical run must pass
the signed-permit preflight binding of the exact G04 identity, immutable G03
checksum, pinned GUI/driver revisions, G08 actor, named witness, site
watchdog limits and a safe initial readback. The permit is revalidated before
every dispatch tick so expiry stops further physical commands.

H02-C still owns the independent watchdog process; until it exists the
production supervisor check stays fail-closed (``supervisor_alive`` false)
and physical profile starts are refused.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from chamber_web.domain.chamber import ChamberSafetyError
from chamber_web.hil.profile_admission import (
    AdmissionDenied, H02LiveChecks, H02WatchdogLimits, verify_signed_permit,
)
from chamber_web.hil.supervision import SupervisionHost

ENV_PERMIT_FILE = "CHAMBER_H02_PERMIT_FILE"
ENV_TRUSTED_KEY = "CHAMBER_H02_TRUSTED_KEY"
ENV_WITNESS = "CHAMBER_H02_WITNESS"
ENV_GUI_COMMIT = "CHAMBER_GUI_COMMIT"
ENV_DRIVER_COMMIT = "CHAMBER_DRIVER_COMMIT"

MAX_PERMIT_BYTES = 1024 * 1024


def _canonical(data: Mapping[str, Any]) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def decode_trusted_key(raw: str) -> bytes:
    """Accept a base64 or hex raw 32-byte Ed25519 public key; else fail closed."""
    text = raw.strip()
    candidates = []
    try:
        candidates.append(base64.b64decode(text, validate=True))
    except (ValueError, TypeError):
        pass
    try:
        candidates.append(bytes.fromhex(text))
    except ValueError:
        pass
    for key in candidates:
        if len(key) == 32:
            return key
    raise ChamberSafetyError(
        "CHAMBER_H02_TRUSTED_KEY must be a base64/hex 32-byte Ed25519 public key")


@dataclass(frozen=True)
class SupervisedProfilePermit:
    envelope: Mapping[str, Any]
    data: Mapping[str, Any]
    public_key: bytes
    watchdog: H02WatchdogLimits
    sha256: str

    def revalidate(self, now_utc: datetime | None = None) -> None:
        """Re-verify signature and validity window before further dispatch."""
        try:
            verified = verify_signed_permit(
                self.envelope, trusted_site_public_key=self.public_key,
                now_utc=now_utc,
            )
        except AdmissionDenied:
            raise
        except Exception as exc:
            raise AdmissionDenied("H02 permit revalidation failed") from exc
        if hashlib.sha256(_canonical(verified)).hexdigest() != self.sha256:
            raise AdmissionDenied("H02 permit changed after admission")


def load_supervised_permit(env: Mapping[str, str]) -> SupervisedProfilePermit | None:
    """None when no supervised permit is configured; fail closed otherwise."""
    path = env.get(ENV_PERMIT_FILE, "").strip()
    key_raw = env.get(ENV_TRUSTED_KEY, "").strip()
    if not path and not key_raw:
        return None
    if not path or not key_raw:
        raise ChamberSafetyError(
            "Incomplete H02 supervised permit configuration: "
            f"{ENV_PERMIT_FILE} and {ENV_TRUSTED_KEY} must both be set")
    permit_file = Path(path).expanduser()
    if not permit_file.is_file():
        raise ChamberSafetyError("H02 permit file is missing or unreadable")
    try:
        if permit_file.stat().st_size > MAX_PERMIT_BYTES:
            raise ChamberSafetyError("H02 permit file exceeds bounded size")
        envelope = json.loads(permit_file.read_text(encoding="utf-8"))
    except ChamberSafetyError:
        raise
    except Exception as exc:
        raise ChamberSafetyError("H02 permit file is not valid JSON") from exc
    key = decode_trusted_key(key_raw)
    data = verify_signed_permit(envelope, trusted_site_public_key=key)
    watchdog = H02WatchdogLimits.from_dict(data["watchdog"])
    return SupervisedProfilePermit(
        envelope, data, key, watchdog, hashlib.sha256(_canonical(data)).hexdigest(),
    )


@dataclass(frozen=True)
class SupervisedProfileRuntime:
    """Server-side supervised-physical context; never built from browser input."""
    permit: SupervisedProfilePermit
    witness: str
    hil_acknowledged: bool
    supervisor_alive: Callable[[], bool]
    gui_commit: str
    driver_commit: str
    supervision: SupervisionHost | None = None

    def live_checks(self, *, authenticated_authorized: bool,
                    connected: bool, verified_stopped: bool, no_stop_latch: bool,
                    recording_healthy: bool):
        return H02LiveChecks(
            g04_exclusive_owner=connected,
            g04_verified_stopped=verified_stopped,
            no_stop_latch=no_stop_latch,
            g07_reconciled_writable=recording_healthy,
            g08_authenticated_authorized=authenticated_authorized,
            physical_stop_procedure_confirmed=self.hil_acknowledged,
            operator_present=authenticated_authorized,
            witness_present=bool(self.witness.strip()),
            supervisor_alive=bool(self.supervisor_alive()),
        )


def supervised_runtime_from_env(
    env: Mapping[str, str], *, hil_present: bool,
    supervisor_alive: Callable[[], bool] | None = None,
    supervision: SupervisionHost | None = None,
) -> SupervisedProfileRuntime | None:
    """Build the supervised runtime for a physical-HIL launch, or None.

    Physical launches without a configured signed permit keep profile
    execution disabled; misconfigured permits refuse to start (fail closed).
    """
    if not hil_present:
        return None
    permit = load_supervised_permit(env)
    if permit is None:
        return None
    return SupervisedProfileRuntime(
        permit=permit,
        witness=env.get(ENV_WITNESS, "").strip(),
        hil_acknowledged=True,
        supervisor_alive=supervisor_alive or (lambda: False),
        gui_commit=env.get(ENV_GUI_COMMIT, "").strip(),
        driver_commit=env.get(ENV_DRIVER_COMMIT, "").strip(),
        supervision=supervision,
    )
