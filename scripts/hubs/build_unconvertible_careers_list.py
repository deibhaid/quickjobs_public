#!/usr/bin/env python3
"""Rebuild manual careers JSON (delegates to hub_tools)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import hub_tools


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, default=hub_tools.MANUAL_CAREERS_OUTPUT)
    parser.add_argument("--tsv", type=Path, default=hub_tools.MANUAL_CAREERS_TSV)
    parser.add_argument(
        "--no-legacy-mirror",
        action="store_true",
        help="Do not copy to quickjobs.unconvertible-careers.json in repo",
    )
    args = parser.parse_args()
    hub_tools.rebuild_manual_careers(
        json_path=args.json,
        tsv_path=args.tsv,
        mirror_legacy=not args.no_legacy_mirror,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
