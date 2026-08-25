#!/usr/bin/env python3
"""Convert 422 hub employers to sharded Workday Playwright (see README Phenom / shard section)."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
import sys
sys.path.insert(0, str(REPO_ROOT / "scripts" / "hubs"))
import hub_tools  # noqa: E402

BASE = hub_tools.BASE_JSON
BASE_JSON = hub_tools.BASE_JSON

RECOMMEND = hub_tools.report_path("quickjobs-422-recommendations.tsv")

# Monday=0 … Sunday=6 (matches QUICKJOBS_SHARD_DAY / quickjobs-run-*-shard)
WORKDAY_PW_SHARDS: dict[int, list[str]] = {
    0: ["ford", "costco", "bank-of-america", "wellsfargo"],
    1: ["jnj", "optum", "unitedhealth", "tesla"],
    2: ["lockheed-martin", "gdit", "l3harris", "fortinet"],
    3: ["berkeley", "stanford", "mit", "ucla"],
    4: ["delta-airlines", "alaska-airlines", "jetblue", "rivian"],
    5: ["doordash", "uber", "hca-healthcare", "tenet"],
    6: ["american-express", "harvard", "lattice-semiconductor", "ge-aerospace"],
}


def workday_search_template(browse_url: str) -> str:
    base = str(browse_url or "").strip().rstrip("/")
    if not base:
        return ""
    return f"{base}?q={{query}}"


def load_workday_urls() -> dict[str, str]:
    urls: dict[str, str] = {}
    if RECOMMEND.is_file():
        for row in csv.DictReader(RECOMMEND.open(), delimiter="\t"):
            wd = (row.get("workday_url") or "").strip()
            if wd and "myworkdayjobs.com" in wd:
                urls[row["id"]] = wd
    blocked = hub_tools.BLOCKED_TSV
    if blocked.is_file():
        for row in csv.DictReader(blocked.open(), delimiter="\t"):
            wd = (row.get("browse_url") or "").strip()
            if wd and "myworkdayjobs.com" in wd:
                urls.setdefault(row["id"], wd)
    return urls


def main() -> int:
    cfg = hub_tools.load_base_bundle()
    by_id = {str(c["id"]): c for c in cfg.get("companies", []) if c.get("id")}
    wd_urls = load_workday_urls()
    shard_ids = {cid for ids in WORKDAY_PW_SHARDS.values() for cid in ids}
    updated: list[str] = []

    for shard, ids in WORKDAY_PW_SHARDS.items():
        for cid in ids:
            co = by_id.get(cid)
            if not co:
                print(f"skip missing id: {cid}")
                continue
            browse = wd_urls.get(cid, "").strip()
            if not browse:
                print(f"skip no workday url: {cid}")
                continue
            co.pop("hub_url", None)
            co.pop("hub_note", None)
            co["type"] = "playwright"
            co["playwright_kind"] = "workday"
            co["workday_fetch"] = "playwright"
            co["workday_skip_playwright_on_422"] = False
            co["workday_pw_shard"] = shard
            co["max_details"] = 12
            co["workday_playwright_max_queries"] = 5
            co["cache_ttl_hours"] = 24
            co["browse_url"] = browse
            co["search_url_template"] = workday_search_template(browse)
            updated.append(f"{cid} (shard {shard})")

    hub_tools.save_base_bundle(cfg)
    print(f"Updated {len(updated)} companies in {BASE}")
    for line in updated:
        print(f"  {line}")
    missing = sorted(shard_ids - set(wd_urls) - set(by_id))
    if missing:
        print("Missing workday URL or config id:", ", ".join(missing))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
