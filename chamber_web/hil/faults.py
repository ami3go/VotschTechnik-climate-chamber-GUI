"""In-memory H01 fault fixtures; imports no network transport or vendor driver."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from chamber_web.adapters.fake import FakeBackend
from chamber_web.domain.chamber import ChamberSnapshot, ReadingQuality

class FaultInjectingFakeBackend(FakeBackend):
    def __init__(self, chamber_id: str):
        super().__init__(chamber_id)
        self.fail_readback = False
        self.stale_readback = False
        self.mismatch_target = False
        self.fail_stop = False
        self.write_count = 0

    def set_temperature(self, target_c: float) -> None:
        self.write_count += 1
        super().set_temperature(target_c)

    def stop(self) -> None:
        if self.fail_stop:
            raise TimeoutError("simulated ambiguous STOP")
        super().stop()

    def read_status(self) -> ChamberSnapshot:
        if self.fail_readback:
            raise TimeoutError("simulated telemetry timeout")
        s = super().read_status()
        return ChamberSnapshot(s.identity, s.measured_temperature_c,
            s.setpoint_temperature_c + 1 if self.mismatch_target and s.setpoint_temperature_c is not None else s.setpoint_temperature_c,
            s.operation_state, ReadingQuality.STALE if self.stale_readback else s.quality,
            datetime.now(timezone.utc)-timedelta(minutes=2) if self.stale_readback else s.sampled_at_utc)
