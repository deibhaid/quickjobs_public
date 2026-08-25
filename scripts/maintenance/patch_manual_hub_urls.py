#!/usr/bin/env python3
"""Apply known careers URLs to manual hubs and drop duplicate -it stub rows."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_JSON = REPO_ROOT / "quickjobs.base.json"
UNC_JSON = REPO_ROOT / "quickjobs.unconvertible-careers.json"

# User-verified careers URLs (and a few obvious fixes for screenshot duplicates).
HUB_URL_PATCHES: dict[str, str] = {
    "akamai": "https://jobs.akamai.com/en/sites/CX_1",
    "confluent": "https://careers.confluent.io/",
    "foreflight": "https://foreflight.com/about/careers/",
    "hashicorp": "https://www.ibm.com/careers/search?q=hashicorp",
    "kaiser-it": "https://www.kaiserpermanentejobs.org/job/",
    "legacy-health-it": "https://www.legacyhealth.org/for-health-professionals/careers",
    "nike-it": "https://careers.nike.com/jobs",
    "openai": "https://openai.com/careers/search/",
    "red-hat": "https://redhat.wd5.myworkdayjobs.com/jobs/",
    "snap": "https://careers.snap.com/jobs",
    "snyk": "https://snyk.io/careers/all-jobs/",
    "wiz": "https://www.wiz.io/careers",
    "electronic-arts": "https://jobs.electronicarts.com/",
    "marriott-international": "https://careers.marriott.com/",
    "t-mobile-us": "https://www.t-mobile.com/careers",
}

# Duplicate manual rows: IT stub hubs with no unique careers destination.
REMOVE_HUB_IDS = frozenset(
    {
        "fedex-it",
        "marriott-it",
        "t-mobile-it",
        "ea-it",
        "faa-it",
        "verizon-it",
    }
)


def patch_companies(companies: list[dict[str, Any]]) -> list[str]:
    log: list[str] = []
    for company in companies:
        cid = str(company.get("id") or "")
        url = HUB_URL_PATCHES.get(cid)
        if url and company.get("type") == "hub":
            if company.get("hub_url") != url:
                company["hub_url"] = url
                log.append(f"hub_url: {cid}")
    return log


def patch_unconvertible(employers: list[dict[str, Any]], hub_ids: set[str]) -> list[str]:
    log: list[str] = []
    kept: list[dict[str, Any]] = []
    for entry in employers:
        if not isinstance(entry, dict):
            continue
        cid = str(entry.get("id") or "")
        if cid in hub_ids:
            log.append(f"unconvertible drop (hub exists): {cid}")
            continue
        url = HUB_URL_PATCHES.get(cid)
        if url and not str(entry.get("careers_url") or "").strip():
            entry["careers_url"] = url
            log.append(f"unconvertible url: {cid}")
        kept.append(entry)
    employers.clear()
    employers.extend(kept)
    return log


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    base = hub_tools.load_base_bundle()
    before = len(base["companies"])
    base["companies"] = [c for c in base["companies"] if c.get("id") not in REMOVE_HUB_IDS]
    removed = before - len(base["companies"])
    url_log = patch_companies(base["companies"])

    hub_ids = {
        str(c["id"])
        for c in base["companies"]
        if isinstance(c, dict) and c.get("id") and c.get("type") == "hub"
    }

    unc_log: list[str] = []
    if UNC_JSON.is_file():
        unc = json.loads(UNC_JSON.read_text(encoding="utf-8"))
        employers = unc.get("employers")
        if isinstance(employers, list):
            unc_log = patch_unconvertible(employers, hub_ids)

    print(f"removed stub hubs: {removed}")
    for line in url_log:
        print(f"  {line}")
    for line in unc_log[:30]:
        print(f"  {line}")
    if len(unc_log) > 30:
        print(f"  ... +{len(unc_log) - 30} unconvertible changes")

    if args.apply:
        hub_tools.save_base_bundle(base)
        if UNC_JSON.is_file():
            UNC_JSON.write_text(json.dumps(unc, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {BASE_JSON}")
        if UNC_JSON.is_file():
            print(f"wrote {UNC_JSON}")
    else:
        print("dry-run (pass --apply to write)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
