#!/usr/bin/env python3
"""Build DOL LCA employer + wage indexes for quickjobs.

Writes:
  - employer-index.json  (visa filer grades)
  - lca-wage-index.json  (salary p25–p75 fallback when JDs omit pay)

  ~/.v/bin/pip install openpyxl
  ~/.v/bin/python scripts/maintenance/fetch_h1b_employer_index.py
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_h1b_module():
    path = REPO_ROOT / "h1b_employer.py"
    spec = importlib.util.spec_from_file_location("h1b_employer", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_quickjobs_cache_root() -> Path:
    import importlib.util

    path = REPO_ROOT / "quickjobs.david.py"
    spec = importlib.util.spec_from_file_location("quickjobs_david", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod.h1b_cache_root()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build DOL LCA employer index for work visa validation")
    parser.add_argument("--fy", type=int, action="append", help="Fiscal year (repeat with --quarter)")
    parser.add_argument("--quarter", type=int, action="append", help="Quarter 1-4 (paired with --fy)")
    args = parser.parse_args()

    h1b = _load_h1b_module()
    cache_root = _load_quickjobs_cache_root()

    quarters: list[tuple[int, int]] | None = None
    if args.fy and args.quarter:
        if len(args.fy) != len(args.quarter):
            print("Provide the same number of --fy and --quarter values", file=sys.stderr)
            return 1
        quarters = list(zip(args.fy, args.quarter, strict=True))

    def progress(msg: str) -> None:
        print(msg, flush=True)

    out = h1b.build_employer_index(cache_root, quarters=quarters, progress=progress)
    payload = __import__("json").loads(out.read_text(encoding="utf-8"))
    print(f"Wrote {out} ({payload.get('employer_count', 0)} employers)")
    wage_path = h1b.wage_index_path(cache_root)
    if wage_path.is_file():
        wage_payload = __import__("json").loads(wage_path.read_text(encoding="utf-8"))
        print(
            f"Wrote {wage_path} ({wage_payload.get('employer_count', 0)} wage employers)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
