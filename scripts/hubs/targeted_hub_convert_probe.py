#!/usr/bin/env python3
"""Targeted hub convert/probe using fingerprint markers (faster than full discover).

Examples:
  ~/.v/bin/python scripts/hubs/targeted_hub_convert_probe.py --mode convert --apply
  ~/.v/bin/python scripts/hubs/targeted_hub_convert_probe.py --mode probe
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import hub_http
import hub_playwright
import hub_tools
import probe_hub_scrape_methods as probe
import discover_career_endpoints as discover
from discover_hub_ats_paths import METHOD_TO_TYPE, apply_row, Discovery

REPO_ROOT = hub_tools.REPO_ROOT
BASE = hub_tools.BASE_JSON
FP_TSV = hub_tools.report_path("quickjobs-hub-ats-fingerprint.tsv")
OUT_TSV = hub_tools.report_path("quickjobs-hub-targeted-convert-probe.tsv")
BLOCKED_TSV = hub_tools.BLOCKED_TSV

CONVERT_MARKERS = frozenset({"successfactors", "phenom", "icims", "eightfold"})
PROBE_MARKERS = frozenset({"adp", "jobvite", "avature", "taleo"})


def load_fingerprint() -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    with FP_TSV.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            out[row["id"]] = row
    return out


def load_blocked() -> dict[str, dict[str, str]]:
    if not BLOCKED_TSV.is_file():
        return {}
    return {r["id"]: r for r in csv.DictReader(BLOCKED_TSV.open(), delimiter="\t")}


def candidate_urls(
    co: dict[str, Any],
    fp_row: dict[str, str],
    blocked: dict[str, str] | None,
    markers: set[str],
) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        u = str(raw or "").strip()
        if u and u not in seen and "myworkdayjobs.com" not in u.lower():
            seen.add(u)
            urls.append(u)

    add(fp_row.get("final_url") or "")
    add(fp_row.get("hub_url") or "")
    add(co.get("hub_url") or "")
    add(co.get("browse_url") or "")
    if blocked:
        add(blocked.get("guess_public_careers") or "")
        add(blocked.get("browse_url") or "")
    # SuccessFactors job list usually lives on /search/ not the marketing page.
    if "successfactors" in markers:
        for base in list(urls):
            origin = "/".join(base.split("/")[:3])
            if origin.startswith("http"):
                add(f"{origin}/search/")
                add(f"{origin}/go/Search/")
                add(f"{origin}/search/?q=devops")
    return urls


def fetch_url(url: str) -> tuple[str, str, int]:
    code, final, body = hub_http.curl_fetch(url)
    body = body or ""
    if hub_playwright.should_playwright_fallback(int(code or 0), body):
        pw_code, pw_final, pw_body = hub_playwright.playwright_fetch(url, referer=url)
        if pw_code == 200 and pw_body and len(pw_body) > 200:
            return pw_final or url, pw_body, int(pw_code)
    return final or url, body, int(code or 0)


def run_probes_for_markers(
    cid: str,
    markers: set[str],
    start_url: str,
    final_url: str,
    body: str,
) -> list[probe.ProbeRow]:
    rows: list[probe.ProbeRow] = []
    want = markers

    def add(row: probe.ProbeRow | None) -> None:
        if row:
            rows.append(row)

    if "phenom" in want:
        add(probe.probe_phenom(cid, start_url, final_url, body))
    if "successfactors" in want:
        add(discover.probe_successfactors(cid, final_url or start_url, body))
        add(probe.probe_successfactors(cid, final_url or start_url, body))
    if "icims" in want:
        add(discover.probe_icims(cid, body, final_url or start_url))
    if "eightfold" in want:
        add(probe.probe_eightfold_pcsx(cid, final_url or start_url, body))
        add(probe.probe_eightfold_pcsx(cid, start_url, body))
    if "adp" in want:
        add(probe.probe_adp(cid, start_url, body, final_url))
    if "jobvite" in want:
        add(probe.probe_jobvite(cid, start_url, body, final_url))
    if "avature" in want:
        add(probe.probe_avature(cid, start_url, body, final_url))
    if "taleo" in want:
        add(probe.probe_taleo_legacy(cid, start_url, body, final_url))
    return rows


def best_ok(rows: list[probe.ProbeRow]) -> probe.ProbeRow | None:
    ok = [r for r in rows if r.status == "ok"]
    if not ok:
        return None
    ok.sort(key=lambda r: int(r.total_jobs or 0), reverse=True)
    return ok[0]


def process_one(
    co: dict[str, Any],
    markers: set[str],
    fp_row: dict[str, str],
    blocked: dict[str, str] | None,
) -> dict[str, str]:
    cid = str(co["id"])
    result = {
        "id": cid,
        "name": str(co.get("name") or cid),
        "markers": "|".join(sorted(markers)),
        "hub_url": "",
        "http_code": "",
        "final_url": "",
        "methods": "",
        "best_method": "",
        "status": "",
        "total_jobs": "",
        "recommended_type": "",
        "apply": "no",
        "config_hint": "",
        "note": "",
    }
    all_rows: list[probe.ProbeRow] = []
    last_code = 0
    tried = 0
    for url in candidate_urls(co, fp_row, blocked, markers)[:8]:
        tried += 1
        final, body, code = fetch_url(url)
        last_code = code
        if not result["hub_url"]:
            result["hub_url"] = url
            result["http_code"] = str(code)
            result["final_url"] = final
        if code != 200 or not body:
            continue
        if not result["final_url"]:
            result["final_url"] = final
        rows = run_probes_for_markers(cid, markers, url, final, body)
        all_rows.extend(rows)
        if best_ok(rows):
            result["hub_url"] = url
            result["http_code"] = str(code)
            result["final_url"] = final
            break

    result["methods"] = ";".join(f"{r.method}:{r.status}:{r.total_jobs}" for r in all_rows)
    best = best_ok(all_rows)
    if not best:
        if all_rows:
            all_rows.sort(key=lambda r: (0 if r.status == "empty" else 1, r.method))
            best = all_rows[0]
            result["best_method"] = best.method
            result["status"] = best.status
            result["total_jobs"] = best.total_jobs
            result["config_hint"] = best.config_hint
            result["note"] = best.error or "no ok probe"
        elif tried and last_code != 200:
            result["status"] = "fetch_fail"
            result["http_code"] = str(last_code)
            result["note"] = f"hub fetch failed http={last_code}"
        else:
            result["status"] = "no_probe"
            result["note"] = "no probe matched marker signals in HTML"
        return result
    result["best_method"] = best.method
    result["status"] = best.status
    result["total_jobs"] = best.total_jobs
    result["config_hint"] = best.config_hint
    rec = METHOD_TO_TYPE.get(best.method, "")
    if not rec and best.method.startswith("icims"):
        rec = "icims"
    if not rec and "successfactors" in best.method:
        rec = "successfactors"
    result["recommended_type"] = rec
    if best.status == "ok" and rec and rec != "hub":
        result["apply"] = "yes"
    else:
        result["note"] = best.error or "probe ok but no convertible type"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("convert", "probe", "both"),
        default="both",
    )
    parser.add_argument("--apply", action="store_true", help="Patch base.json for apply=yes rows")
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--ids", default="", help="Optional comma-separated id filter")
    args = parser.parse_args()

    want_ids = {x.strip() for x in args.ids.split(",") if x.strip()} if args.ids.strip() else set()
    fp = load_fingerprint()
    blocked_by = load_blocked()
    cfg = hub_tools.load_base_bundle()
    by_id = {c["id"]: c for c in cfg["companies"] if c.get("id")}

    targets: list[tuple[dict[str, Any], set[str], str, dict[str, str], dict[str, str] | None]] = []
    for cid, fp_row in sorted(fp.items()):
        if want_ids and cid not in want_ids:
            continue
        co = by_id.get(cid)
        if not co or str(co.get("type") or "").lower() != "hub":
            continue
        markers = {m for m in (fp_row.get("markers") or "").split("|") if m}
        mode = ""
        use: set[str] = set()
        if args.mode in ("convert", "both"):
            hit = markers & CONVERT_MARKERS
            if hit:
                use |= hit
                mode = "convert"
        if args.mode in ("probe", "both"):
            hit = markers & PROBE_MARKERS
            if hit:
                use |= hit
                mode = "both" if mode == "convert" else "probe"
        if use:
            targets.append((co, use, mode, fp_row, blocked_by.get(cid)))

    print(f"Targeted {len(targets)} hub employers (mode={args.mode}, workers={args.workers})", flush=True)
    rows: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futs = {
            pool.submit(process_one, co, markers, fp_row, blocked): (co["id"], mode)
            for co, markers, mode, fp_row, blocked in targets
        }
        done = 0
        for fut in as_completed(futs):
            done += 1
            cid, mode = futs[fut]
            try:
                row = fut.result()
            except Exception as exc:
                row = {
                    "id": cid,
                    "name": cid,
                    "markers": "",
                    "hub_url": "",
                    "http_code": "",
                    "final_url": "",
                    "methods": "",
                    "best_method": "",
                    "status": "error",
                    "total_jobs": "",
                    "recommended_type": "",
                    "apply": "no",
                    "config_hint": "",
                    "note": str(exc)[:120],
                }
            row["batch"] = mode
            rows.append(row)
            label = row["recommended_type"] if row["apply"] == "yes" else row["status"]
            print(f"  [{done}/{len(targets)}] {cid}: {label} ({row.get('best_method') or '-'})", flush=True)

    rows.sort(key=lambda r: (r.get("apply") != "yes", r["id"]))
    OUT_TSV.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "id",
        "name",
        "batch",
        "markers",
        "hub_url",
        "http_code",
        "final_url",
        "methods",
        "best_method",
        "status",
        "total_jobs",
        "recommended_type",
        "apply",
        "config_hint",
        "note",
    ]
    with OUT_TSV.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    applied: list[str] = []
    if args.apply:
        cfg = hub_tools.load_base_bundle()
        by_id = {c["id"]: c for c in cfg["companies"]}
        for row in rows:
            if row.get("apply") != "yes":
                continue
            co = by_id.get(row["id"])
            if not co or str(co.get("type") or "").lower() != "hub":
                continue
            disc = Discovery(
                id=row["id"],
                name=row["name"],
                careers_url=row.get("hub_url") or "",
                method=row.get("best_method") or "",
                status=row.get("status") or "",
                total_jobs=row.get("total_jobs") or "",
                keyword_hits="",
                recommended_type=row.get("recommended_type") or "",
                apply="yes",
                config_hint=row.get("config_hint") or "",
                url_tested=row.get("final_url") or row.get("hub_url") or "",
                error="",
                notes="",
            )
            apply_row(co, disc)
            applied.append(row["id"])
        if applied:
            hub_tools.save_base_bundle(cfg)

    ok = [r for r in rows if r.get("apply") == "yes"]
    print(f"Wrote {OUT_TSV}")
    print(f"Convertible: {len(ok)} / {len(rows)}")
    if applied:
        print(f"Applied to base.json: {len(applied)}")
        for cid in applied:
            print(f"  + {cid}")
    # summary by marker batch
    from collections import Counter

    print("\nStatus counts:")
    for k, v in Counter(r.get("status") or "?" for r in rows).most_common():
        print(f"  {v:3d}  {k}")
    print("\nBest methods:")
    for k, v in Counter(r.get("best_method") or "(none)" for r in rows).most_common():
        print(f"  {v:3d}  {k}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
