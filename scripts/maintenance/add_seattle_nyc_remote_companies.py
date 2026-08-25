#!/usr/bin/env python3
"""Add Seattle/NYC metro remote scrapeable platform/SRE employers from research reports.

Sources:
  ~/ws/scriptdir/output/quickjobs-reports/seattle-remote-scrapeable-companies-2026-06-15.md
  ~/ws/scriptdir/output/quickjobs-reports/nyc-remote-scrapeable-companies-2026-06-15.md

Idempotent merge into quickjobs.david.base.json. Greenhouse/Lever boards verified via
public API before inclusion. Upgrades Okta entries -> greenhouse (okta).

Run: ~/.v/bin/python add_seattle_nyc_remote_companies.py --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
import sys
sys.path.insert(0, str(REPO_ROOT / "scripts" / "hubs"))
import hub_tools  # noqa: E402

BASE = hub_tools.BASE_JSON
BASE_JSON = hub_tools.BASE_JSON

OUT_PREVIEW = hub_tools.report_path("quickjobs-seattle-nyc-remote-added.json")

IT_SEARCH_KEYWORDS = [
    "devops",
    "devops engineer",
    "site reliability",
    "site reliability engineer",
    "sre",
    "platform engineer",
    "platform engineering",
    "infrastructure engineer",
    "cloud engineer",
    "cloud operations",
    "systems engineer",
    "production engineer",
    "release engineer",
    "build engineer",
    "build and release",
    "principal engineer",
    "staff engineer",
    "software engineer",
    "observability",
    "terraform",
    "kubernetes",
]

MATCHING_DEFAULTS: dict[str, Any] = {
    "section": "matching",
    "search_keywords": IT_SEARCH_KEYWORDS,
    "default_salary": "maybe",
    "cache_ttl_hours": 12,
    "discover": True,
}


def gh(
    company_id: str,
    name: str,
    board: str,
    *,
    label: str | None = None,
    sector: str | None = None,
    browse_url: str | None = None,
    layoff_prone: bool | None = None,
) -> dict[str, Any]:
    row = deepcopy(MATCHING_DEFAULTS)
    row.update(
        {
            "id": company_id,
            "name": name,
            "label": label or f"{name} (Remote US)",
            "type": "greenhouse",
            "board": board,
            "browse_url": browse_url or f"https://boards.greenhouse.io/{board}",
        }
    )
    if sector:
        row["sector"] = sector
    if layoff_prone is not None:
        row["layoff_prone"] = layoff_prone
    return row


def lever_it(
    company_id: str,
    name: str,
    lever_site: str,
    *,
    label: str | None = None,
    sector: str | None = None,
    browse_url: str | None = None,
    layoff_prone: bool | None = None,
) -> dict[str, Any]:
    row = deepcopy(MATCHING_DEFAULTS)
    row.update(
        {
            "id": company_id,
            "name": name,
            "label": label or f"{name} (Remote US)",
            "type": "lever",
            "lever_site": lever_site,
            "browse_url": browse_url or f"https://jobs.lever.co/{lever_site}",
            "skip_verify": True,
        }
    )
    if sector:
        row["sector"] = sector
    if layoff_prone is not None:
        row["layoff_prone"] = layoff_prone
    return row


def promote_patch(company_id: str, **fields: Any) -> dict[str, Any]:
    return {"id": company_id, **fields}


def new_or_upgraded_companies() -> list[dict[str, Any]]:
    return [
        # ── Seattle metro — verified Greenhouse ───────────────────────────────
        gh("smartsheet", "Smartsheet", "smartsheet", sector="tech"),
        gh("offerup", "OfferUp", "offerup", sector="tech"),
        gh("pitchbook", "PitchBook", "pitchbookdata", sector="finance"),
        gh("extrahop", "ExtraHop", "extrahopnetworks", sector="tech"),
        gh("qualtrics", "Qualtrics", "qualtrics", sector="tech"),
        # ── Seattle metro — verified Lever ────────────────────────────────────
        lever_it("outreach", "Outreach", "outreach", sector="tech"),
        lever_it("rover", "Rover", "rover", sector="tech"),
        lever_it("highspot", "Highspot", "highspot", sector="tech"),
        lever_it("getty-images", "Getty Images", "gettyimages", sector="tech"),
        # ── NYC metro — verified Greenhouse ───────────────────────────────────
        gh("yext", "Yext", "yext", sector="tech"),
        gh("iex", "IEX", "iex", sector="finance"),
        gh("peloton", "Peloton", "peloton", sector="tech", layoff_prone=True),
        gh("squarespace", "Squarespace", "squarespace", sector="tech"),
        gh("flatiron-health", "Flatiron Health", "flatironhealth", sector="healthtech"),
    ]


def merge_company(existing: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(existing)
    for key, value in patch.items():
        if value is None and key in merged:
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged


def apply(base: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    by_id = {c["id"]: c for c in base["companies"]}
    log: list[str] = []

    for patch in new_or_upgraded_companies():
        cid = patch["id"]
        if cid in by_id:
            by_id[cid] = merge_company(by_id[cid], patch)
            log.append(f"upgraded: {cid}")
        else:
            by_id[cid] = patch
            log.append(f"added: {cid}")

    base["companies"] = sorted(by_id.values(), key=lambda c: c["id"])
    return base, log


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write quickjobs.david.base.json")
    args = parser.parse_args()

    base = hub_tools.load_base_bundle()
    before = len(base["companies"])
    updated, log = apply(base)

    OUT_PREVIEW.parent.mkdir(parents=True, exist_ok=True)
    OUT_PREVIEW.write_text(
        json.dumps({"log": log, "count": len(updated["companies"])}, indent=2),
        encoding="utf-8",
    )

    for line in log:
        print(line)
    print(f"companies: {before} -> {len(updated['companies'])}")

    if args.apply:
        hub_tools.save_base_bundle(updated)
        print(f"wrote {BASE_JSON}")
    else:
        print(f"dry-run preview: {OUT_PREVIEW}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
