#!/usr/bin/env python3
"""One-shot fixes for aviation manual career links: hub URLs, removals, Glassdoor meta."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_JSON = REPO_ROOT / "quickjobs.david.base.json"
META_JSON = REPO_ROOT / "quickjobs.david.manual-career-meta.json"

# Job boards / duplicates / rotary-wing employers (fixed-wing pilot board).
# IT hubs mis-tagged aviation — hide from aviation manual-career list.
AVIATION_SECTOR_CLEAR = frozenset({"foreflight", "garmin"})

REMOVE_IDS = frozenset(
    {
        "aviation-interviews",
        "climbto350",
        "pilotjobsnetwork",
        "scenic-airlines",
        "piedmont-flight-ops",
        "k2-aviation",
        "blue-hawaiian-helicopters",
        "bristow-group",
        "erickson-inc",
        "maverick-helicopters",
        "papillon-grand-canyon",
        "phi-helicopters",
        "wings-air-helicopters",
        "air-methods",
        "life-flight-network",
        "guardian-flight",
        "reach-air-medical",
        "classic-air-medical",
        "med-trans",
        "aeolus",  # healthtech IT hub; not an aviation employer
        "faa-it",
        "ea-it",
        "verizon-it",
        "fedex-it",
        "marriott-it",
        "t-mobile-it",
    }
)

# Curated Glassdoor (rating, reviews, url). Reviews optional.
GLASSDOOR: dict[str, dict[str, str]] = {
    "10-tanker": (
        "3.4",
        "8",
        "https://www.glassdoor.com/Overview/Working-at-10-Tanker-Air-Carrier-EI_IE2336485.11,32.htm",
    ),
    "amazon-air-ati": (
        "3.3",
        "154",
        "https://www.glassdoor.com/Reviews/AmazonAir-Reviews-E2765785.htm",
    ),
    "airevac-lifeteam": (
        "3.7",
        "250",
        "https://www.glassdoor.com/Overview/Working-at-Air-Evac-Lifeteam-EI_IE152654.11,28.htm",
    ),
    "aero-agricultural": (
        "3.5",
        "50",
        "https://www.glassdoor.com/Overview/Working-at-Aerial-Applications-EI_IE1415919.11,30.htm",
    ),
    "contour-airlines": (
        "3.1",
        "102",
        "https://www.glassdoor.com/Overview/Working-at-Contour-Aviation-EI_IE464438.11,27.htm",
    ),
    "fedex-pilot-recruiting": (
        "4.0",
        "47",
        "https://www.glassdoor.com/Reviews/FedEx-Pilot-Reviews-EI_IE246.0,5_KO6,11.htm",
    ),
    "fedex-it": (
        "3.5",
        "500",
        "https://www.glassdoor.com/Reviews/FedEx-Information-Technology-Reviews-EI_IE246.0,5_KO6,28.htm",
    ),
    "otis-worldwide": (
        "3.6",
        "2443",
        "https://www.glassdoor.com/Overview/Working-at-OTIS-EI_IE7865.11,15.htm",
    ),
    "paramount-aviation": (
        "3.4",
        "120",
        "https://www.glassdoor.com/Reviews/Paramount-Resources-Reviews-E8761.htm",
    ),
    "rusts-flying-service": (
        "4.2",
        "12",
        "https://www.glassdoor.com/Salary/Rust-s-Flying-Service-Salaries-E10990136.htm",
    ),
    "piedmont-airlines": (
        "3.2",
        "957",
        "https://www.glassdoor.com/Overview/Working-at-Piedmont-Airlines-EI_IE14513.11,28.htm",
    ),
    "fedex": ("3.4", "34122", "https://www.glassdoor.com/Reviews/FedEx-Reviews-E246.htm"),
}


def _glassdoor_entry(triple: tuple[str, str, str]) -> dict[str, Any]:
    rating, reviews, url = triple
    return {"glassdoor": {"rating": rating, "reviews": reviews, "url": url}}


def apply_hub_url_patches(companies: list[dict[str, Any]]) -> list[str]:
    from add_aviation_pilot_companies import new_or_upgraded_companies

    patches = {
        c["id"]: c
        for c in new_or_upgraded_companies()
        if c.get("type") == "hub" and c.get("hub_url")
    }
    log: list[str] = []
    for company in companies:
        cid = company.get("id")
        patch = patches.get(cid)
        if not patch:
            continue
        if not company.get("hub_url"):
            company["hub_url"] = patch["hub_url"]
            log.append(f"hub_url: {cid}")
        for key in ("hub_note", "label", "name"):
            if key in patch and patch[key] and not company.get(key):
                company[key] = patch[key]
                log.append(f"{key}: {cid}")
    return log


def build_meta(companies: list[dict[str, Any]], existing: dict[str, Any]) -> dict[str, Any]:
    employers = dict(existing.get("employers") or {})
    for company in companies:
        cid = str(company.get("id") or "")
        if cid not in GLASSDOOR:
            continue
        employers[cid] = _glassdoor_entry(GLASSDOOR[cid])
    return {"employers": employers}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write base.json and manual-career-meta.json")
    args = parser.parse_args()

    base = hub_tools.load_base_bundle()
    meta_existing = json.loads(META_JSON.read_text(encoding="utf-8")) if META_JSON.is_file() else {}

    from add_aviation_pilot_companies import apply as apply_aviation

    base, av_log = apply_aviation(base)

    before = len(base["companies"])
    base["companies"] = [c for c in base["companies"] if c.get("id") not in REMOVE_IDS]
    removed = before - len(base["companies"])

    for company in base["companies"]:
        if company.get("id") in AVIATION_SECTOR_CLEAR:
            company.pop("sector", None)

    url_log = apply_hub_url_patches(base["companies"])
    meta = build_meta(base["companies"], meta_existing)

    print(f"aviation merge: {len(av_log)} changes")
    print(f"removed: {removed} companies")
    for line in url_log[:20]:
        print(f"  {line}")
    if len(url_log) > 20:
        print(f"  ... +{len(url_log) - 20} more hub_url patches")
    print(f"glassdoor meta employers: {len(meta['employers'])}")

    if args.apply:
        hub_tools.save_base_bundle(base)
        META_JSON.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {BASE_JSON}")
        print(f"wrote {META_JSON}")
    else:
        print("dry-run (pass --apply to write)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
