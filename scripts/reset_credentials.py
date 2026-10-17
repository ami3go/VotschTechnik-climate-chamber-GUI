"""Trusted host-only administrator credential reset; no hardware or network I/O.

Source checkout: python -m scripts.reset_credentials
Frozen Windows install: ClimateChamberServer.exe --reset-credentials
"""
from __future__ import annotations

import argparse
from pathlib import Path

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
