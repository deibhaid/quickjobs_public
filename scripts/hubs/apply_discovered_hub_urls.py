#!/usr/bin/env python3
"""Apply probed careers URLs to hub rows missing hub_url in quickjobs.david.base.json."""

from __future__ import annotations

import argparse

import hub_tools


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write quickjobs.david.base.json")
    args = parser.parse_args()

    log = hub_tools.apply_discovered_hub_urls(apply=args.apply)
    print(f"hub_url patches: {len(log)}")
    for line in log[:40]:
        print(f"  {line}")
    if len(log) > 40:
        print(f"  ... +{len(log) - 40} more")

    if args.apply:
        print(f"wrote {hub_tools.BASE_JSON}")
        hub_tools.rebuild_manual_careers()
    else:
        print("dry-run (pass --apply to write)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
