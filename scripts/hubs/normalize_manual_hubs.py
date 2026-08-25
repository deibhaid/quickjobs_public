#!/usr/bin/env python3
"""Normalize manual hub labels and restore preferred big-tech employers.

- Relabel (S&P 500 hub) / (Nasdaq-100 hub) → (manual careers hub)
- Move Google and Apple from section=excluded to matching (live scrape)
- Drop amazon-excluded (amazon-jobs is the canonical Amazon entry)
- Remove saic from profile company_ids_exclude if present

Run: ~/.v/bin/python normalize_manual_hubs.py --apply
"""

from __future__ import annotations

import argparse
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

import hub_tools

REPO_ROOT = hub_tools.REPO_ROOT
BASE_JSON = hub_tools.BASE_JSON
PROFILE_JSON = REPO_ROOT / "quickjobs.david.profile.json"

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

LABEL_INDEX_RE = re.compile(r"\((S&P 500|Nasdaq-100) hub\)", re.I)
NOTE_INDEX_RE = re.compile(r"^(S&P 500|Nasdaq-100) index —", re.I)


def normalize_hub_text(label: str, note: str | None) -> tuple[str, str | None]:
    new_label = LABEL_INDEX_RE.sub("(manual careers hub)", label)
    new_note = note
    if note:
        new_note = NOTE_INDEX_RE.sub("Manual careers link —", note)
    return new_label, new_note


def promote_google(existing: dict[str, Any]) -> dict[str, Any]:
    row = deepcopy(existing)
    row.update(
        {
            "section": "matching",
            "sector": "tech",
            "label": "Google (Remote US)",
            "default_loc": "remote",
            "search_keywords": IT_SEARCH_KEYWORDS,
            "skip_verify": True,
            "cache_ttl_hours": 12,
        }
    )
    row.pop("subsection", None)
    row.pop("subsection_warn", None)
    return row


def promote_apple(existing: dict[str, Any]) -> dict[str, Any]:
    row = deepcopy(existing)
    row.update(
        {
            "section": "matching",
            "sector": "tech",
            "label": "Apple (Remote US)",
            "default_loc": "remote",
            "search_keywords": IT_SEARCH_KEYWORDS,
            "skip_verify": True,
            "cache_ttl_hours": 12,
        }
    )
    row.pop("subsection", None)
    row.pop("subsection_warn", None)
    return row


def apply(base: dict[str, Any], profile: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    log: list[str] = []
    companies: list[dict[str, Any]] = []

    for company in base.get("companies", []):
        cid = str(company.get("id") or "")

        if cid == "amazon-excluded":
            log.append("removed: amazon-excluded (use amazon-jobs)")
            continue

        if cid == "google":
            companies.append(promote_google(company))
            log.append("promoted: google → matching")
            continue

        if cid == "apple":
            companies.append(promote_apple(company))
            log.append("promoted: apple → matching")
            continue

        row = deepcopy(company)
        label = str(row.get("label") or "")
        note = row.get("hub_note")
        if LABEL_INDEX_RE.search(label) or (note and NOTE_INDEX_RE.search(str(note))):
            new_label, new_note = normalize_hub_text(label, str(note) if note else None)
            if new_label != label:
                row["label"] = new_label
                log.append(f"relabeled: {cid}")
            if new_note and new_note != note:
                row["hub_note"] = new_note

        companies.append(row)

    base["companies"] = sorted(companies, key=lambda c: c["id"])

    excludes = list(profile.get("company_ids_exclude") or [])
    removed: list[str] = []
    for drop in ("saic",):
        if drop in excludes:
            excludes.remove(drop)
            removed.append(drop)
    if removed:
        profile["company_ids_exclude"] = sorted(excludes)
        log.append(f"profile un-excluded: {', '.join(removed)}")

    return base, profile, log


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    base = hub_tools.load_base_bundle()
    profile = json.loads(PROFILE_JSON.read_text(encoding="utf-8"))
    updated_base, updated_profile, log = apply(base, profile)

    for line in log[:10]:
        print(line)
    if len(log) > 10:
        print(f"... and {len(log) - 10} more")
    print(f"companies: {len(base['companies'])} -> {len(updated_base['companies'])}")

    if args.apply:
        hub_tools.save_base_bundle(updated_base)
        PROFILE_JSON.write_text(json.dumps(updated_profile, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {BASE_JSON}")
        print(f"wrote {PROFILE_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
