"""Demo-only profile model and simulation, with no hardware communication.

The production controller will live behind the separate Python driver adapter.
"""
from __future__ import annotations

import csv
import io
import math
from collections import deque
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Iterable

PROFILE_HEADERS = ("target", "ramp", "tolerance", "dwell", "description", "enabled")
MIN_TEMP = -40.0
MAX_TEMP = 130.0
MAX_STEPS = 200


@dataclass
class Step:
    target: float
    ramp: float
    tolerance: float
    dwell: int
    description: str
    enabled: bool = True


def default_steps() -> list[Step]:
    return [
        Step(25, 5, 2, 300, "Soak at ambient"),
        Step(-40, 5, 1, 1800, "Cold temperature"),
        Step(85, 5, 1, 1800, "High temperature"),
        Step(25, 5, 2, 600, "Return to ambient"),
        Step(25, 5, 2, 600, "Final soak"),
    ]


def validate_steps(steps: Iterable[Step]) -> list[Step]:
    result = list(steps)
    if not 1 <= len(result) <= MAX_STEPS:
        raise ValueError(f"A profile needs 1–{MAX_STEPS} steps")
    if not any(step.enabled for step in result):
        raise ValueError("At least one step must be enabled")
    for row_number, step in enumerate(result, 1):
        for name in ("target", "ramp", "tolerance"):
            value = getattr(step, name)
            if isinstance(value, bool) or not math.isfinite(float(value)):
                raise ValueError(f"Row {row_number}: invalid {name}")
        if not MIN_TEMP <= step.target <= MAX_TEMP:
            raise ValueError(f"Row {row_number}: target outside {MIN_TEMP}..{MAX_TEMP} °C")
        if not 0 < step.ramp <= 5:
            raise ValueError(f"Row {row_number}: demo ramp must be >0 and <=5 °C/min")
        if not 0 < step.tolerance <= 20:
            raise ValueError(f"Row {row_number}: tolerance must be >0 and <=20 °C")
        if isinstance(step.dwell, bool) or not isinstance(step.dwell, int) or not 0 <= step.dwell <= 86400:
            raise ValueError(f"Row {row_number}: dwell must be 0..86400 whole seconds")
        if len(step.description) > 160:
            raise ValueError(f"Row {row_number}: description too long")
    return result


def _enabled_flag(value: str) -> bool:
    text = value.strip().lower()
    if text in ("true", "1", "yes", "y"):
        return True
    if text in ("false", "0", "no", "n"):
        return False
    raise ValueError(f"Invalid enabled value: {value!r}")


def import_profile_csv(content: str) -> list[Step]:
    if len(content.encode("utf-8")) > 1_000_000:
        raise ValueError("CSV exceeds the 1 MB limit")
    # Strip BOM; csv.DictReader handles quoted commas and newlines.
    reader = csv.DictReader(io.StringIO(content.lstrip("\ufeff"), newline=""))
    if reader.fieldnames != list(PROFILE_HEADERS):
        raise ValueError("CSV columns must be: " + ", ".join(PROFILE_HEADERS))
    result = []
    for row_number, row in enumerate(reader, 1):
        if row_number > MAX_STEPS:
            raise ValueError(f"CSV exceeds {MAX_STEPS} steps")
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f"Row {row_number}: malformed CSV")
        dwell_value = float(row["dwell"])
        if not math.isfinite(dwell_value) or not dwell_value.is_integer():
            raise ValueError(f"Row {row_number}: dwell must be whole seconds")
        result.append(Step(
            target=float(row["target"]),
            ramp=float(row["ramp"]),
            tolerance=float(row["tolerance"]),
            dwell=int(dwell_value),
            description=row["description"],
            enabled=_enabled_flag(row["enabled"]),
        ))
    return validate_steps(result)


def export_profile_csv(steps: Iterable[Step]) -> str:
    validated = validate_steps(steps)
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow(PROFILE_HEADERS)
    for step in validated:
        # Prevent formula evaluation on spreadsheet open; reject these text
        # prefixes rather than silently corrupting an import/export round-trip.
        if step.description.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
            raise ValueError("Description must not start with a spreadsheet formula character")
        writer.writerow((
            step.target, step.ramp, step.tolerance, step.dwell,
            step.description, str(step.enabled),
        ))
    return output.getvalue()


