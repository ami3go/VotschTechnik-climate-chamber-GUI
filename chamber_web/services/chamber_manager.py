"""Single-device application facade. Browser code never receives a raw backend.

G04-A executes only explicitly simulated adapters; real hardware remains OFF.
No multi-chamber runtime, scheduler or unauthorized UI mutation is introduced.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from chamber_web.domain.chamber import ChamberBackend, ChamberSafetyError, validate_chamber_id
from chamber_web.domain.config import ChamberConfig
from chamber_web.services.chamber_controller import ChamberController, ControllerHealth


class ChamberManager:
    def __init__(
        self, configurations: list[ChamberConfig], *,
        backend_factory: Callable, allow_test_backend: bool = False,
        lease_directory: Path | None = None, io_timeout_s: float = 2.0,
    ):
        if len(configurations) != 1:
            raise ChamberSafetyError(
                "v1 requires exactly one configured chamber; "
                "multiple physical devices are not supported"
            )
        self._config = configurations[0]
        # Validate cardinality BEFORE creating any backend or connecting.
        backend: ChamberBackend = backend_factory(
            self._config, allow_test_backend=allow_test_backend,
        )
        self._controller = ChamberController(
            self._config, backend, lease_directory=lease_directory,
            io_timeout_s=io_timeout_s,
        )

    def configured_ids(self) -> tuple[str, ...]:
        return (self._config.chamber_id,)

    def _check_id(self, chamber_id: str) -> None:
        validate_chamber_id(chamber_id)
        if chamber_id != self._config.chamber_id:
            raise ChamberSafetyError("Wrong/stale chamber_id: operation refused")

    def get(self, chamber_id: str) -> "ChamberManager":
        """Expose only the guarded service facade (not a raw backend)."""
        self._check_id(chamber_id)
        return self

    def connect(self, chamber_id: str) -> None:
        self._check_id(chamber_id)
        self._controller.connect(chamber_id)

    def disconnect(self, chamber_id: str) -> None:
        self._check_id(chamber_id)
        self._controller.disconnect(chamber_id)

    def status(self, chamber_id: str):
        self._check_id(chamber_id)
        return self._controller.status(chamber_id)

    def health(self, chamber_id: str) -> ControllerHealth:
        self._check_id(chamber_id)
        return self._controller.health

    def capabilities(self, chamber_id: str):
        """G02-A compatibility: cached capabilities, never direct backend I/O."""
        self._check_id(chamber_id)
        caps = self._controller.capabilities
        if caps is None:
            raise ChamberSafetyError("Capabilities unavailable before verified identity")
        return caps

    def set_temperature(self, chamber_id: str, target_c: float,
                        *, operator_token: str | None = None) -> None:
        self._check_id(chamber_id)
        self._controller.set_temperature(chamber_id, target_c, operator_token=operator_token)

    def start(self, chamber_id: str, *, operator_token: str | None = None) -> None:
        self._check_id(chamber_id)
        self._controller.start(chamber_id, operator_token=operator_token)

    def set_profile_running(self, chamber_id: str, running: bool, *,
                            operator_token: str | None = None) -> None:
        self._check_id(chamber_id)
        self._controller.set_profile_running(
            chamber_id, running, operator_token=operator_token,
        )

    def set_digital_output(self, chamber_id: str, number: int, state: bool, *,
                           operator_token: str | None = None) -> None:
        self._check_id(chamber_id)
        self._controller.set_digital_output(
            chamber_id, number, state, operator_token=operator_token,
        )

    def stop(self, chamber_id: str) -> None:
        self._check_id(chamber_id)
        self._controller.stop(chamber_id)

    def reconcile_stop(self, chamber_id: str) -> None:
        self._check_id(chamber_id)
        self._controller.reconcile_stop(chamber_id)

    def claim_operator(self, chamber_id: str, owner: str) -> str:
        self._check_id(chamber_id)
        return self._controller.claim_operator(chamber_id, owner)

    def release_operator(self, chamber_id: str, token: str) -> None:
        self._check_id(chamber_id)
        self._controller.release_operator(chamber_id, token)

    def start_polling(self, chamber_id: str, *, interval_s: float = 2.0) -> None:
        self._check_id(chamber_id)
        self._controller.start_polling(chamber_id, interval_s=interval_s)
