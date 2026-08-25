#!/usr/bin/env python3
"""Read-only ATS fingerprint for quickjobs hub employers only.

Does not read or write quickjobs.david.base.json except to list type=hub rows.
Output: ~/ws/scriptdir/output/quickjobs-hub-ats-fingerprint.tsv
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import hub_http
import hub_tools

BASE = hub_tools.BASE_JSON
BASE_JSON = hub_tools.BASE_JSON

BLOCKED_TSV = hub_tools.BLOCKED_TSV
OUT_TSV = hub_tools.report_path("quickjobs-hub-ats-fingerprint.tsv")
USER_AGENT = hub_http.BROWSER_USER_AGENT

# (label, regex on lowercased body + final URL)
ATS_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("greenhouse", re.compile(r"greenhouse\.io|boards-api\.greenhouse", re.I)),
    ("lever", re.compile(r"jobs\.lever\.co|api\.lever\.co", re.I)),
    ("ashby", re.compile(r"ashbyhq\.com|ashbyBoardSlug", re.I)),
    ("salesforce", re.compile(r"force\.com|my\.site\.com|salesforce\.com/.*career|lightning\.force", re.I)),
    ("taleo", re.compile(r"taleo\.net|tbe\.taleo", re.I)),
    ("icims", re.compile(r"[a-z0-9-]+\.icims\.com", re.I)),
    ("eightfold", re.compile(r"eightfold\.ai|/api/pcsx/", re.I)),
    ("phenom", re.compile(r"phenompeople|phenom\.com|/widgets", re.I)),
    ("oracle_hcm", re.compile(r"oraclecloud\.com/hcm|recruitingCEJobRequisitions", re.I)),
    ("successfactors", re.compile(r"successfactors\.com|career.?site", re.I)),
    ("workday", re.compile(r"myworkdayjobs\.com", re.I)),
    ("smartrecruiters", re.compile(r"smartrecruiters\.com", re.I)),
    ("jobvite", re.compile(r"jobvite\.com", re.I)),
    ("brassring", re.compile(r"brassring\.com", re.I)),
    ("avature", re.compile(r"avature\.net", re.I)),
    ("talentegy", re.compile(r"talentegy\.com|activatecdn\.azureedge", re.I)),
    ("ukg", re.compile(r"ukg\.com|ultipro\.com|recruiting\.ultipro", re.I)),
    ("cornerstone", re.compile(r"cornerstoneondemand\.com", re.I)),
    ("servicenow", re.compile(r"service-now\.com.*job|sn_csm", re.I)),
    ("adp", re.compile(r"workforcenow\.adp\.com|adp\.com/mascsr", re.I)),
    ("jazzhr", re.compile(r"applytojob\.com|jazzhr", re.I)),
    ("breezy", re.compile(r"breezy\.hr", re.I)),
    ("recruitee", re.compile(r"recruitee\.com", re.I)),
    ("teamtailor", re.compile(r"teamtailor\.com", re.I)),
    ("pinpoint", re.compile(r"pinpointhq\.com|pinpoint\.com", re.I)),
    ("pageup", re.compile(r"pageuppeople\.com", re.I)),
    ("silkroad", re.compile(r"silkroad\.com", re.I)),
    ("beamery", re.compile(r"beamery\.com", re.I)),
    ("gem", re.compile(r"gem\.com/careers|jobs\.gem", re.I)),
    ("dover", re.compile(r"dover\.io|app\.dover", re.I)),
    ("fountain", re.compile(r"web\.fountain\.com|fountain\.com", re.I)),
    ("workable", re.compile(r"apply\.workable\.com|workable\.com", re.I)),
    ("bamboohr", re.compile(r"bamboohr\.com/careers", re.I)),
    ("rippling", re.compile(r"rippling-ats", re.I)),
    ("comeet", re.compile(r"comeet\.com|comeet\.co", re.I)),
    ("personio", re.compile(r"jobs\.personio", re.I)),
]


def http_get(url: str, timeout: int = hub_http.DEFAULT_TIMEOUT) -> tuple[int, str, str]:
    return hub_http.http_get(url, timeout=timeout)


def hub_urls(co: dict, blocked: dict[str, str]) -> list[str]:
    cid = str(co.get("id") or "")
    seen: set[str] = set()
    out: list[str] = []
    for raw in (co.get("hub_url"), blocked.get(cid)):
        u = str(raw or "").strip()
        if not u or "myworkdayjobs.com" in u.lower() or u in seen:
            continue
        seen.add(u)
        out.append(u)
        if "://careers." in u:
            alt = u.replace("://careers.", "://jobs.", 1)
            if alt not in seen:
                seen.add(alt)
                out.append(alt)
    return out


def fingerprint_markers(blob: str) -> list[str]:
    found: list[str] = []
    for label, pat in ATS_PATTERNS:
        if pat.search(blob):
            found.append(label)
    return found


def scan_one(co: dict, blocked: dict[str, str]) -> dict[str, str]:
    cid = str(co.get("id") or "")
    urls = hub_urls(co, blocked)
    if not urls:
        return {
            "id": cid,
            "name": str(co.get("name") or cid),
            "hub_url": "",
            "fetch_status": "no_url",
            "final_url": "",
            "markers": "",
            "icims_hosts": "",
            "note": "",
        }
    best_markers: list[str] = []
    best_icims: list[str] = []
    status = ""
    final = ""
    used = urls[0]
    for url in urls:
        code, fin, body = http_get(url)
        blob = f"{fin}\n{body}"
        markers = fingerprint_markers(blob)
        icims = sorted(
            {
                m.group(0).lower()
                for m in re.finditer(r"https?://([a-z0-9-]+\.icims\.com)", blob, re.I)
                if "www.icims.com" not in m.group(0).lower()
            }
        )
        if markers or code == 200 or (body and len(body) > 500):
            used = url
            status = str(code)
            final = fin
            best_markers = markers
            best_icims = icims
            if markers:
                break
    return {
        "id": cid,
        "name": str(co.get("name") or cid),
        "hub_url": used,
        "fetch_status": status,
        "final_url": final,
        "markers": "|".join(best_markers),
        "icims_hosts": "|".join(best_icims[:5]),
        "note": "",
    }


def load_hubs(base_path: Path) -> list[dict]:
    cfg = hub_tools.load_base_bundle(base_path)
    return [c for c in cfg.get("companies", []) if str(c.get("type") or "").lower() == "hub"]


def load_blocked(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for row in csv.DictReader(path.open(), delimiter="\t"):
        alt = (row.get("guess_public_careers") or "").strip()
        if alt:
            out[row["id"]] = alt
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=BASE)
    parser.add_argument("--blocked-tsv", type=Path, default=BLOCKED_TSV)
    parser.add_argument("--out", type=Path, default=OUT_TSV)
    parser.add_argument("--workers", type=int, default=10)
    args = parser.parse_args()

    hubs = load_hubs(args.base)
    blocked = load_blocked(args.blocked_tsv)
    print(f"Fingerprinting {len(hubs)} hub employers (read-only, no config changes)…")

    rows: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = [pool.submit(scan_one, co, blocked) for co in hubs]
        for fut in as_completed(futures):
            rows.append(fut.result())

    rows.sort(key=lambda r: r["id"])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else []
    with args.out.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames, delimiter="\t")
        w.writeheader()
        w.writerows(rows)

    # Summary for requested ATS
    focus = {"greenhouse", "lever", "ashby", "salesforce", "taleo", "icims", "eightfold"}
    hits: dict[str, list[str]] = {k: [] for k in sorted(focus)}
    for r in rows:
        for m in (r.get("markers") or "").split("|"):
            if m in hits:
                hits[m].append(r["id"])

    print(f"Wrote {args.out}")
    for label in sorted(focus):
        ids = hits[label]
        print(f"  {label}: {len(ids)} hubs")
        if ids:
            print(f"    {', '.join(ids[:12])}{' …' if len(ids) > 12 else ''}")
    no_marker = [r["id"] for r in rows if not r.get("markers") and r.get("fetch_status") not in ("no_url",)]
    print(f"  (no ATS marker in HTML): {len(no_marker)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
