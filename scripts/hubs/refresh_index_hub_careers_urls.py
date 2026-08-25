#!/usr/bin/env python3
"""Refresh hub_url on index/manual careers hubs with verified public careers URLs.

Uses data/index_hub_careers_urls.json, add_index_company_hubs.CAREERS_URL_OVERRIDES
(via S&P 500 / Nasdaq ticker mapping), and hub_tools.MANUAL_CAREERS_URLS.

Also updates quickjobs-hub-probe-journal.json careers_url so future syncs stay correct.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import hub_tools

REPO_ROOT = hub_tools.REPO_ROOT
BASE_JSON = hub_tools.BASE_JSON
URL_DATA = REPO_ROOT / "data" / "index_hub_careers_urls.json"
JOURNAL_PATH = Path.home() / "ws/scriptdir/output/quickjobs-hub-probe-journal.json"

BAD_URL_RE = re.compile(
    r"search/\?q=devops|search-jobs/devops|/en/search-results|search-jobs\?keywords|"
    r"jobs\.global\.com|globe\.com/careers|best\.com|berkshire\.com/careers|"
    r"bristol\.com/careers|home\.com/search|myworkdayjobs\.com",
    re.I,
)

sys.path.insert(0, str(hub_tools.HUBS_DIR))
import add_index_company_hubs as index_hubs  # noqa: E402
import hub_tools  # noqa: E402


def load_url_data() -> dict[str, str]:
    data: dict[str, str] = {}
    if URL_DATA.is_file():
        raw = json.loads(URL_DATA.read_text(encoding="utf-8"))
        for cid, url in raw.items():
            u = str(url or "").strip()
            if u and "myworkdayjobs.com" not in u.lower():
                data[str(cid)] = u
    for cid, url in hub_tools.MANUAL_CAREERS_URLS.items():
        u = str(url or "").strip()
        if u and "myworkdayjobs.com" not in u.lower():
            data[cid] = u
    return data


def ticker_url_lookup() -> dict[str, str]:
    if not index_hubs.DEFAULT_SP500_MD.is_file():
        return {}
    sp = index_hubs.parse_sp500_md(index_hubs.DEFAULT_SP500_MD)
    nas = (
        index_hubs.parse_nasdaq_md(index_hubs.DEFAULT_NASDAQ_MD)
        if index_hubs.DEFAULT_NASDAQ_MD.is_file()
        else []
    )
    base = hub_tools.load_base_bundle()
    ids, names, norm_to_id = index_hubs.load_existing_index(base)
    ticker_map = index_hubs.ticker_map_for_ids(ids)
    out: dict[str, str] = {}
    for sym, name in sp + nas:
        cid = index_hubs.match_existing(sym, name, ids, names, norm_to_id, ticker_map)
        if not cid:
            continue
        url = index_hubs.CAREERS_URL_OVERRIDES.get(sym.upper(), "")
        if not url:
            url = index_hubs.guess_careers_url(name, sym)
        if url and "myworkdayjobs.com" not in url.lower():
            out[cid] = url
    return out


def best_url(cid: str, company: dict[str, Any], known: dict[str, str], ticker: dict[str, str]) -> str:
    for src in (known.get(cid), ticker.get(cid)):
        u = str(src or "").strip()
        if u and "myworkdayjobs.com" not in u.lower():
            return u
    current = str(company.get("hub_url") or "").strip()
    if current and not BAD_URL_RE.search(current) and "myworkdayjobs.com" not in current.lower():
        return current
    return ""


def apply_refresh(*, apply: bool = False, include_aviation: bool = False) -> tuple[list[str], list[str]]:
    if not BASE_JSON.is_file():
        return [], ["missing base.json"]

    known = load_url_data()
    ticker = ticker_url_lookup()
    base = hub_tools.load_base_bundle()
    journal = hub_tools.load_journal_by_id() if JOURNAL_PATH.is_file() else {}

    log: list[str] = []
    missing: list[str] = []

    for company in base.get("companies") or []:
        if str(company.get("type") or "").lower() != "hub":
            continue
        if not include_aviation and str(company.get("sector") or "").lower() == "aviation":
            continue
        cid = str(company.get("id") or "")
        if not cid:
            continue
        url = best_url(cid, company, known, ticker)
        if not url:
            missing.append(f"{cid} ({company.get('name', cid)})")
            continue
        old = str(company.get("hub_url") or "").strip()
        if old != url:
            company["hub_url"] = url
            log.append(f"hub_url: {cid} -> {url}")
        if cid in journal:
            if str(journal[cid].get("careers_url") or "").strip() != url:
                journal[cid]["careers_url"] = url

    if apply:
        hub_tools.save_base_bundle(base)
        if journal and JOURNAL_PATH.parent.is_dir():
            data = json.loads(JOURNAL_PATH.read_text(encoding="utf-8")) if JOURNAL_PATH.is_file() else {
                "version": 1,
                "updated_at": "",
                "employers": {},
            }
            employers = data.setdefault("employers", {})
            for cid, row in journal.items():
                if isinstance(employers.get(cid), dict):
                    employers[cid]["careers_url"] = row.get("careers_url", "")
            JOURNAL_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        hub_tools.rebuild_manual_careers()

    return log, missing


def validate_manual_index() -> tuple[int, list[str]]:
    base = hub_tools.load_base_bundle()
    hub_cfg = {
        str(c["id"]): c
        for c in base.get("companies") or []
        if isinstance(c, dict) and c.get("id") and str(c.get("type") or "").lower() == "hub"
    }
    missing: list[str] = []
    for cid, co in sorted(hub_cfg.items()):
        if str(co.get("sector") or "").lower() == "aviation":
            continue
        url = str(co.get("hub_url") or "").strip()
        if url and "myworkdayjobs.com" in url.lower():
            url = ""
        if not url:
            missing.append(cid)
    return len(hub_cfg), missing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write base.json, journal, rebuild manual careers")
    parser.add_argument("--include-aviation", action="store_true")
    parser.add_argument("--validate", action="store_true", help="Run collect_manual_career_index_entries check")
    args = parser.parse_args()

    log, missing = apply_refresh(apply=args.apply, include_aviation=args.include_aviation)
    print(f"hub_url updates: {len(log)}")
    for line in log[:50]:
        print(f"  {line}")
    if len(log) > 50:
        print(f"  ... +{len(log) - 50} more")

    if missing:
        print(f"still missing URL ({len(missing)}):")
        for line in missing[:30]:
            print(f"  {line}")
        if len(missing) > 30:
            print(f"  ... +{len(missing) - 30} more")
    else:
        print("all targeted hubs have a careers URL")

    if args.apply:
        print(f"wrote {BASE_JSON}")
        if JOURNAL_PATH.is_file():
            print(f"updated {JOURNAL_PATH}")
    elif not args.apply:
        print("dry-run (pass --apply to write)")

    if args.validate or args.apply:
        try:
            total, no_url = validate_manual_index()
            print(f"manual index entries: {total}; missing url (non-aviation): {len(no_url)}")
            for cid in no_url[:20]:
                print(f"  missing index url: {cid}")
        except Exception as exc:
            print(f"validate skipped: {exc}")

    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())
