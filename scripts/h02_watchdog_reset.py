"""Clear the H02-C watchdog restart latch after a documented operator review.

The latch refuses all further physical profile starts after a supervisor loss
or an unverified STOP. Clearing is a deliberate manual step: inspect
``watchdog-timeline.jsonl`` and ``watchdog-child.jsonl`` in the evidence
directory, complete the approved on-site review, then run:

    python scripts/h02_watchdog_reset.py --evidence-dir PATH \
        --reviewed-by "NAME" --confirm-clear

The original latch file is preserved as ``watchdog-latch-cleared.json`` and a
``LATCH_CLEARED`` event is appended to the timeline. This script never starts
a run, never reaches hardware and does not clear UNKNOWN chamber state.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", required=True)
    parser.add_argument("--reviewed-by", required=True)
    parser.add_argument("--confirm-clear", action="store_true")
    args = parser.parse_args(argv)
    reviewed_by = args.reviewed_by.strip()
    if not reviewed_by or not args.confirm_clear:
        print("Refusing to clear: --reviewed-by NAME and --confirm-clear are "
              "both required after the approved review.", file=sys.stderr)
        return 2
    directory = Path(args.evidence_dir)
    latch = directory / "watchdog-latch.json"
    if not latch.exists():
        print("No watchdog latch present; nothing to clear.")
        return 0
    try:
        data = json.loads(latch.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"Latch unreadable ({type(exc).__name__}); preserve evidence and "
              "investigate manually.", file=sys.stderr)
        return 3
    cleared = directory / "watchdog-latch-cleared.json"
    record = {
        "at_utc": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        "event": "LATCH_CLEARED",
        "reviewed_by": reviewed_by,
        "latch": data,
    }
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / "watchdog-timeline.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, sort_keys=True) + "\n")
        latch.replace(cleared)
    except OSError as exc:
        print(f"Failed to clear latch: {type(exc).__name__}", file=sys.stderr)
        return 4
    print(f"Latch cleared by {reviewed_by}; preserved at {cleared.name}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
