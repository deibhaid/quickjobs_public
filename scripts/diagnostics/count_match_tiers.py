#!/usr/bin/env python3
"""Count match tiers and UI-relevant metrics from snapshot + HTML."""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

SG = frozenset(["strong", "good"])


def primary(job: dict) -> bool:
    return job.get("loc") != "excluded" and job.get("salary") != "low"


def sidebar_dot_count(co: dict) -> int:
    return len(
        [
            j
            for j in co.get("jobs") or []
            if primary(j) and j.get("match") in SG
        ]
    )


def count_snapshot(snapshot_path: Path) -> dict[str, int]:
    data = json.loads(snapshot_path.read_text(encoding="utf-8"))
    tier_jobs = Counter()
    for co in data.get("companies") or []:
        for job in co.get("jobs") or []:
            tier_jobs[str(job.get("match") or "none")] += 1
    sg_sources = sum(1 for co in data.get("companies") or [] if sidebar_dot_count(co) > 0)
    return {
        "strong": tier_jobs.get("strong", 0),
        "good": tier_jobs.get("good", 0),
        "stretch": tier_jobs.get("stretch", 0),
        "sg_sidebar_sources": sg_sources,
    }


def count_listings_pool_sg(html_path: Path) -> int:
    html = html_path.read_text(encoding="utf-8", errors="replace")
    match = re.search(
        r'<script type="application/json" id="lazy-board-data">(.*?)</script>',
        html,
        re.DOTALL,
    )
    if not match:
        return -1
    index = json.loads(match.group(1)).get("index") or []
    return sum(
        1
        for entry in index
        if entry.get("pool") == "listings" and entry.get("match") in SG
    )


def main() -> int:
    label = sys.argv[1] if len(sys.argv) > 1 else "counts"
    snap = Path(
        sys.argv[2]
        if len(sys.argv) > 2
        else "/mnt/Uploads/html/quickjobs/job-search-quickjobs.snapshot.json"
    )
    html = Path(
        sys.argv[3]
        if len(sys.argv) > 3
        else "/mnt/Uploads/html/job-search-quickjobs.html"
    )
    snap_counts = count_snapshot(snap)
    listings_sg = count_listings_pool_sg(html) if html.is_file() else -1
    print(label)
    print(f"strong={snap_counts['strong']} good={snap_counts['good']} stretch={snap_counts['stretch']}")
    print(f"sg_sidebar_sources={snap_counts['sg_sidebar_sources']}")
    print(f"listings_pool_sg={listings_sg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
