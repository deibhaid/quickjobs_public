#!/usr/bin/env python3
"""Print quickjobs scrape_selected company ids in search order (excludes applied)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SHARED_DIR = REPO_ROOT / "scripts" / "_shared"
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))
import config_bundle  # noqa: E402

_FETCH_TYPE_ORDER: dict[str, int] = {
    "hub": 0,
    "entries": 1,
    "rss": 2,
    "json_feed": 3,
    "qualityinfo": 3,
    "lever": 4,
    "greenhouse": 5,
    "ashby": 5,
    "paylocity": 6,
    "html_jsonld": 7,
    "smartrecruiters": 8,
    "bullhorn_public": 8,
    "jeffersonfrank": 8,
    "oracle_hcm": 8,
    "taleo_cws": 8,
    "talentbrew": 8,
    "icims": 8,
    "phenom": 8,
    "dice_mcp": 11,
    "linkedin": 11,
    "apple": 12,
    "playwright": 20,
}


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in overlay.items():
        if key == "companies":
            continue
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_merged_config() -> dict[str, Any]:
    base = config_bundle.load_base_bundle(REPO_ROOT / "quickjobs.david.base.json")
    profile = json.loads((REPO_ROOT / "quickjobs.david.profile.json").read_text(encoding="utf-8"))
    cfg = _deep_merge(base, profile)
    by_id = {c["id"]: c for c in base.get("companies", []) if c.get("id")}
    for company in profile.get("companies", []):
        if company.get("id"):
            by_id[company["id"]] = {**by_id.get(company["id"], {}), **company}
    cfg["companies"] = list(by_id.values())
    return cfg


def companies_in_search_order(companies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    indexed = list(enumerate(companies))
    indexed.sort(
        key=lambda item: (
            _FETCH_TYPE_ORDER.get(str(item[1].get("type") or "").lower(), 15),
            item[0],
        )
    )
    return [company for _, company in indexed]


def company_is_hub_link(company: dict[str, Any]) -> bool:
    return str(company.get("type") or "").lower() == "hub"


def company_uses_playwright_browser(company: dict[str, Any]) -> bool:
    kind = str(company.get("type") or "").lower()
    if kind == "playwright":
        return True
    if company.get("playwright") or company.get("use_playwright"):
        return True
    if kind == "workday" and str(company.get("workday_fetch") or "cxs").lower() == "playwright":
        return True
    if kind == "eightfold" and str(company.get("eightfold_fetch") or "pcsx").lower() == "playwright":
        return True
    return False


def scrape_selected(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    exclude = {str(cid) for cid in (cfg.get("company_ids_exclude") or []) if str(cid).strip()}
    company_list = companies_in_search_order(cfg.get("companies") or [])
    return [
        c
        for c in company_list
        if c.get("id") and not company_is_hub_link(c) and str(c["id"]) not in exclude
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="List scrape_selected company order for quickjobs.")
    parser.add_argument("--start", type=int, default=1, help="1-based start position (default: 1)")
    parser.add_argument("--end", type=int, default=0, help="1-based end position inclusive (0 = all)")
    parser.add_argument("--playwright-only", action="store_true", help="Only Playwright-phase companies")
    parser.add_argument("--http-only", action="store_true", help="Only HTTP/API-phase companies")
    parser.add_argument("--ids-only", action="store_true", help="Print ids one per line")
    parser.add_argument("--csv", action="store_true", help="Print comma-separated ids")
    args = parser.parse_args(argv)

    cfg = load_merged_config()
    selected = scrape_selected(cfg)
    if args.playwright_only:
        selected = [c for c in selected if company_uses_playwright_browser(c)]
    elif args.http_only:
        selected = [c for c in selected if not company_uses_playwright_browser(c)]

    start = max(1, args.start)
    end = len(selected) if args.end <= 0 else min(len(selected), args.end)
    if start > end:
        print("No companies in range.", file=__import__("sys").stderr)
        return 1

    slice_rows = selected[start - 1 : end]
    if args.ids_only:
        for row in slice_rows:
            print(row["id"])
        return 0
    if args.csv:
        print(",".join(str(row["id"]) for row in slice_rows))
        return 0

    http_n = sum(1 for c in selected if not company_uses_playwright_browser(c))
    pw_n = len(selected) - http_n
    print(f"scrape_selected={len(scrape_selected(cfg))} shown={len(selected)} http={http_n} pw={pw_n}")
    for idx, row in enumerate(slice_rows, start=start):
        phase = "PW" if company_uses_playwright_browser(row) else "HTTP"
        label = row.get("label") or row.get("name") or ""
        print(f"{idx:4d}  {row['id']:<28}  {str(row.get('type') or ''):<16}  {phase}  {label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
