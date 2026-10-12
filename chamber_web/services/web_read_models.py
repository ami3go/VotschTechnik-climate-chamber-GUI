"""Read-only, backend-neutral extension seams for G07 run/event records.

G02-B never synthesizes run records or persistent events from dashboard telemetry.
G07 implementations can be wired into WebReadServices without changes to pages.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class RunRecord:
    chamber_id: str
    run_id: str
    profile_name: str
    profile_revision: int
    operator: str | None
    started_at_utc: datetime
    ended_at_utc: datetime | None
    outcome: str


@dataclass(frozen=True)
class EventRecord:
    event_id: str
    chamber_id: str
    timestamp_utc: datetime
    severity: str
    message: str
    operator: str | None = None
    run_id: str | None = None
    step: int | None = None


@dataclass(frozen=True)
class RecordPage:
    """Bounded immutable server result. available=False means provider absent."""
    available: bool
    records: tuple[RunRecord, ...] | tuple[EventRecord, ...] = ()
    detail: str = ""
    def __post_init__(self) -> None:
        if len(self.records) > 100:
            raise ValueError("Record page exceeds 100 rows")
        if not self.available and self.records:
            raise ValueError("Unavailable providers cannot return invented records")


class HistoryReader(Protocol):
    def list_runs(self, chamber_id: str, *, search: str = "",
                  limit: int = 50) -> RecordPage: ...


class EventReader(Protocol):
    def list_events(self, chamber_id: str, *, severity: str = "ALL",
                    search: str = "", limit: int = 50) -> RecordPage: ...


class UnavailableHistoryReader:
    def list_runs(self, chamber_id: str, *, search: str = "",
                  limit: int = 50) -> RecordPage:
        return RecordPage(False, detail="G07 run recording/history service is not installed.")


class UnavailableEventReader:
    def list_events(self, chamber_id: str, *, severity: str = "ALL",
                    search: str = "", limit: int = 50) -> RecordPage:
        return RecordPage(False, detail="G07 persistent event/audit log service is not installed.")


def bounded_search(value: str) -> str:
    # Prevent unbounded provider-side queries; never use input in SQL or HTML.
    return str(value or "").strip()[:120]
