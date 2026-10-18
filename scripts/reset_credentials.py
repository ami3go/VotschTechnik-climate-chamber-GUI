"""Trusted host-only administrator credential reset; no hardware or network I/O.

Source checkout: python -m scripts.reset_credentials OR python scripts/reset_credentials.py
Frozen Windows install: ClimateChamberServer.exe --reset-credentials
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

# Direct execution sets sys.path[0] to scripts/, not the repository root.
# Resolve the location of this file instead of relying on the working
# directory or on an untrusted PYTHONPATH.
if __package__ in (None, ""):
    root = Path(__file__).resolve().parent.parent
    if not (root / "chamber_web" / "security" / "bootstrap.py").is_file():
        raise SystemExit(
            "Cannot locate chamber_web: run this script from the complete "
            "GUI repository checkout (not a standalone copied script)."
        )
    sys.path.insert(0, str(root))

from chamber_web.security.bootstrap import interactive_reset_credentials


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reset admin password and PIN with the current password or offline recovery token"
    )
    parser.add_argument(
        "--data-dir", type=Path, default=None,
        help="Existing security directory (default CHAMBER_SECURITY_DIR or ~/.chamber_web/security)",
    )
    options = parser.parse_args()
    return interactive_reset_credentials(options.data_dir)


if __name__ == "__main__":
    raise SystemExit(main())
