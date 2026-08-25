#!/usr/bin/env python3
"""One-off deep probe for F500 hub samples: HTML fingerprint + API attempts."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import hub_tools

sys.path.insert(0, str(hub_tools.HUBS_DIR))
import discover_career_endpoints as discover  # noqa: E402
import fingerprint_hub_ats as fp  # noqa: E402
import probe_hub_scrape_methods as probe  # noqa: E402

CURL = [
    "curl",
    "-sL",
    "--compressed",
    "--max-time",
    "25",
    "-A",
    "Mozilla/5.0 (compatible; QuickJobsF500Probe/1.0)",
]

SAMPLE_IDS = [
    "bank-of-america",
    "caterpillar",
    "best-buy",
    "broadcom",
    "cardinal-health",
    "automatic-data-processing",
    "bristol-myers-squibb",
    "biogen",
    "centene",
    "booking",
    "c-h-robinson",
    "broadridge-financial-solutions",
    "berkshire-hathaway",
    "blackstone",
    "cbre-group",
]


def curl_fetch(url: str) -> tuple[int, str, str]:
    proc = subprocess.run(
        [*CURL, "-w", "\n%{http_code}", url],
        capture_output=True,
        timeout=30,
    )
    if proc.returncode != 0:
        return 599, url, ""
    raw = proc.stdout or b""
    parts = raw.rsplit(b"\n", 1)
    if len(parts) == 2 and parts[1].strip().isdigit():
        code = int(parts[1].strip())
        body_raw = parts[0]
    else:
        code = 200
        body_raw = raw
    body = body_raw.decode("utf-8", errors="replace")
    return code, url, body


def probe_one(co: dict) -> dict:
    cid = str(co["id"])
    hub = str(co.get("hub_url") or "").strip()
    result = {
        "company": cid,
        "hub_url": hub,
        "ats_markers": "",
        "api_method": "",
        "fetcher_type": "",
        "blocked_why": "",
    }
    if not hub:
        result["blocked_why"] = "no hub_url"
        return result

    urls = probe.careers_urls_for_target({"careers_url": hub, "hub_url": hub})
    # Also try jobs/careers subdomain variants from discover
    from discover_hub_ats_paths import slug_variants, url_candidates  # noqa: WPS433

    extra = url_candidates(co, None)[:8]
    for u in extra:
        if u not in urls:
            urls.append(u)

    best_row = None
    best_url = hub
    markers: list[str] = []

    for url in urls[:12]:
        code, final_url, body = curl_fetch(url)
        if code != 200 or not body:
            continue
        blob = f"{final_url}\n{body}"
        found = fp.fingerprint_markers(blob)
        if found and not markers:
            markers = found
            best_url = final_url

        probes = (
            lambda: probe.probe_phenom(cid, hub, final_url, body),
            lambda: probe.probe_oracle_hcm(cid, url, body, final_url),
            lambda: probe.probe_greenhouse(cid, url, body),
            lambda: probe.probe_eightfold_pcsx(cid, final_url),
            lambda: probe.probe_successfactors(cid, final_url, body),
            lambda: probe.probe_talentbrew(cid, final_url or url),
            lambda: discover.probe_lever(cid, body, final_url),
            lambda: discover.probe_smartrecruiters(cid, body, final_url),
            lambda: discover.probe_icims(cid, body, final_url),
            lambda: discover.probe_ashby(cid, body, final_url),
        )
        for fn in probes:
            row = fn()
            if row and row.status == "ok":
                if not best_row or int(row.total_jobs or 0) > int(best_row.total_jobs or 0):
                    best_row = row
                    best_url = final_url

    result["ats_markers"] = "|".join(markers) if markers else "(none)"
    if best_row:
        result["api_method"] = best_row.method
        result["fetcher_type"] = probe.METHOD_TO_TYPE.get(best_row.method, best_row.method)
        if best_row.method in ("lever", "smartrecruiters", "icims", "ashby"):
            result["fetcher_type"] = best_row.method
    else:
        if markers:
            result["blocked_why"] = f"ATS detected ({result['ats_markers']}) but no public API probe hit"
        elif "myworkdayjobs" in hub.lower():
            result["blocked_why"] = "Workday URL (CXS blocked off-VPN)"
        else:
            result["blocked_why"] = "no ATS marker or API on probed URLs"
    return result


def main() -> int:
    cfg = json.loads(hub_tools.BASE_JSON.read_text())
    by_id = {c["id"]: c for c in cfg["companies"]}
    print("company\thub_url\tats_markers\tapi_method\tfetcher_type\tblocked_why")
    for cid in SAMPLE_IDS:
        co = by_id.get(cid)
        if not co:
            print(f"{cid}\t(missing)\t\t\t\tnot in base")
            continue
        r = probe_one(co)
        print(
            f"{r['company']}\t{r['hub_url']}\t{r['ats_markers']}\t"
            f"{r['api_method']}\t{r['fetcher_type']}\t{r['blocked_why']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