class DemoChamber:
    """One isolated, operator-started SIMULATION per browser page.

    A browser timer drives this demonstration. It is not a production engine,
    does not control hardware and must never run chamber profiles unattended.
    """

    def __init__(self) -> None:
        self.profile_name = "Temperature Cycle – Automotive"
        self.steps = default_steps()
        self.run_steps: list[Step] = []
        self.current = 23.4
        self.manual_target = 25.0
        self.step_index = 0
        self.dwell_elapsed = 0.0
        self.elapsed = 0.0
        self.running = False
        self.held = False
        self.completed = False
        self.speed = 20
        self.samples: deque[dict] = deque(maxlen=1500)
        self.readings: deque[dict] = deque(maxlen=12)
        self.logs: deque[dict] = deque(maxlen=40)
        self.tick_count = 0
        self.log("Simulation ready — no physical chamber connected")

    @property
    def active_steps(self) -> list[Step]:
        return self.run_steps if self.run_steps else self.steps

    @property
    def active(self) -> Step:
        steps = self.active_steps
        return steps[min(self.step_index, len(steps) - 1)]

    @property
    def status(self) -> str:
        if self.held:
            return "Held"
        if self.running:
            return "Running"
        if self.completed:
            return "Completed"
        return "Stopped"

    @property
    def progress(self) -> float:
        if self.completed:
            return 1.0
        if not self.run_steps:
            return 0.0
        total = sum(s.enabled for s in self.run_steps)
        done = sum(s.enabled for s in self.run_steps[:self.step_index])
        return done / max(total, 1)

    def log(self, message: str, level: str = "INFO") -> None:
        self.tick_count += 1
        self.logs.appendleft({
            "id": str(self.tick_count),
            "time": datetime.now().strftime("%H:%M:%S"),
            "level": level,
            "message": message,
        })

    def start(self) -> None:
        if self.running:
            return
        snapshot = validate_steps(self.steps)
        self.run_steps = [replace(s) for s in snapshot]
        self.step_index = next(i for i, s in enumerate(self.run_steps) if s.enabled)
        self.dwell_elapsed = 0.0
        self.elapsed = 0.0
        self.running = True
        self.held = False
        self.completed = False
        self.samples.clear()
        self.readings.clear()
        self.log("DEMO profile started: " + self.profile_name)

    def stop(self) -> None:
        if self.running or self.held:
            self.running = False
            self.held = False
            self.completed = False
            self.log("DEMO profile stopped")

    def hold(self) -> None:
        if self.running:
            self.held = not self.held
            self.log("DEMO profile held" if self.held else "DEMO profile resumed")

    def advance(self) -> None:
        i = self.step_index + 1
        while i < len(self.run_steps) and not self.run_steps[i].enabled:
            i += 1
        if i == len(self.run_steps):
            self.running = False
            self.held = False
            self.completed = True
            self.log("DEMO profile completed")
        else:
            self.step_index = i
            self.dwell_elapsed = 0.0
            self.log(f"Step {i + 1}: target {self.active.target:g} °C")

    def tick(self) -> None:
        if not self.running or self.held:
            return
        step = self.active
        seconds = float(self.speed)
        self.elapsed += seconds
        change_limit = step.ramp * seconds / 60
        diff = step.target - self.current
        self.current = round(self.current + max(-change_limit, min(change_limit, diff)), 3)
        in_band = abs(self.current - step.target) <= step.tolerance
        self.dwell_elapsed = self.dwell_elapsed + seconds if in_band else 0
        phase = "Soak" if in_band else "Ramp"
        target = step.target
        step_number = self.step_index + 1
        if self.dwell_elapsed >= step.dwell:
            self.log(f"Step {step_number} completed")
            self.advance()
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.samples.append({
            "time": stamp,
            "measured": self.current,
            "target": target,
        })
        self.tick_count += 1
        self.readings.appendleft({
            "id": str(self.tick_count),
            "time": datetime.now().strftime("%H:%M:%S"),
            "measured": f"{self.current:.1f}",
            "target": f"{target:.1f}",
            "status": phase,
        })
