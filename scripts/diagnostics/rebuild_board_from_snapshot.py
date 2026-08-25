#!/usr/bin/env python3
"""Regenerate job-search HTML from the last run snapshot (no scrape)."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


def main() -> int:
    script = Path(__file__).resolve().parents[2] / "quickjobs.py"
    sys.argv = [str(script), "rebuild-snapshot"]
    runpy.run_path(str(script), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
