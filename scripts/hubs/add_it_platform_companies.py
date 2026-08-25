#!/usr/bin/env python3
"""Add or upgrade IT/platform employers across all industry sectors.

Idempotent merge into quickjobs.david.base.json. Prefer live scrapers (Greenhouse,
Lever, Phenom, Playwright) in section=matching; fall back to matching hubs when ATS
is blocked or unknown.

Run: ~/.v/bin/python add_it_platform_companies.py --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import hub_tools

BASE = hub_tools.BASE_JSON
BASE_JSON = hub_tools.BASE_JSON

OUT_PREVIEW = hub_tools.report_path("quickjobs-it-platform-added.json")

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


def hub_it(
    company_id: str,
    name: str,
    hub_url: str,
    *,
    label: str | None = None,
    sector: str | None = None,
    note: str = "IT/platform careers — verify remote US on each req",
) -> dict[str, Any]:
    row = deepcopy(MATCHING_DEFAULTS)
    row.pop("discover", None)
    row.update(
        {
            "id": company_id,
            "name": name,
            "label": label or f"{name} (IT careers link)",
            "type": "hub",
            "hub_url": hub_url,
            "hub_note": note,
        }
    )
    if sector:
        row["sector"] = sector
    return row


def promote_patch(company_id: str, **fields: Any) -> dict[str, Any]:
    patch = {"id": company_id, **fields}
    return patch


def workday_it(
    company_id: str,
    name: str,
    browse_url: str,
    *,
    label: str | None = None,
    sector: str | None = None,
    workday_fetch: str = "cxs",
) -> dict[str, Any]:
    row = deepcopy(MATCHING_DEFAULTS)
    row.pop("discover", None)
    row.update(
        {
            "id": company_id,
            "name": name,
            "label": label or f"{name} (Remote US — Workday)",
            "type": "playwright",
            "playwright_kind": "workday",
            "workday_fetch": workday_fetch,
            "browse_url": browse_url,
            "max_details": 12,
            "skip_verify": True,
        }
    )
    if sector:
        row["sector"] = sector
    return row


def icims_it(
    company_id: str,
    name: str,
    host: str,
    *,
    label: str | None = None,
    sector: str | None = None,
) -> dict[str, Any]:
    browse = f"https://{host}.icims.com/jobs/search?ss=1&in_iframe=1"
    template = f"https://{host}.icims.com/jobs/search?searchKeyword={{query}}&ss=1&in_iframe=1"
    row = deepcopy(MATCHING_DEFAULTS)
    row.pop("discover", None)
    row.update(
        {
            "id": company_id,
            "name": name,
            "label": label or f"{name} (Remote US — iCIMS)",
            "type": "playwright",
            "playwright_kind": "icims",
            "browse_url": browse,
            "search_url_template": template,
            "max_details": 12,
            "skip_verify": True,
        }
    )
    if sector:
        row["sector"] = sector
    return row


def new_or_upgraded_companies() -> list[dict[str, Any]]:
    return [
        # ── Live scrape: Greenhouse (API verified) ───────────────────────────
        gh("instacart", "Instacart", "instacart", sector="ecommerce"),
        gh("databricks", "Databricks", "databricks", sector="tech"),
        gh("roblox", "Roblox", "roblox", sector="tech"),
        gh("anthropic", "Anthropic", "anthropic", sector="tech"),
        gh("jamf", "Jamf", "jamf", sector="tech"),
        gh("seatgeek", "SeatGeek", "seatgeek", sector="ecommerce"),
        gh("scale-ai", "Scale AI", "scaleai", sector="tech"),
        gh("reddit", "Reddit", "reddit", sector="tech"),
        gh("pinterest", "Pinterest", "pinterest", sector="tech"),
        gh(
            "epic-systems",
            "Epic Systems",
            "epicgames",
            label="Epic Systems (healthcare IT — Greenhouse)",
            sector="healthcare",
            browse_url="https://boards.greenhouse.io/epicgames",
        ),
        # Promote from hubs / fix section
        promote_patch(
            "airbnb",
            section="matching",
            type="greenhouse",
            board="airbnb",
            browse_url="https://boards.greenhouse.io/airbnb",
            discover=True,
            search_keywords=IT_SEARCH_KEYWORDS,
            sector="ecommerce",
            default_salary="maybe",
        ),
        # ── Matching hubs: large IT employers (every sector) ─────────────────
        hub_it(
            "openai",
            "OpenAI",
            "https://openai.com/careers",
            sector="tech",
        ),
        hub_it(
            "snowflake",
            "Snowflake",
            "https://careers.snowflake.com/us/en",
            sector="tech",
        ),
        hub_it(
            "confluent",
            "Confluent",
            "https://careers.confluent.io/",
            sector="tech",
        ),
        hub_it(
            "akamai",
            "Akamai",
            "https://www.akamai.com/careers",
            sector="tech",
        ),
        hub_it(
            "hashicorp",
            "HashiCorp",
            "https://www.hashicorp.com/en/careers",
            sector="tech",
        ),
        hub_it(
            "snyk",
            "Snyk",
            "https://snyk.io/careers/",
            sector="tech",
        ),
        promote_patch(
            "wiz",
            section="matching",
            type="greenhouse",
            board="wizinc",
            browse_url="https://boards.greenhouse.io/wizinc",
            discover=True,
            search_keywords=IT_SEARCH_KEYWORDS,
            sector="tech",
            label="Wiz (Remote US)",
            default_salary="maybe",
            cache_ttl_hours=12,
        ),
        hub_it(
            "red-hat",
            "Red Hat",
            "https://www.redhat.com/en/jobs",
            sector="tech",
        ),
        hub_it(
            "snap",
            "Snap",
            "https://careers.snap.com/",
            sector="tech",
        ),
        hub_it(
            "aeolus",
            "Aeolus",
            "https://www.aeolus.bio/careers",
            sector="healthtech",
        ),
        hub_it(
            "uber",
            "Uber",
            "https://jobs.uber.com/",
            label="Uber (IT careers link)",
            sector="logistics",
            note="Public careers portal — verify remote US on each req",
        ),
        hub_it(
            "collins-aerospace",
            "Collins Aerospace",
            "https://jobs.collinsaerospace.com/",
            label="Collins Aerospace (RTX — aviation IT + engineering)",
            sector="defense",
            note="Collins is RTX; search platform/devops roles — may mirror RTX phenom listings",
        ),
        hub_it(
            "ge-aerospace",
            "GE Aerospace",
            "https://jobs.gecareers.com/global/en/ge-aerospace",
            label="GE Aerospace (aviation IT + engineering)",
            sector="aviation",
        ),
        hub_it(
            "foreflight",
            "ForeFlight",
            "https://foreflight.com/about/careers/",
            label="ForeFlight (aviation software — IT)",
            sector="aviation",
        ),
        hub_it(
            "garmin",
            "Garmin",
            "https://careers.garmin.com/",
            label="Garmin (avionics software/hardware — IT)",
            sector="aviation",
        ),
        hub_it(
            "faa-it",
            "FAA",
            "https://www.usajobs.gov/Search?k=faa%20information%20technology",
            label="FAA (USAJOBS — IT)",
            sector="aviation",
            note="Federal aviation IT via USAJOBS",
        ),
        # ── Sector breadth: healthcare, finance, retail, energy, telecom ─────
        hub_it(
            "kaiser-it",
            "Kaiser Permanente (IT)",
            "https://jobs.kaiserpermanente.org/",
            sector="healthcare",
        ),
        hub_it(
            "providence-it",
            "Providence Health",
            "https://providence.jobs/",
            label="Providence Health (Pacific NW — IT)",
            sector="healthcare",
        ),
        hub_it(
            "legacy-health-it",
            "Legacy Health",
            "https://legacyhealth.org/careers/",
            label="Legacy Health (Portland — IT)",
            sector="healthcare",
        ),
        hub_it(
            "comcast-it",
            "Comcast",
            "https://jobs.comcast.com/",
            sector="telecom",
        ),
        hub_it(
            "t-mobile-it",
            "T-Mobile",
            "https://careers.t-mobile.com/",
            sector="telecom",
        ),
        hub_it(
            "verizon-it",
            "Verizon",
            "https://mycareer.verizon.com/",
            sector="telecom",
        ),
        hub_it(
            "chevron-it",
            "Chevron",
            "https://careers.chevron.com/",
            sector="energy",
        ),
        hub_it(
            "exxonmobil-it",
            "ExxonMobil",
            "https://jobs.exxonmobil.com/",
            sector="energy",
        ),
        hub_it(
            "nike-it",
            "Nike (IT)",
            "https://jobs.nike.com/",
            label="Nike (IT — verify new reqs outside past employer)",
            sector="ecommerce",
        ),
        hub_it(
            "disney-it",
            "Disney",
            "https://jobs.disneycareers.com/",
            sector="entertainment",
        ),
        hub_it(
            "ea-it",
            "Electronic Arts",
            "https://ea.gr8people.com/",
            sector="entertainment",
        ),
        hub_it(
            "marriott-it",
            "Marriott",
            "https://careers.marriott.com/",
            sector="hospitality",
        ),
        hub_it(
            "hilton-it",
            "Hilton",
            "https://jobs.hilton.com/",
            sector="hospitality",
        ),
        hub_it(
            "fedex-it",
            "FedEx (IT)",
            "https://careers.fedex.com/",
            label="FedEx (IT — separate from pilot scrape)",
            sector="logistics",
        ),
        hub_it(
            "ups-it",
            "UPS (IT)",
            "https://www.jobs-ups.com/",
            label="UPS (IT — separate from pilot scrape)",
            sector="logistics",
        ),
        # ── Priority targets: live scrape upgrades (applied last in merge order) ─
        workday_it(
            "nvidia",
            "NVIDIA",
            "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite",
            sector="tech",
            workday_fetch="playwright",
        ),
        workday_it(
            "saic",
            "SAIC",
            "https://saic.wd1.myworkdayjobs.com/SAIC_Careers",
            sector="defense",
            workday_fetch="playwright",
        ),
        workday_it(
            "boeing-it",
            "Boeing (IT)",
            "https://boeing.wd1.myworkdayjobs.com/en-US/EXTERNAL_CAREERS",
            label="Boeing (IT — Workday; separate from pilot scrape)",
            sector="defense",
            workday_fetch="cxs",
        ),
        icims_it(
            "alaska-airlines-it",
            "Alaska Airlines (IT)",
            "careers-alaskaair",
            label="Alaska Airlines (IT — iCIMS; separate from pilot scrape)",
            sector="aviation",
        ),
        promote_patch(
            "anduril",
            section="matching",
            type="greenhouse",
            board="andurilindustries",
            browse_url="https://boards.greenhouse.io/andurilindustries",
            discover=True,
            search_keywords=IT_SEARCH_KEYWORDS,
            sector="defense",
            label="Anduril (Remote US)",
            default_salary="maybe",
            cache_ttl_hours=12,
        ),
        promote_patch(
            "rtx",
            section="matching",
            sector="defense",
            search_keywords=IT_SEARCH_KEYWORDS,
        ),
        promote_patch(
            "leidos",
            section="matching",
            sector="defense",
            search_keywords=IT_SEARCH_KEYWORDS,
        ),
        promote_patch(
            "garmin",
            section="matching",
            sector="aviation",
            search_keywords=IT_SEARCH_KEYWORDS,
        ),
        promote_patch(
            "akamai",
            section="matching",
            sector="tech",
            search_keywords=IT_SEARCH_KEYWORDS,
        ),
        promote_patch(
            "snowflake",
            section="matching",
            sector="tech",
            search_keywords=IT_SEARCH_KEYWORDS,
        ),
        promote_patch(
            "openai",
            section="matching",
            sector="tech",
            search_keywords=IT_SEARCH_KEYWORDS,
        ),
        promote_patch(
            "red-hat",
            section="matching",
            sector="tech",
            search_keywords=IT_SEARCH_KEYWORDS,
        ),
        promote_patch(
            "uber",
            section="matching",
            sector="logistics",
            search_keywords=IT_SEARCH_KEYWORDS,
        ),
    ]


def merge_company(existing: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(existing)
    merged.update(patch)
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
    updated, log = apply(base)

    OUT_PREVIEW.parent.mkdir(parents=True, exist_ok=True)
    OUT_PREVIEW.write_text(
        json.dumps({"log": log, "count": len(updated["companies"])}, indent=2),
        encoding="utf-8",
    )

    for line in log:
        print(line)
    print(f"companies: {len(base['companies'])} -> {len(updated['companies'])}")

    if args.apply:
        hub_tools.save_base_bundle(updated)
        print(f"wrote {BASE_JSON}")
    else:
        print(f"dry-run preview: {OUT_PREVIEW}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
