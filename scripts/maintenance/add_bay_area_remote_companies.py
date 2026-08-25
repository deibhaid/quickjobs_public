#!/usr/bin/env python3
"""Add Bay Area remote scrapeable platform/SRE employers from research report.

Source: ~/ws/scriptdir/output/quickjobs-reports/bay-area-remote-scrapeable-companies-2026-06-15.md

Idempotent merge into quickjobs.base.json. Greenhouse/Lever boards verified via
public API before inclusion. Upgrades Wiz hub -> greenhouse (wizinc).

Run: ~/.v/bin/python add_bay_area_remote_companies.py --apply
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

OUT_PREVIEW = hub_tools.report_path("quickjobs-bay-area-remote-added.json")

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
    return row


def promote_patch(company_id: str, **fields: Any) -> dict[str, Any]:
    return {"id": company_id, **fields}


def new_or_upgraded_companies() -> list[dict[str, Any]]:
    return [
        # ── Report top priorities: verified Greenhouse ─────────────────────────
        gh("redpanda", "Redpanda", "redpandadata", sector="tech"),
        gh("clickhouse", "ClickHouse", "clickhouse", sector="tech"),
        gh("tailscale", "Tailscale", "tailscale", sector="tech"),
        gh("samsara", "Samsara", "samsara", sector="tech"),
        gh("jfrog", "JFrog", "jfrog", sector="tech"),
        gh("temporal", "Temporal", "temporaltechnologies", sector="tech"),
        gh("discord", "Discord", "discord", sector="tech"),
        gh("cockroach-labs", "Cockroach Labs", "cockroachlabs", sector="tech"),
        gh("harness", "Harness", "harnessinc", sector="tech"),
        gh("coreweave", "CoreWeave", "coreweave", sector="tech"),
        gh("together-ai", "Together AI", "togetherai", sector="tech"),
        gh("fireworks-ai", "Fireworks AI", "fireworksai", sector="tech"),
        gh("marqeta", "Marqeta", "marqeta", sector="finance"),
        gh("checkr", "Checkr", "checkr", sector="tech"),
        gh("faire", "Faire", "faire", sector="ecommerce"),
        gh("amplitude", "Amplitude", "amplitude", sector="tech"),
        gh("airtable", "Airtable", "airtable", sector="tech"),
        gh("unity", "Unity", "unity3d", sector="tech", layoff_prone=True),
        gh("nextdoor", "Nextdoor", "nextdoor", sector="tech"),
        gh("bill-com", "Bill.com", "billcom", sector="finance"),
        gh("10x-genomics", "10x Genomics", "10xgenomics", sector="healthtech"),
        gh("tenable", "Tenable", "tenableinc", sector="tech"),
        gh("box", "Box", "boxinc", sector="tech"),
        gh("sourcegraph", "Sourcegraph", "sourcegraph91", sector="tech"),
        gh("planetscale", "PlanetScale", "planetscale", sector="tech"),
        # ── Lever (API verified) ─────────────────────────────────────────────
        lever_it("coupa", "Coupa", "coupa", sector="tech"),
        lever_it("grail", "Grail", "grailbio", sector="healthtech"),
        # ── Hub -> Greenhouse upgrade ──────────────────────────────────────────
        promote_patch(
            "wiz",
            type="greenhouse",
            board="wizinc",
            browse_url="https://boards.greenhouse.io/wizinc",
            label="Wiz (Remote US)",
            discover=True,
            search_keywords=IT_SEARCH_KEYWORDS,
            default_salary="maybe",
            cache_ttl_hours=12,
            hub_url=None,
            hub_note=None,
        ),
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
    parser.add_argument("--apply", action="store_true", help="Write quickjobs.base.json")
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
